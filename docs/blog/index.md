# Blog

Notes on the experience of building this UK Credit Risk RWA Calculator — the regulation, the engineering, and what it has been like driving the work largely through a swarm of Claude Code agents.

The blog is a planned series of eight posts. Each post stands alone, but the arc as a whole alternates between regulatory depth (CRR vs Basel 3.1, the output floor, CRM edge cases) and engineering depth (the immutable pipeline, the agent workflow, the test strategy).

Posts land roughly every two to three weeks.

## Posts

- **2026-05-12 — [The Pipeline: Why Regulation Forced an Immutable Design](2026-05-12-the-pipeline.md)**
  Architecture deep-dive. Frozen bundles, structural protocols, lazy graphs, accumulated errors, and a data/engine split — each one falling out of a real regulatory demand rather than aesthetic preference.

- **2026-04-28 — [Building a UK Basel 3.1 RWA Calculator in Public](2026-04-28-building-a-uk-basel-31-rwa-calculator-in-public.md)**
  Series kickoff. Why an open-source reference implementation of UK Basel 3.1 / PS1/26 credit risk RWA, what the calculator does, and what is in the rest of the series.

## What is coming

The remaining posts in the planned arc, with rough working titles:

| # | Title | Audience lean |
|---|---|---|
| 3 | Risk Weights Are Not a Lookup Table: SA & Exposure Classification | Regulatory |
| 4 | Building With an Agent Swarm: How `loop.sh` Writes This Codebase | Engineers |
| 5 | The Output Floor and Why Basel 3.1 Bites | Regulatory |
| 6 | CRM, MOFs, and Other Edge-Case Archaeology | Both |
| 7 | Testing a Regulatory Engine: 5,300 Tests, Hand-Derived Goldens | Engineers |
| 8 | What I Got Wrong, What's Next | Both |

## Who it is for

The series is written for two audiences and tries to land with both:

- Engineers who care about how AI-assisted development works at non-trivial scale, where correctness matters and the rule book is unforgiving.
- Risk and regulatory practitioners who want concrete, worked treatment of the parts of CRR and Basel 3.1 where the rules behave in ways the executive summaries do not capture.

## How to read it alongside the docs

The rest of this site is reference material — specifications, architecture, API. The blog is narrative: why the calculator is shaped the way it is, what was hard, and what the regulation actually does once you implement it carefully. Posts link back into the relevant spec and architecture pages where the details live.
