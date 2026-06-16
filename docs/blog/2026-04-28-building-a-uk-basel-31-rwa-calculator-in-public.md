# Building a UK Basel 3.1 RWA Calculator in Public

*An open-source reference implementation, written mostly by AI agents under human direction, and what it taught me about both regulation and engineering.*

Published 2026-04-28.

---

On 1 January 2027, the UK's implementation of Basel 3.1 — the PRA's [Policy Statement 1/26](https://www.bankofengland.co.uk/prudential-regulation/publication/2026/january/implementation-of-the-basel-3-1-final-rules-policy-statement) — comes into force. For UK banks using the standardised approach to credit risk, exposure classification gets stricter and several risk-weight bands move. For banks using internal models, parameter floors tighten and a 72.5% output floor caps the benefit of using IRB at all. The net effect for most UK firms is more capital held against the same balance sheet.

I have been building an open-source reference implementation of credit-risk RWA under both the current rules ([CRR](https://www.legislation.gov.uk/eur/2013/575/contents), as onshored) and PS1/26. It runs roughly 5,300 tests, including around 500 acceptance scenarios where the expected outputs are hand-derived from the regulatory text. It supports Standardised, Foundation IRB, Advanced IRB, slotting, equity, the output floor, and the parts of CRM that turn out to matter most. As of this week it passes 100% of the CRR acceptance suite and 100% of the Basel 3.1 acceptance suite.

I built it largely by directing a swarm of [Claude Code](https://www.anthropic.com/claude-code) agents.

This is the first post in a series about that experience. The series alternates between two things I think are worth writing about:

- **What the regulation actually says when you read it carefully** — and why most engineering treatments of "Basel risk weights" fail to capture how the rules behave in edge cases.
- **What it is like to drive a small team of language-model agents through a regulatory codebase** — what they do well, where they break, and what scaffolding makes the difference between useful and useless.

Both audiences should get something out of every post. If a post feels too far in one direction, that is a bug; tell me.

## What the calculator actually does

The pipeline is conceptually simple:

```
RawDataBundle
  -> Loader
  -> HierarchyResolver
  -> Classifier
  -> CRMProcessor
  -> SA / IRB / Slotting / Equity calculators
  -> OutputAggregator
  -> AggregatedResultBundle
```

Each stage takes an immutable bundle and returns a new immutable bundle. Errors flow through a `list[CalculationError]` rather than exceptions; data quality issues are accumulated, not raised. The whole thing is built on Polars `LazyFrame`, so the entire computation graph for a portfolio is a single logical plan that materialises only at the aggregator boundary.

*Update (June 2026): a 2026-06 architecture migration replaced cross-stage laziness with a fold over a literal stage registry (`engine/registry.py` + `engine/orchestrator.py::run_stages`) that threads an immutable `PipelineContext` and exchanges eagerly-sealed frames at every stage exit — there is no longer a single logical plan deferred to the aggregator boundary. See the [Architecture: Pipeline](../architecture/pipeline.md) page for the current model.*

That sounds tidy. It is not, in fact, tidy. By the time you have:

- handled multi-level rating inheritance (own → parent → ultimate parent, internally and externally, separately, because internal PD and external CQS are not the same animal),
- split residential-real-estate loans across the LTV bands required by PS1/26 Article 124–124D,
- routed cross-approach guarantees so an IRB exposure guaranteed by a sovereign-rated counterparty picks up SA CCFs on the guaranteed slice,
- and prevented AIRB-modelled collateral from being double-counted against the same exposure,

…the "simple pipeline" has accumulated about 600 audit items between the implementation plan and the docs plan. The fact that the audit is exhaustive is the point. A regulatory engine you cannot trace is a regulatory engine you cannot certify.

## Why I am writing about this

Two reasons.

First, **the regulation is genuinely interesting and badly explained**. Most public material on Basel 3.1 is either marketing ("get ready for compliance!") or impenetrable ("see Article 92a(1)(b)(ii)"). There is a useful gap between "executive summary" and "the rule book itself" — concrete worked examples, edge cases, what the rule does to a real portfolio. This series tries to fill that gap for the parts I have implemented.

Second, **I want to be honest about what AI-assisted engineering looks like at this scale**. The codebase is roughly 114 source files and 231 test files. I did not personally type most of it. I did design the agent pipeline, write the prompts, design the validation gates, and review every diff. The right framing is not "AI wrote it" or "I wrote it"; it is "I directed a small team that happens to be made of language models, and the gates I wrote determine whether the team produces correct work or hallucinated nonsense". Post 4 in this series goes deep on what that actually means in practice.

## What is in the series

| # | Title | What it covers |
|---|---|---|
| 1 | Building a UK Basel 3.1 RWA Calculator in Public | This post. |
| 2 | The Pipeline: Why Regulation Forced an Immutable Design | Architecture. Why protocols, frozen dataclasses, and LazyFrames fall out of audit requirements rather than aesthetic preference. |
| 3 | Risk Weights Are Not a Lookup Table | Standardised approach and exposure classification. The RE splitter, ECRA vs SCRA, retail granularity. |
| 4 | Building With an Agent Swarm | How `loop.sh`, the four-stage agent pipeline, and the pre-commit gate produce regulatory-grade code without me typing most of it. |
| 5 | The Output Floor and Why Basel 3.1 Bites | The headline change for IRB banks. Mechanics, motivation, what shows up in real portfolios. |
| 6 | CRM, MOFs, and Other Edge-Case Archaeology | A tour of the regulatory edge cases that took disproportionate effort. |
| 7 | Testing a Regulatory Engine | 5,300 tests, hand-derived golden files, hash-locked oracles, and the contracts that keep the layers separated. |
| 8 | What I Got Wrong, What's Next | Honest retrospective and the open roadmap. |

Posts will land roughly every two to three weeks.

## Who this is for

If you write code that interacts with credit-risk regulation — risk technologists, capital reporting engineers, model implementation teams, regulators, audit teams — the regulatory posts (3, 5, 6) and the testing post (7) are the most directly useful. If you are building serious software with language-model agents, posts 2, 4, and 7 are the ones that touch the engineering substance.

If you are neither, post 8 will probably still be readable. The mistakes generalise.

## What is open

The repository is at [github.com/OpenAfterHours/rwa_calculator](https://github.com/OpenAfterHours/rwa_calculator). The code is open-source. The rest of this docs site covers the calculator's [architecture](../architecture/index.md), [specifications](../specifications/index.md), and a [CRR-vs-Basel-3.1 comparison](../framework-comparison/index.md) in more depth than any of these posts will.

This is a reference implementation — useful for understanding how the rules behave, not a regulated production system. The gap between the two matters; I will come back to it in post 8.

---

**Read next:** *The Pipeline: Why Regulation Forced an Immutable Design* (in progress).

**Further reading:**

- [PRA PS1/26 — Implementation of the Basel 3.1 final rules](https://www.bankofengland.co.uk/prudential-regulation/publication/2026/january/implementation-of-the-basel-3-1-final-rules-policy-statement)
- [BCBS CRE standards (consolidated framework)](https://www.bis.org/basel_framework/standard/CRE.htm)
- [CRR (EU 575/2013, as onshored)](https://www.legislation.gov.uk/eur/2013/575/contents)
