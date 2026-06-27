# Blog

Notes on the experience of building this UK Credit Risk RWA Calculator — the regulation, the engineering, and what it has been like driving the work largely through a swarm of Claude Code agents.

The blog began as a planned series of eight posts. Each post stands alone, but the arc alternates between regulatory depth (CRR vs Basel 3.1, the output floor, CRM edge cases) and engineering depth (the immutable pipeline, the agent workflow, the test strategy). The first eight posts — "season one" — ran from late April to mid-June 2026 and closed with a retrospective. The project kept growing, so the series did too: a second run, over the rest of June, picks up the subsystems that did not exist when season one was written — counterparty credit risk, the rulebook-as-data migration, and the web application.

Posts land roughly weekly.

## Season two

The project outgrew its original eight-post plan. These posts carry the story forward to the parts of the calculator built after season one.

- **2026-06-27 — [The Swarm, Six Weeks On: Reviewer-Gated Worktree Batches](2026-06-27-the-swarm-six-weeks-on.md)**
  A follow-up to *Building With an Agent Swarm*. How `/next-items` grew from four parallel waves and one gate into an event-driven supervisor: a reviewer agent gating every wave, one git worktree per item, background dispatch, on-disk batch state that survives compactions, and squash-merge-before-gate.

- **2026-06-25 — [From Workbench to Web App: Reconciliation and the RWA Driver Chain](2026-06-25-from-workbench-to-web-app.md)**
  The web application the first eight posts never mentioned. Retiring the Marimo workbench for a server-rendered FastAPI app, live stage-by-stage progress tapped from existing telemetry with no engine change, a reconciliation explorer that scales to millions of keys, and the single-loan forensic driver chain that makes a discrepancy explainable step by step.

- **2026-06-23 — [Making Regulation Data, Not Code: The Rulebook Migration](2026-06-23-making-regulation-data-not-code.md)**
  The deepest architecture change since the pipeline post. Moving every regulatory value out of code into cited, content-hashed rulebook packs resolved per `(regime, date)`, and replacing `is_crr` branches with cited feature flags — so every number an auditor cares about carries a citation and a hash.

- **2026-06-20 — [Counterparty Credit Risk: Teaching the Engine SA-CCR](2026-06-20-counterparty-credit-risk-sa-ccr.md)**
  The single biggest subsystem added after season one. A regulatory and engineering deep-dive on SA-CCR — `EAD = α·(RC + PFE)`, the five hedging-set asset classes, the maturity-factor and MPOR cascade, wrong-way risk and default-fund contributions, and why counterparty rows have to route into both the SA and the IRB engines.

## Season one

The original eight-post arc: why the calculator exists, how it is shaped, how the regulation actually behaves, and how it gets built.

- **2026-06-16 — [What I Got Wrong, What's Next](2026-06-16-what-i-got-wrong-whats-next.md)**
  Season-one finale. The honest ledger: things that took longer than I planned, things the agent swarm got wrong, what is still open, and the gap between a reference implementation and a regulated production system.

- **2026-06-09 — [Testing a Regulatory Engine](2026-06-09-testing-a-regulatory-engine.md)**
  Five layers in the test pyramid, each catching a different failure mode. The headline is not the test count — it is the small hash-locked oracle suite that prevents the goldens from becoming a mirror of the engine.

- **2026-06-02 — [CRM, MOFs, and Other Edge-Case Archaeology](2026-06-02-crm-mofs-and-other-edge-case-archaeology.md)**
  Four war stories from the changelog — Multiple Option Facilities, AIRB own-LGD anti-double-counting, the SME supporting factor's connected-client aggregation, and cross-approach CCF substitution. Each one a regulatory rule applied to the wrong unit until a careful reading caught it.

- **2026-05-26 — [The Output Floor and Why Basel 3.1 Bites](2026-05-26-the-output-floor-and-why-basel-31-bites.md)**
  Regulatory deep-dive on the 72.5% output floor. Why it exists, how the `TREA = max{U-TREA; x × S-TREA + OF-ADJ}` formula works, what the Art. 122(8) election does, and why "the floor binds" is the start of the analysis rather than the end.

- **2026-05-19 — [Building With an Agent Swarm](2026-05-19-building-with-an-agent-swarm.md)**
  How a bash loop, role-bounded Claude Code agents, and a pre-commit hook produce regulatory-grade code. Walks one closed plan item end-to-end and is honest about the failure modes. (See the season-two follow-up for how the orchestration matured.)

- **2026-05-12 — [Risk Weights Are Not a Lookup Table](2026-05-12-risk-weights-are-not-a-lookup-table.md)**
  Standardised Approach deep-dive. Why the £1m loan secured by a residential property has at least six right answers, and why "look up the country, get the risk weight" misreads what SA actually does.

- **2026-05-05 — [The Pipeline: Why Regulation Forced an Immutable Design](2026-05-05-the-pipeline.md)**
  Architecture deep-dive. Frozen bundles, structural protocols, lazy graphs, accumulated errors, and a data/engine split — each one falling out of a real regulatory demand rather than aesthetic preference.

- **2026-04-28 — [Building a UK Basel 3.1 RWA Calculator in Public](2026-04-28-building-a-uk-basel-31-rwa-calculator-in-public.md)**
  Series kickoff. Why an open-source reference implementation of UK Basel 3.1 / PS1/26 credit risk RWA, what the calculator does, and what is in the rest of the series.

## The series

Season one ran for eight posts, alternating between regulatory substance (CRR vs Basel 3.1, the output floor, CRM edge cases) and engineering substance (architecture, the agent workflow, testing strategy). The first post set the scene; the eighth was the honest retrospective. Season two continues the same alternation on the subsystems built since — counterparty credit risk, the regulatory-data migration, and the web application. The repository is at [github.com/OpenAfterHours/rwa_calculator](https://github.com/OpenAfterHours/rwa_calculator).

A note on dates and accuracy: published posts are dated snapshots. Code references in each post are pinned to the commit it was written against, and where a later change has overtaken a published post, a dated *Update* note records what moved rather than rewriting the original. The live project counts a post cites (tests, files, stages) can be regenerated at any time with `uv run python scripts/blog_counts.py`.

## Who it is for

The series is written for two audiences and tries to land with both:

- Engineers who care about how AI-assisted development works at non-trivial scale, where correctness matters and the rule book is unforgiving.
- Risk and regulatory practitioners who want concrete, worked treatment of the parts of CRR and Basel 3.1 where the rules behave in ways the executive summaries do not capture.

## How to read it alongside the docs

The rest of this site is reference material — specifications, architecture, API. The blog is narrative: why the calculator is shaped the way it is, what was hard, and what the regulation actually does once you implement it carefully. Posts link back into the relevant spec and architecture pages where the details live.
