# Blog

Notes on the experience of building this UK Credit Risk RWA Calculator — the regulation, the engineering, and what it has been like driving the work largely through a swarm of Claude Code agents.

The blog is a planned series of eight posts. Each post stands alone, but the arc as a whole alternates between regulatory depth (CRR vs Basel 3.1, the output floor, CRM edge cases) and engineering depth (the immutable pipeline, the agent workflow, the test strategy).

Posts land roughly every two to three weeks.

## Posts

- **2026-08-04 — [What I Got Wrong, What's Next](2026-08-04-what-i-got-wrong-whats-next.md)**
  Closing post. The honest ledger: things that took longer than I planned, things the agent swarm got wrong, ~35 open Tier 1 items, and the gap between a reference implementation and a regulated production system.

- **2026-07-21 — [Testing a Regulatory Engine](2026-07-21-testing-a-regulatory-engine.md)**
  Five layers in the test pyramid, each catching a different failure mode. The headline is not the 5,300-test count — it is the small hash-locked oracle suite that prevents the goldens from becoming a mirror of the engine.

- **2026-07-07 — [CRM, MOFs, and Other Edge-Case Archaeology](2026-07-07-crm-mofs-and-other-edge-case-archaeology.md)**
  Four war stories from the changelog — Multiple Option Facilities, AIRB own-LGD anti-double-counting, the SME supporting factor's connected-client aggregation, and cross-approach CCF substitution. Each one a regulatory rule applied to the wrong unit until a careful reading caught it.

- **2026-06-23 — [The Output Floor and Why Basel 3.1 Bites](2026-06-23-the-output-floor-and-why-basel-31-bites.md)**
  Regulatory deep-dive on the 72.5% output floor. Why it exists, how the `TREA = max{U-TREA; x × S-TREA + OF-ADJ}` formula works, what the Art. 122(8) election does, and why "the floor binds" is the start of the analysis rather than the end.

- **2026-06-09 — [Building With an Agent Swarm](2026-06-09-building-with-an-agent-swarm.md)**
  How a 90-line bash loop, four role-bounded Claude Code agents, and a pre-commit hook produce regulatory-grade code. Walks one closed plan item end-to-end and is honest about the failure modes.

- **2026-05-26 — [Risk Weights Are Not a Lookup Table](2026-05-26-risk-weights-are-not-a-lookup-table.md)**
  Standardised Approach deep-dive. Why the £1m loan secured by a residential property has at least six right answers, and why "look up the country, get the risk weight" misreads what SA actually does.

- **2026-05-12 — [The Pipeline: Why Regulation Forced an Immutable Design](2026-05-12-the-pipeline.md)**
  Architecture deep-dive. Frozen bundles, structural protocols, lazy graphs, accumulated errors, and a data/engine split — each one falling out of a real regulatory demand rather than aesthetic preference.

- **2026-04-28 — [Building a UK Basel 3.1 RWA Calculator in Public](2026-04-28-building-a-uk-basel-31-rwa-calculator-in-public.md)**
  Series kickoff. Why an open-source reference implementation of UK Basel 3.1 / PS1/26 credit risk RWA, what the calculator does, and what is in the rest of the series.

## The series

The series ran for eight posts, alternating between regulatory substance (CRR vs Basel 3.1, the output floor, CRM edge cases) and engineering substance (architecture, the agent workflow, testing strategy). The first post sets the scene; the closing post is the honest retrospective. The repository is at [github.com/OpenAfterHours/rwa_calculator](https://github.com/OpenAfterHours/rwa_calculator).

## Who it is for

The series is written for two audiences and tries to land with both:

- Engineers who care about how AI-assisted development works at non-trivial scale, where correctness matters and the rule book is unforgiving.
- Risk and regulatory practitioners who want concrete, worked treatment of the parts of CRR and Basel 3.1 where the rules behave in ways the executive summaries do not capture.

## How to read it alongside the docs

The rest of this site is reference material — specifications, architecture, API. The blog is narrative: why the calculator is shaped the way it is, what was hard, and what the regulation actually does once you implement it carefully. Posts link back into the relevant spec and architecture pages where the details live.
