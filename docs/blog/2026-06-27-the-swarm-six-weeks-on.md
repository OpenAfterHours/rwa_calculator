# The Swarm, Six Weeks On: Reviewer-Gated Worktree Batches

*Post 4 said, in plain text, that "the orchestrator commands don't review the agents' work." Six weeks later that sentence is wrong, and the way it became wrong is the most interesting thing that has happened to this build pipeline since I wrote about it. A fifth agent now refuses bad work between every wave; each item builds in its own git worktree; and the orchestrator stopped being a script that runs once and became a supervisor that survives across turns.*

Published 2026-06-27. Code references are pinned to commit [`7e7ed7ec`](https://github.com/OpenAfterHours/rwa_calculator/tree/7e7ed7ec).

---

This post picks the series back up after the season-one finale ([*What I Got Wrong, What's Next*](2026-06-16-what-i-got-wrong-whats-next.md), 2026-06-16). That post closed a planned arc of eight; this one opens a second pass over the same ground, because the ground moved. The calculator is still a UK Basel 3.1 / PRA PS1/26 credit-risk RWA engine, still Polars, still one person directing a swarm of Claude Code agents. What changed is the swarm.

[Post 4 — *Building With an Agent Swarm*](2026-05-19-building-with-an-agent-swarm.md) — described four role-bounded agents dispatched as parallel waves behind one global validation gate, and it made a deliberate, load-bearing claim about how quality was enforced:

> The non-obvious property: the orchestrator commands don't "review" the agents' work. They route inputs and outputs through the validation gate. Agents make architectural mistakes constantly; the gate is what catches them.

That was true when I wrote it, and it was a defensible design. The gate is mechanical, deterministic, and impossible to sweet-talk: a `print()` in an engine module fails [ruff `T20`](https://docs.astral.sh/ruff/rules/print/) and rolls back the batch, a module-scope regulatory scalar fails [`scripts/arch_check.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/7e7ed7ec/scripts/arch_check.py), and neither of those failures depends on anyone's judgement. The thesis of post 4 was that you should *mechanise* enforcement rather than trust the agents to police themselves, and I still believe every word of that thesis.

But "mechanise enforcement" and "don't review the work" are not the same claim, and conflating them was the weak point. A deterministic gate catches grammar — the shapes the architecture forbids — and it catches them at the *end*, after four waves of agents have each built on whatever the previous wave produced. It does not catch a scenario-architect who quoted the wrong risk weight in wave 1, because a wrong-but-plausible number is grammatically perfect. By the time the global gate runs, three more agents have faithfully implemented that number, and the gate goes green on a portfolio that is quietly under-capitalised.

So the model grew a reviewer. This post is the honest account of what that did, what it cost, and what it deliberately did not change.

## What the orchestrator looks like now

The wrapper has not changed. [`loop.sh`](https://github.com/OpenAfterHours/rwa_calculator/blob/7e7ed7ec/loop.sh) is still about a hundred lines of bash that select a prompt file from a mode argument and pipe it into `claude -p` in a `while` loop, pushing the branch at the end of each iteration. It is the same dumb, reliable harness post 4 showed. The default build prompt is still effectively one line — *Run `/next-items 3`* — and all the intelligence still lives inside that slash command. That part of the design was right and I left it alone.

What changed is the command. In post 4, [`/next-items`](https://github.com/OpenAfterHours/rwa_calculator/blob/7e7ed7ec/.claude/commands/next-items.md) was a straight-through runbook: pick a batch, fire four parallel waves, run the gate once, commit, push, done — all inside a single Claude Code turn. Today it is an **event-driven, multi-turn supervisor**. The opening lines of the command now say so explicitly:

> This command spans **multiple turns**. The orchestrator (you) is an event-driven supervisor: kick off the batch in one turn, end the turn, then react to agent completion notifications and operator messages across subsequent turns until the batch is fully resolved.

Three structural changes carry that shift, and they are worth taking one at a time.

### One git worktree per item

A batch of `N` non-conflicting plan items used to run as `N` agents editing one working tree, separated only by the collision rules that kept them off each other's files. That worked, but it was fragile: two agents touching the same helper produced a tangle that the global gate would reject *as a whole*, losing the whole batch's work even though one item was clean.

Now each batched item gets its own branch and its own checkout:

```
git worktree add -b batch/<batch-id>/<P-code> ../rwa_calculator-<P-code> HEAD
```

Every agent working on item `P1.114` operates inside `../rwa_calculator-P1.114`, on branch `batch/<batch-id>/P1.114`, rooted at the merge target's HEAD. Items are now *physically* isolated rather than isolated by convention. A collision between two items can no longer corrupt a shared file mid-flight, because there is no shared file — there are `N` trees. The collision rules survive, but demoted from hard disqualifiers to "soft preferences," because the worktree merge surfaces a genuine conflict cleanly at the end instead of producing a silent tangle in the middle.

### Background dispatch and an operator who can talk back

In the old model the orchestrator dispatched a wave and *blocked* until it returned, inside one turn. You watched, or you walked away; you could not interrupt. Now every role-agent and every reviewer is dispatched with `run_in_background: true` and a stable name of the form `<role>-<P-CODE>-r<revision-count>`. The orchestrator fires the wave and *ends its turn*. When an agent finishes, the orchestrator wakes, processes the completion, dispatches the next thing, and ends its turn again.

The point is not just politeness to the scheduler. It is that the operator — me — can now chat with the orchestrator *while the batch is in flight*. The command lists this as first-class behaviour: ask for status and it summarises the live state; say "drop P1.114" and it marks the item dropped, attempts to `TaskStop` the in-flight agent, and persists the change; say "show me the wave-2 output for P1.97" and it reads it back. None of that was possible when a batch was one uninterruptible turn.

### State on disk, read at the top of every turn

A multi-turn supervisor that can be interrupted, compacted, or resumed cannot keep its truth in the conversation. So the orchestrator writes the batch to `.claude/state/next-items-<batch-id>.json` and — this is the load-bearing rule — **reads that file at the start of every turn before doing anything else**. The state file records, per item, its branch, worktree path, current wave, `agent_status`, a `revision_count` map keyed by wave, the stored agent `outputs`, and any `drop_reason`. Writes are atomic: the orchestrator writes `<file>.tmp` with the Write tool and then `mv`s it over the real file, because an LLM patching JSON line by line is exactly the kind of brittle that loses a batch.

This is the change that makes the rest viable. Context compaction is not a hypothetical when a batch of three items runs five waves each with reviews and retries — that is dozens of agent round-trips, easily more conversation than a single context window holds. The on-disk state means a compaction in the middle of a batch is a non-event: the next turn reads the file and knows precisely what is in flight, what passed review, and what is waiting. The conversation became supplementary. The file became the truth.

## The fifth agent

The role roster grew from six to seven. Post 4 named four build agents plus two read-mostly ones (`plan-curator`, `doc-writer`) that run in other loop modes. The new one is [`reviewer`](https://github.com/OpenAfterHours/rwa_calculator/blob/7e7ed7ec/.claude/agents/reviewer.md), and within the build loop it makes five: the four-wave chain `scenario-architect → fixture-builder → test-writer → engine-implementer`, with a reviewer gate **between every wave**.

The reviewer's own definition is blunt about what it is:

> You are a quality gate, not a fixer. You read one role-agent's output, check it against the criteria the orchestrator supplies inline, and return a single verdict.

That verdict is one of three tokens, and the orchestrator parses the first line to decide what happens next:

- `VERDICT: pass` — advance to the next wave (or, past wave 4, mark the item `merge_ready`).
- `VERDICT: revise` — the output is fixable; re-dispatch the *same* role-agent with the reviewer's feedback inline.
- `VERDICT: drop` — unrecoverable; skip the item, record the reason, tear it down later.

The reviewer's tools are `Read, Grep, Glob, Skill` — read-only, plus the `basel31` and `crr` regulatory reference skills. It has no `Edit`, no `Write`, no `Bash`. It cannot fix what it criticises, by construction, for the same reason `test-writer` cannot touch `src/`: a reviewer that can edit the work it reviews stops being a gate and becomes another author, and the independence that makes the verdict worth anything evaporates.

Crucially, the criteria the reviewer applies are not hidden inside its system prompt. They live in the `/next-items` command itself, as four explicit checklists — one per wave — pasted verbatim into the reviewer's prompt at dispatch time. The command says why:

> They are deliberately written here, not derived implicitly from each role-agent's system prompt, so the operator can audit and tune them in this single file.

So the wave-1 checklist (`C1.1`–`C1.6`) demands that a scenario-architect proposal name a framework and a specific article-plus-paragraph citation, map every input field to a real schema in [`contracts/bundles.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/7e7ed7ec/src/rwa_calc/contracts/bundles.py), put every regulatory term on its own line with a scalar attributed to a skill or a [rulepack pack](https://github.com/OpenAfterHours/rwa_calculator/tree/7e7ed7ec/src/rwa_calc/rulebook/packs), and carry an explicit "edge cases out of scope" section. The wave-3 checklist (`C3.1`–`C3.6`) insists the test-writer's new test *exists on disk*, *was run*, and *failed with an `AssertionError`* — not an import error, not a fixture-load error, not a collection error, which are the three ways a "failing test" can be failing for the wrong reason. The wave-4 checklist (`C4.1`–`C4.5`) demands every modified path sit under `src/rwa_calc/`, that none of the hard-excluded shared files were touched, and that the targeted pytest the test-writer named now passes.

And the retry budget is deliberately mean. One revision per wave per item. A `revise` verdict re-dispatches the role-agent once with feedback; a second `revise` on the same wave drops the item; a `drop` verdict drops it immediately with no retry. The arithmetic is in the supervisor's progression table, keyed on `revision_count[<wave>]`. The reason for the cap is the reason for the whole exercise: an agent that cannot fix its output given one round of specific, actionable feedback is not going to fix it given five, and burning context on a death-spiral starves the items that are actually progressing.

## A worked review

Here is the kind of error the reviewer was built to catch, drawn from a real open plan item — the season-one finale listed `P1.95` as "B31 SCRA grades for unrated institution guarantors."

Under Basel 3.1, an unrated institution exposure is risk-weighted by the Standardised Credit Risk Assessment approach (SCRA), which sorts the counterparty into one of three grades. For an exposure with original maturity over three months, the risk weights are **Grade A 40%, Grade B 75%, Grade C 150%** (PRA PS1/26 Art. 120-121; BCBS CRE20.16-21). There is also a *short-term* column for exposures of three months or less: Grade A 20%, **Grade B 50%**, Grade C 150%.

Now imagine a scenario-architect drafting the proposal for a £10m exposure to a Grade B institution, maturity well over three months. The honest, easy mistake is to read across the wrong row of the table and quote **50%** — the short-term Grade B weight — for a long-dated exposure. Grammatically the proposal is flawless: a real article, a real grade, a number that genuinely appears in the SCRA table. The hand-calc reads

```
EAD            = 10,000,000
SCRA grade     = B
risk weight    = 50%          (← wrong column: that is the ≤3-month weight)
RWA            = 5,000,000
```

when the correct figure is `10,000,000 × 75% = 7,500,000` — a £2.5m understatement of RWA on one exposure.

Under the post-4 model, nothing mechanical stops this. The fixture-builder builds a counterparty with `grade = B`; the test-writer pins `rwa == 5_000_000`; the engine-implementer makes that test pass; the global gate — `arch_check`, ruff, ty, contracts — runs green, because every one of those checks is about *shape*, and the shape is fine. The wrong number ships, and it is caught weeks later by a human reading the diff, or by a later acceptance scenario that happens to disagree. That is precisely the failure mode the finale catalogued under "things the agent swarm got wrong."

Under the reviewer model, the wave-1 checklist criterion `C1.3` requires the reviewer to spot-check each asserted scalar against the relevant skill. The reviewer reads the proposal, opens the `basel31` skill, finds the SCRA table, sees `RW(>3m) Grade B = 75%`, and the proposal's 50% does not match. Its own instructions are specific about the consequence — *"One wrong scalar warrants `revise`, not `drop`"* — so it returns `VERDICT: revise` with feedback naming the article, the right column, and the right number. The orchestrator re-dispatches the *same* scenario-architect with that feedback inline; the corrected proposal quotes 75%; the reviewer passes it; and the fixture, the test, and the engine code are all built on the right number from the start. The error was caught on the cheapest possible artifact — a markdown proposal — before three downstream agents spent any effort encoding it.

## What the reviewer catches, and what it still does not

It would be easy to over-claim here, and the finale's honesty is worth keeping faith with. The reviewer mechanises a *slice* of what used to be entirely my job, not the whole of it.

What it catches that the global gate never could: a wrong scalar (the worked example), a citation to an article that does not contain the rule, a "failing" test that is actually failing on an import error, a fixture file that was reported but never written to disk, an engine diff that strayed into a hard-excluded shared file. All of these are things the deterministic gate is blind to because they are semantic or because they are *between* waves rather than at the end. The reviewer sits on the boundary where the old model had nothing but my eyes, and it sits there on *every* wave, for *every* item, without getting tired at 4am.

What it still does not catch is the harder half, and the reviewer's own prompt is honest about the boundary: *"No re-deriving the regulatory math from scratch... You spot-check scalars against the reference skills; you do not redo the hand-calc."* The most expensive failures the finale documented were not wrong scalars — they were *right scalars applied to the wrong unit*. The SME supporting factor that evaluated per-counterparty instead of per-group-of-connected-clients used the correct threshold; the bug was the unit. The multi-rating logic that collapsed to "most recent wins" used defensible defaults; the bug was that Art. 138 prescribes a different selection. A scalar spot-check sails straight past both. A reviewer reading only the supplied criteria, forbidden from re-deriving the math, will pass a proposal whose every number is real and whose every number is attached to the wrong thing.

So the division of labour matured rather than dissolved. The reviewer absorbed the mechanical regulatory check — *is this number the number the rule book actually states?* — which was the most tedious, most automatable part of what I did per iteration. The irreducibly human part — *is this the right rule, applied to the right unit, when two articles overlap?* — stayed exactly where post 4 and the finale left it: with me. The reviewer did not replace judgement. It cleared the judgement of its busywork.

## What it cost

Worktrees are not free. Each item is a full checkout — for a repository this size that is real disk and real provisioning time, paid `N` times per batch. The teardown is fiddly: `git worktree remove --force` and `git branch -D` for every item including the dropped ones. A crashed batch can leave orphan worktrees that the next run trips over, which is why the command pins teardown to a strict cleanup step — a litter of stale `../rwa_calculator-*` directories is annoying to clean by hand.

There is also a real concession in the design: hard-excluded items skip worktrees entirely. Any item that must touch a genuinely shared file runs single-stream in the main tree, the old way, because *"the worktree machinery is only worth it when N>1."* And that shared-file list has grown. Post 4 forced single-stream on changes to `engine/pipeline.py`, `contracts/protocols.py`, `contracts/bundles.py`, and `engine/aggregator/aggregator.py`. The list now also includes [`engine/registry.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/7e7ed7ec/src/rwa_calc/engine/registry.py) and [`engine/orchestrator.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/7e7ed7ec/src/rwa_calc/engine/orchestrator.py) — the two files the [Phase-4 fold](../plans/target-architecture-migration.md) made central. The registry is the single literal, ordered list of the ten pipeline stages; the orchestrator is the fold that threads an immutable context through them. Two agents editing either one in parallel is a guaranteed tangle, so the command refuses to let them.

And the reviewer itself costs latency and tokens. Five waves became five waves plus four reviews, each review a full agent round-trip, each potential `revise` another. A batch that used to be one turn is now a dozen or more. The trade is deliberate: the build loop runs unattended, so wall-clock latency is cheap; what is expensive is a wrong number reaching a commit, because that costs *me* a debugging session days later. Spending agent round-trips to spend less of my attention is the entire economic logic of the swarm, and the reviewer is that logic applied one level deeper.

## What did not change

The squash-and-gate boundary at the end is the same shape post 4 described, just relocated to the worktree world. Once every item is `merge_ready` or `dropped`, the orchestrator checks out the feature branch and `git merge --squash`es each surviving worktree branch in tier-priority order, then runs the **single global validation gate** once on the merged tree: `arch_check.py`, `ruff check`, `ruff format --check`, `ty src/`, the contracts suite, and the union of the batch's new tests. The plan is ticked only if that gate is green. A merge conflict drops its item rather than aborting the batch — the work is regenerated cleanly next time. The gate still runs *once*, not per agent, for the same reason post 4 gave: per-agent gate runs would churn ruff redundantly across each other's edits and waste the parallelism.

The call graph is still exactly one level deep: orchestrator → one of the five build agents, and nothing deeper. Sub-agents do not spawn sub-agents; the reviewer dispatches nothing. Agents still never commit — every commit in the whole pipeline lands in the orchestrator, at the squash step and the plan-tick step, never inside a role-agent. Those two invariants are the spine of the whole thing and they are untouched.

And the deterministic gate kept growing underneath all of this. Post 4 advertised eight architectural checks in `arch_check.py`. There are now **seventeen**. The nine new ones are mostly the Phase-4 migration's guards — check 14 bans Polars namespace registrations outright, check 15 demands the stage registry be a literal tuple with no conditionals, check 16 enforces stage anatomy, check 17 forbids an engine module from branching on `config.is_crr` / `config.is_basel_3_1` (regime behaviour reads a cited pack `Feature` instead). The thesis of post 4 — that you mechanise the rules you *can* mechanise and let a refusing gate enforce them — did not weaken. It got nine checks stronger. What the reviewer added was a second, judgement-bearing gate in front of it, for the rules a deterministic checker structurally cannot see.

That is the honest shape of the evolution. Post 4's role boundaries are intact. Post 4's refusing gate is intact and larger. What I got wrong in post 4 was the sentence that said the orchestrator does not review the work — not because reviewing the work is somehow better than mechanising the rules, but because the two are different jobs, and a regulated codebase needs both. The deterministic gate refuses the shapes the architecture forbids. The reviewer refuses the numbers the rule book forbids. Between them, the throughput is the same three-ish closed Tier-1 items per iteration the finale quoted — but a smaller fraction of those items now reach my diff review carrying a number that was wrong from wave one. The shape of enforcement matured. The thesis held.

If you want the live figures rather than a snapshot, the repository now ships [`scripts/blog_counts.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/7e7ed7ec/scripts/blog_counts.py), which prints the canonical counts this series quotes — roughly 7,450 test functions across the layers, 186 source modules, seventeen architectural checks, seven role agents, ten pipeline stages — straight from the tree, so the next person to write about this codebase does not have to take my word for any of them.

---

**Read next:** back to the [series index](index.md) — the full arc from the pipeline architecture through the output floor, CRM edge cases, the test strategy, and the season-one retrospective.

**Further reading:**

- [`/next-items` command](https://github.com/OpenAfterHours/rwa_calculator/blob/7e7ed7ec/.claude/commands/next-items.md) — the multi-turn supervisor runbook in full, including the per-wave reviewer checklists.
- [`reviewer` agent](https://github.com/OpenAfterHours/rwa_calculator/blob/7e7ed7ec/.claude/agents/reviewer.md) — the read-only quality gate and its `pass | revise | drop` contract.
- [Architecture: Pipeline](../architecture/pipeline.md) and the [target-architecture migration plan](../plans/target-architecture-migration.md) — the Phase-4 fold whose shared files (`registry.py`, `orchestrator.py`) are now forced single-stream.
- [Post 4 — *Building With an Agent Swarm*](2026-05-19-building-with-an-agent-swarm.md) — the snapshot this post updates, kept as-is on purpose.
- [Citation tracking](../development/citation-tracking.md) and the [testing strategy](../development/testing.md) — the deterministic half of the enforcement the reviewer sits in front of.
