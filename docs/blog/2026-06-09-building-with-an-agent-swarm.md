# Building With an Agent Swarm

*A 90-line bash loop, four role-bounded Claude Code agents, and a pre-commit hook that refuses to take "but my test passes" for an answer. This is what AI-assisted engineering looks like when the rule book is unforgiving.*

Published 2026-06-09. Code references are pinned to commit [`cceaee4`](https://github.com/OpenAfterHours/rwa_calculator/tree/cceaee4).

---

This is post 4 in the series on building this UK Basel 3.1 RWA calculator. Posts 1–3 covered why the calculator exists, how its pipeline is shaped, and how the Standardised Approach actually works. This post is the unusual one: how the codebase gets *written*, given that the person whose name is on the commits — me — did not type most of the code.

If you have read enough breathless takes on AI coding to last a lifetime, this is not that. The honest version of "agents wrote the calculator" is closer to "I designed a pipeline of agents with strict role boundaries, wrote the prompts that constrain each one, designed the validation gates that refuse work that violates the architecture, and reviewed every diff." The agents do the typing. The interesting question is what scaffolding has to be in place before that division of labour produces regulatory-grade code, and what failure modes you have to defend against.

*Update (June 2026): the agent workflow described here is accurate for the period, but the `data/tables/` value home it references (both the "prefer adding a row to an existing data table" implementer guidance and the collision rule keyed on "a different `data/tables/` file") was later replaced by the rulebook packs. A new regulatory value now goes into `src/rwa_calc/rulebook/packs/{common,crr,b31}.py` as a cited entry — see the "pack-as-value-home" guidance in `CLAUDE.md` — and the collision rules key on the relevant engine sub-package / pack instead. The build loop has also evolved beyond the four-agent, no-review picture above. A fifth role agent, `reviewer`, now gates every wave with a `VERDICT: pass | revise | drop` (one revision retry allowed) — superseding the claim below that the orchestrator commands "don't review" the agents' work — so the role-agent roster is now seven: `scenario-architect`, `fixture-builder`, `test-writer`, `engine-implementer`, `reviewer`, `plan-curator`, `doc-writer`. `/next-items` now runs each item in its own git worktree (branch `batch/<batch-id>/<P-code>`), dispatches the agents in the background so the operator can chat with the orchestrator mid-batch, persists batch state under `.claude/state/`, and squash-merges the surviving branches into the feature branch before the single end-of-batch gate; the forced-single-stream shared-file list now also includes `engine/registry.py` and `engine/orchestrator.py`. `arch_check.py` is up to 17 checks (the "eight" under Further reading was the `cceaee4`-era count), and `loop.sh` is now a ~100-line mode-selector shim, with the real orchestration in the slash commands. For the full current account, see the two-months-on retrospective ([`2026-09-29-the-swarm-two-months-on.md`](2026-09-29-the-swarm-two-months-on.md), forthcoming).*

## What is actually running

The orchestrator is 90 lines of bash. Here is the meaningful half of it:

```bash
while [[ $ITERATION -lt $MAX_ITERATIONS ]]; do
    LOGFILE="logs/${MODE}_$(date +%Y%m%d_%H%M%S)_iter${ITERATION}.jsonl"

    cat "$PROMPT_FILE" | claude -p \
        --dangerously-skip-permissions \
        --output-format=stream-json \
        --include-partial-messages \
        --model opus \
        --verbose \
        | tee "$LOGFILE" \
        | python3 scripts/render_stream.py

    git push origin "$CURRENT_BRANCH" || git push -u origin "$CURRENT_BRANCH"
    ITERATION=$((ITERATION + 1))
done
```

(Trimmed from [`loop.sh`](https://github.com/OpenAfterHours/rwa_calculator/blob/cceaee4/loop.sh).)

Run `./loop.sh 20` and the loop pipes a prompt file (`PROMPT_build.md` by default) into Claude Code in headless mode, twenty times, with auto-approval on tool calls and Opus as the primary model. Each iteration's full JSON event stream is captured to `logs/`, rendered TUI-style to the terminal in real time by `scripts/render_stream.py`, and the working branch is pushed at the end of each iteration so a crash does not lose work.

There is nothing clever about the wrapper. The cleverness is what the prompt file does.

The default prompt is one line: `Run /next-items 3.` That single slash command — implemented as a Claude Code custom command at [`.claude/commands/next-items.md`](https://github.com/OpenAfterHours/rwa_calculator/blob/cceaee4/.claude/commands/next-items.md) — drives a complete iteration. It picks up to three non-conflicting work items from `IMPLEMENTATION_PLAN.md`, dispatches a four-stage agent pipeline as parallel waves, runs the global validation gate exactly once at the end, commits each item separately on green, and pushes. If the gate is red, no commits are made and the next iteration inherits the unfinished state.

The whole codebase, in build mode, is one bash loop calling one slash command calling four agents.

## The four agents and their walls

Every agent is defined as a Markdown file under `.claude/agents/`. Each one has frontmatter declaring its allowed tools, the file paths it owns exclusively, and the model it runs on. The prompt body sets out its workflow. The orchestrator dispatches them by name; Claude Code routes the dispatch through the file definitions.

The four build-mode agents are:

- **`scenario-architect`** is read-only. Its only output is a structured Markdown proposal: a scenario header, an inputs table mapped to the bundle schema, a hand-calculation with every regulatory term on its own line and a citation per scalar, expected outputs that match the hand-calc, and an explicit "out of scope" list so downstream agents do not over-assert. It has no Edit or Write tool. It cannot run tests. It cannot invent a fixture path. ([`.claude/agents/scenario-architect.md`](https://github.com/OpenAfterHours/rwa_calculator/blob/cceaee4/.claude/agents/scenario-architect.md).)
- **`fixture-builder`** owns `tests/fixtures/` exclusively. It cannot edit `src/`, `tests/unit/`, or `tests/acceptance/`. It implements parquet rows and Python builder functions from the architect's proposal. It runs `uv run python tests/fixtures/generate_all.py` before returning to confirm the parquet outputs regenerate cleanly.
- **`test-writer`** owns `tests/{unit,acceptance,contracts,integration}/`. It cannot edit `src/`. Its job is to write *one cleanly failing test* that pins the behaviour described in the proposal. Failure mode and pytest invocation are reported back to the orchestrator. If the proposal needs a contract test that does not yet exist, it writes that too.
- **`engine-implementer`** owns `src/rwa_calc/`. It cannot edit `tests/` or `docs/`. Its workflow, lifted verbatim from its agent definition: reproduce the failing test, find the right insertion point in the engine module, prefer extending an existing function over adding a new one, prefer adding a row to an existing data table over a new module, make the *smallest* change that turns the test green, run the validation gate in order, and stop if any previously-passing unrelated test fails. No "while I'm here" cleanup.

The walls between them are the load-bearing structure. If `engine-implementer` could rewrite the failing test, the four-stage pipeline degenerates into one agent doing all the work and convincing itself it succeeded. If `test-writer` could touch `src/`, the test and the implementation drift toward each other until both pass without proving anything. The role-bounded files are how I make those failure modes structurally impossible rather than rely on the agents to remember the rules.

There are also two read-mostly agents — `plan-curator` (owns the two root plan files) and `doc-writer` (owns `docs/`) — but those run in different loop modes (`docs_build`, `plan`, `docs_plan`). The build loop only ever invokes the four above.

## The orchestrator: parallel waves with one global gate

`/next-items 3` is the meat of the build loop. The "3" is the batch width. The slash-command file ([`next-items.md`](https://github.com/OpenAfterHours/rwa_calculator/blob/cceaee4/.claude/commands/next-items.md)) is essentially a tightly-specified runbook for the top-level Claude Code session:

1. **Pick a non-conflicting batch.** Walk `IMPLEMENTATION_PLAN.md` in tier order. For each candidate, infer its change footprint from the `Ref:` field, the cited file paths, and the named test. Apply collision rules: each batched item must touch a *different* engine sub-package, a *different* `data/tables/` file, and produce a *different* new test path. Two SA fixes in one batch is a collision; two CRM fixes likewise. Items that touch any of `engine/pipeline.py`, `contracts/protocols.py`, `contracts/bundles.py`, or `engine/aggregator/aggregator.py` are forced single-stream — the orchestrator picks them alone even when `N>1` was requested, and reports the downgrade. The collision rules exist because four parallel waves cannot safely converge if two agents are editing the same file.
2. **Four parallel waves.** Wave 1 dispatches N `scenario-architect` calls in a single message — Claude Code runs them concurrently, each with the verbatim plan-item bullet as input. Wave 2 dispatches `fixture-builder` for each item that needs new fixtures (items that don't are skipped). Wave 3 dispatches `test-writer` for each item with its proposal and fixture report. Wave 4 dispatches `engine-implementer` for each item with its proposal, fixture report, and failing test.
3. **One global validation gate.** *Once*, after wave 4 completes for all N items: `arch_check.py` + `ruff check` + `ruff format --check` + `ty src/` + the contracts test suite. The gate runs once per batch — not per agent, not per item. Per-agent gate runs would `N×`-redundantly churn ruff and format on each other's edits and waste the entire batch's parallelism.
4. **Commit per item, then tick the plan.** On green, each of the N items gets its own commit. The `IMPLEMENTATION_PLAN.md` ticks land in one final `chore(plan): tick N code items` commit. Then push. On red, no commits are made — the next iteration inherits the working tree as-is and the operator sees the gate's diagnostic.

The non-obvious property: the orchestrator commands don't "review" the agents' work. They route inputs and outputs through the validation gate. Agents make architectural mistakes constantly; the gate is what catches them. A `print()` statement in an engine module ([ruff `T20`](https://docs.astral.sh/ruff/rules/print/)) fails the gate and rolls back the batch. A regulatory scalar declared at module scope in `engine/sa/` fails `arch_check.py` check 5 and rolls back the batch. A new stage that doesn't declare `logger = logging.getLogger(__name__)` fails check 8. The agents do not know the rules in detail; they discover them by tripping over the gate, fix forward, and converge on architecture-shaped diffs.

## The pre-commit gate is a Claude Code hook

The validation gate also exists as a separate, defence-in-depth layer: a Claude Code `PreToolUse` hook that fires on `Bash(git:*)` commands and refuses commits that fail the architectural checks. The hook is 40 lines:

```bash
INPUT=$(cat)
COMMAND=$(echo "$INPUT" | python -c "import sys,json; ...")

# Only gate git commit commands
echo "$COMMAND" | grep -qE '\bgit\b.*\bcommit\b' || exit 0

ARCH_OUT=$(uv run python scripts/arch_check.py 2>&1)
if [[ $? -ne 0 ]]; then
    FAILED=1
    ERRORS="${ARCH_OUT}"$'\n'
fi

RUFF_OUT=$(uv run ruff check src/ 2>&1)
if [[ $? -ne 0 ]]; then
    FAILED=1
    ERRORS="${ERRORS}${RUFF_OUT}"$'\n'
fi

if [[ $FAILED -ne 0 ]]; then
    echo '{"continue": false, "stopReason": "..."}'
else
    echo '{"continue": true}'
fi
```

(From [`scripts/pre_commit_gate.sh`](https://github.com/OpenAfterHours/rwa_calculator/blob/cceaee4/scripts/pre_commit_gate.sh).)

The hook reads the tool-call JSON from stdin, checks whether the command is a `git commit`, runs `arch_check.py` and `ruff`, and emits `{"continue": false}` if either fails. Claude Code blocks the tool call and returns the diagnostic to the agent, which must then fix forward.

The reason this is a hook rather than just a step in the slash-command runbook: agents try to commit. Often. Especially when something is half-working and they are looking for a checkpoint. If the only thing standing between them and a green-looking commit is the agent's own discipline, the discipline will erode. The hook does not erode. It will refuse a commit at 4am on a Sunday because someone called `print()` from `engine/sa/calculator.py`, and that is exactly what it should do.

## Walking one item end to end

The most recent build commit on the calculator (as of writing) is `b8ce937`, [version 0.2.3](../appendix/changelog.md), from 2026-04-28: *"facility undrawn generation now respects the `committed` flag."* It is a small, clean example of the four-stage pipeline producing a minimum-diff fix to a real regulatory gap.

The plan item came from `IMPLEMENTATION_PLAN.md`: a tier-1 (calculation correctness) bullet noting that `engine/hierarchy.py::_calculate_facility_undrawn` was generating a synthetic `facility_undrawn` exposure row for every facility, regardless of whether the facility was an irrevocable lending commitment. Under CRR Art. 166 and PS1/26 Art. 166C, an unconditionally cancellable facility carries no commitment EAD or RWA against unused headroom. A `committed: bool` column already existed on `FACILITY_SCHEMA` (`data/schemas.py`) but was dormant — nothing in the pipeline read it.

The walk:

- **Wave 1 (scenario-architect)** produced a proposal: the regulatory citation (Art. 166 / 166C), an inputs table specifying a counterparty + a single facility with `committed=False` + zero loans, the expected output (no `facility_undrawn` row in the unified exposures frame), and an out-of-scope list (loans and contingents already mapped to such facilities are *unaffected* — they should still flow through `_unify_exposures` normally).
- **Wave 2 (fixture-builder) was skipped.** The existing `tests/fixtures/exposures/facilities.py` already had a `FAC_CORP_UNCOMMIT_001` row declared with `committed=False` for the SA CCF tests; no new fixture rows were needed. The architect's proposal noted this and the orchestrator passed an empty fixture report into Wave 3.
- **Wave 3 (test-writer)** added four unit tests to `tests/unit/test_hierarchy.py`: `test_uncommitted_facility_suppresses_undrawn_row` (no synthetic row generated), `test_committed_null_treated_as_committed` (defensive null handling), `test_uncommitted_facility_loans_still_flow` (loans mapped to uncommitted facilities still appear in the unified output), and `test_uncommitted_facility_contingents_still_flow`. The mislabeled pre-existing `test_facility_uncommitted_lr_risk_type` (which actually used `committed=True`) was renamed to `test_facility_lr_risk_type`. The test for the new behaviour failed cleanly with the right message.
- **Wave 4 (engine-implementer)** added a single defensive filter to `_calculate_facility_undrawn`: `pl.col("committed").fill_null(True) if "committed" in facility_cols else pl.lit(True)`. The `fill_null(True)` is because pipeline tests use minimal schemas without the column at all; the conditional defaults missing schemas to "all committed" so legacy callers continue to generate synthetic rows. The schema default for `committed` was flipped from `False` to `True` in `data/schemas.py:69` so omitted columns mean "committed" rather than "uncommitted." Three lines of engine change, one schema-default flip, regulatory citation in the docstring.
- **Validation gate**: `arch_check.py` clean, `ruff` clean, `ty` clean, contracts pass, full suite 5,521 passed. Acceptance goldens unchanged because the only existing `committed=False` fixture (`FAC_CORP_UNCOMMIT_001`) was not asserted against in any expected-output JSON.
- **Commit, push, plan tick.** The commit message and the changelog entry both cite Art. 166 / 166C and name the test that pins the behaviour.

What I want you to notice about this walk: the agents made no architectural decisions. The proposal cited the right regulation. The test pinned the right behaviour. The engine change was the smallest possible diff that satisfied the test and the gate. None of that is because the agents are smart in some general sense; it is because the prompts and gates make any other answer mechanically harder than the right one.

## Failure modes and what humans actually do

Three classes of failure recur, and three things stay decisively human.

**Failure 1: the proposal is regulatorily wrong.** This is by far the most common failure. The architect cites the right *Article* but the wrong *paragraph*; or invents a scalar that does not exist; or builds a hand-calculation on a misread of a table footnote. Mitigation: the architect's prompt forbids inventing scalars from training data and requires every regulatory term to be sourced from the `basel31` or `crr` skill (which read the actual PDFs). The fixture-builder and test-writer cannot recover from a wrong proposal — they will faithfully implement nonsense — so the architect's accuracy is on the critical path. I review every architect proposal before it advances to fixtures. That is the most expensive thing I do per iteration; it is the least automatable; it is unavoidable.

**Failure 2: the test is the wrong test.** The test-writer occasionally writes a test that asserts on the *wrong field* — e.g. on `risk_weight` instead of `effective_risk_weight`, or on the SA result when the scenario should have routed to IRB. The gate doesn't catch this; the gate only checks that something passes. Defence: the contract test suite (`tests/contracts/`) pins the *shape* of the bundles and the routing rules between them, so a misrouted exposure tends to fail a contracts test even when the test-writer's chosen test passes. When a misrouted test does pass alone, the next iteration's regression set tends to surface it.

**Failure 3: the implementer makes the right change for the wrong reason.** The most insidious failure. The implementer adds a special-case branch in the calculator that produces the right number for the test fixture but does so by reading a column that wasn't designed to carry that meaning, or by short-circuiting an expression chain in a way that breaks an unrelated case. The validation gate catches grammatical violations (no `print()`, no inline regulatory scalars), not semantic ones. Defence: the implementer's prompt says "prefer extending an existing function over adding a new one; prefer adding a row to an existing data table over a new module" — and I read every diff. There is no automation that replaces this. If the implementer touched more than three files, I am suspicious; if it touched more than five, I make it justify each one.

**What stays human.** Architecture changes — touching `engine/pipeline.py`, the contracts, or the orchestrator — are forced single-stream by the slash command and reviewed against the patterns from [post 2](2026-05-12-the-pipeline.md) before they are accepted. Plan curation — deciding which item is tier 1 vs tier 4, what counts as a code bug vs a documentation gap — is the `plan-curator` agent's job to *propose*, mine to *adjudicate*. Public regulatory interpretations (which Article applies, which paragraph governs, what "material dependence" means in Art. 124E) get my eyes before they ship. The agents are very good at applying regulatory text once the right text is identified; they are mediocre at deciding which text is the right one when two Articles overlap.

## What this is, and what it is not

What this is: a way to extract eight to ten hours of attention from one human and produce roughly the throughput of a small team writing a regulated codebase. Not by replacing engineering judgement; by mechanising the parts of engineering that look like judgement but are actually pattern-matching against a written rule book. The architecture (post 2), the regulation (post 3), and the gates (this post) absorb the judgement that would otherwise have to live in a junior developer's head. Once those are in place, the agents do the typing, and they type fast.

What this is not: autonomous. The loop runs while I am asleep, but only because I have read the previous day's diffs before going to bed and the gates are tight enough that the worst the loop can do overnight is fail a hundred validation gates and commit nothing. I have never shipped a release without reading the changelog entries it produced. I do not believe anyone responsibly can.

What I have learned: the hard work is the prompts, the gates, and the role boundaries. The model is not the binding constraint. A weaker model behind these scaffolds writes better code than a stronger model without them. If you read this and want to try it, start with the gates — `arch_check.py` and the contract tests — before you write the prompts. The prompts are useless without something willing to refuse their output.

Post 5 in the series goes back to regulation: the 72.5% output floor under Basel 3.1, why it exists, how it works mechanically, and what it does to a real portfolio.

---

**Read next:** [*The Output Floor and Why Basel 3.1 Bites*](2026-06-23-the-output-floor-and-why-basel-31-bites.md).

**Further reading:**

- [Architecture: Pipeline](../architecture/pipeline.md) — the calculator's pipeline that the agents are writing into.
- [`scripts/arch_check.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/cceaee4/scripts/arch_check.py) — the eight architectural checks that run before every commit.
- [Claude Code documentation](https://docs.claude.com/claude-code) — the harness the loop runs on.
