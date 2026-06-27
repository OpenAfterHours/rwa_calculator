# What I Got Wrong, What's Next

*The season-one finale. The honest ledger: things that took longer than planned, things the agent swarm got wrong, what is still open, and the gap between a reference implementation and a regulated production system. Season two follows — on CCR, the rulebook-as-data migration, the web app, and how the swarm matured.*

Published 2026-08-04. Code references are pinned to commit [`7e7ed7ec`](https://github.com/OpenAfterHours/rwa_calculator/tree/7e7ed7ec). The counts in this post were taken with [`scripts/blog_counts.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/7e7ed7ec/scripts/blog_counts.py) at that commit; run it for live figures.

---

This is the eighth post — the season-one finale — in the series on building this UK Basel 3.1 RWA calculator. Posts 1–7 made the case for what the calculator does and how it works. This post is the ledger: what got built, what didn't, what nearly didn't, and what to expect of a reference implementation versus a regulated production system. It closes the first arc, not the project; season two picks up the threads this post has to leave hanging.

The series began with this claim: *"This is a reference implementation — useful for understanding how the rules behave, not a regulated production system. The gap between the two matters; I'll come back to it in post 8."* This is post 8. The gap is the substance of half this post.

A note before the ledger: a lot has shipped since the first seven posts were drafted that those posts treat as future work or out of scope. The SA-CCR counterparty-credit-risk epic, SFT/FCCM collateral, BA-CVA, securitisation allocation, the rulebook-as-data migration (regulatory values moved out of the engine into cited `rulebook/packs/` entries), and the web UI with its reconciliation view all landed across the 0.2.x–0.3.x line. Each earns its own season-two post; the ledger below is the state of the *first* arc at the season-one boundary.

## Things that took longer than I planned

Four areas where the published changelog under-counts the effort that landed.

**The CRM allocator.** The credit risk mitigation processor went through three rewrites. The first version was a single-allocation pass: each piece of collateral is assigned to one exposure, full stop. That ignored counterparty-level pools (a parent guarantee covering many drawdowns) and facility-level pledges (a master collateral basket). The second version was multi-level: direct → facility-level pro-rata → counterparty-level pro-rata, with overcollateralisation thresholds (1.4x for non-financial RE/other, 1.25x for receivables, 1.0x for financial). The third version, [shipped in 0.2.1](../appendix/changelog.md), added pool-awareness for AIRB own-LGD anti-double-counting — the war story from [post 6](2026-07-07-crm-mofs-and-other-edge-case-archaeology.md). Each rewrite was three to four weeks of work and produced numbers that looked correct under the previous test set. Each successive set of acceptance scenarios revealed why the previous version was structurally insufficient.

**Rating inheritance.** Resolving "the counterparty's effective rating" turned out to be two parallel resolutions, not one. Internal ratings (which carry a PD) and external ratings (which carry a CQS) inherit from different parent chains under different rules, with [Art. 138 multi-rating selection](../appendix/changelog.md) layered on top of the external chain. The classifier gates IRB on `internal_pd is not null`, not on rating presence. Sovereigns with external CQS but no internal PD always land on SA even when F-IRB is permitted. The whole story took six weeks across `engine/hierarchy.py`, the classifier, and the cross-approach guarantor routing — most of which I underestimated as "should be a couple of joins."

**The output floor's OF-ADJ.** The headline `max(U-TREA, x × S-TREA)` formula from [post 5](2026-06-23-the-output-floor-and-why-basel-31-bites.md) is straightforward. The OF-ADJ reconciliation between IRB provision treatment (EL shortfall to CET1, excess to T2 capped at 0.6% of IRB RWA) and SA provision treatment (general credit risk adjustments to T2 directly) was not. The first cut conflated GCRA and SCRA, which produced floor numbers that were quietly wrong on any portfolio with non-zero general provisions. Sorting out the GCRA / SCRA boundary against Reg (EU) 183/2014, the 1.25% S-TREA cap on GCRA, and the 12.5x own-funds-to-RWA conversion took longer than the rest of the floor implementation combined.

**RGLA / PSE classification routing.** Regional governments and public sector entities can be treated as sovereign-derived or institution-treated; the same counterparty therefore has two possible exposure classes. I knew about this in principle. I learned the consequences from a [version 0.1.63](../appendix/changelog.md) bug where `rgla_institution` and `pse_institution` counterparties carrying internal ratings were silently routed to SA regardless of IRB permissions, because the permission expressions were keyed on the SA exposure class while the IRB permission table only listed CGCB and INSTITUTION. The fix touched the classifier, the model-permissions resolver, the entity-type maps, and a substantial set of regression tests. The lesson — that "what class is this exposure?" is genuinely a two-answer question — would have been much cheaper to learn from the rule book than from the bug.

## Things the agent swarm got wrong

The pre-commit gate from [post 4](2026-06-09-building-with-an-agent-swarm.md) catches architectural drift. It does not catch regulatory misreading. Three categories where the gates passed, the test went green, and the result was wrong on a careful read of the regulation.

**Reasonable-looking arithmetic on the wrong unit.** The SME supporting factor evaluating per-counterparty instead of group-of-connected-clients (covered in [post 6](2026-07-07-crm-mofs-and-other-edge-case-archaeology.md)) is the cleanest example. The agent's hand-derivation showed the EUR 1.5m threshold being checked against the loan's EAD, the test asserted the resulting RWA, the implementation made the test pass, the gate ran clean. Nothing about that loop ever consulted Art. 4(1)(39) on connected clients. The bug was caught only when a later acceptance scenario combined a small loan with a large parent group and produced a number that disagreed with the spec doc the architect agent had cited.

**Multi-rating "most recent wins."** The hierarchy resolver's external rating logic for Art. 138 originally collapsed multiple ratings to "the most recent assessment" — a defensible default if you have not read Art. 138 carefully. The actual rule is per-agency dedup (most recent per ECAI), then 1-rating / 2-rating-higher-RW / ≥3-rating-second-best selection. The first implementation passed every acceptance scenario where each counterparty had ratings from at most one agency, which was every scenario at the time the implementation landed. The bug was caught when the next batch of scenarios introduced multi-agency ratings — and the agents that wrote those scenarios did not notice that the hand-derivation should have followed Art. 138 because the rule had not been salient on previous iterations.

**Defaulted retail with non-financial collateral.** The defaulted SA treatment was originally blending the base class RW with the provision-coverage RW pro-rata by the secured/unsecured split. For defaulted retail with RE collateral, this produced 75% (the base retail RW) instead of the Art. 127(1) 100%/150%. The agent that built the original implementation followed the structure of the non-defaulted SA path (which does blend collateral) and assumed defaulted should look the same. The reading of Art. 127(2) — that the unsecured portion is what the CRM method produces, and no secondary split inside the defaulted override is needed — required someone to notice that the assumed parallelism between defaulted and non-defaulted didn't survive contact with the specific text.

The pattern across all three: agents are good at applying regulatory text once the right text is identified, mediocre at deciding which text is the right one when two articles overlap or when a default assumption is unstated. The validation gate enforces grammatical regularity (no `print()`, no inline scalars, frozen bundles); it does not enforce regulatory adequacy. That part stayed with me. It was not displaceable.

## What is still open

`IMPLEMENTATION_PLAN.md` lists roughly 21 open P1 items (calculation correctness) at the time of writing — the bulk of them in a Tier 9 conformance-audit batch (P1.198–P1.213) awaiting promotion into Tier 1. A representative sample of the open ones, by P-code:

- **P1.199** — CIU / fund-unit collateral mis-buckets to `other_physical` (a flat 40% haircut) instead of the Art. 224(5) look-through volatility adjustment; eligible fund units never reach a financial-collateral treatment. Effort: L.
- **P1.205 / P1.206 / P1.207** — the equity PD/LGD floors and the speculative flag. P1.205: the CRR Art. 165(1) 0.09% equity PD floors are defined but unreachable — no input column selects the long-term-relationship / regular-cashflow sub-types, so they floor at 0.40% / 1.25% instead. P1.206: the Art. 165(2) 65% diversified-PE LGD keys on the type-string only, ignoring the `is_diversified_portfolio` flag the IRB-Simple branch honours. P1.207: the B31 `is_speculative` flag short-circuits to 400%, bypassing the unlisted-AND-business-under-5-years higher-risk test (Art. 133(4)). Effort: S–M.
- **P1.208 / P1.210 / P1.212** — the SA provision GCRA-versus-SCRA boundary again, the same distinction that bit the output floor (above) showing up in three more places. P1.208: the SA exposure-value deduction sums *all* provision rows, so general CRA wrongly reduce SA exposure value (Art. 111(1) is SCRA-only). P1.210: the Art. 159(3) defaulted IRB pool wrongly includes GCRA because `provision_type` is never split upstream. P1.212: the GCRA cap base uses floor-eligible S-TREA instead of the full standardised TREA (Art. 92(3A)). Effort: S–M.
- **P1.213** — the SA-CCR option supervisory delta uses the original tenor for the Black-Scholes `T` instead of remaining time-to-expiry from `reporting_date`, overstating delta, the PFE add-on, and EAD on any seasoned option. Effort: S.

Add to that the structural items I am most aware of:

- **The oracle suite has 3 of an audit-recommended ~50 exposures** — the load-bearing claim of [post 7](2026-07-21-testing-a-regulatory-engine.md). Closing the gap is a several-week roadmap item, not a quick patch.
- **Stress testing** has scenario coverage but the surrounding workbook integration is partial.
- **COREP and Pillar 3 templates** are now broad — the CCR templates (C 34.xx) and the Pillar III CCR1–CCR8 tables shipped across the 0.3.x line, so CCR is no longer out of scope. The remaining placeholders are narrow: the C 08.01 row 0160 "alternative treatment for real estate" returns null pending an RE alt-treatment pipeline flag, and the SFT EAD path implements only FCCM (Art. 220–223) — the reserved `"var"` (Art. 221) and `"imm"` (Art. 283) methods fail loud rather than guess.
- **Performance** has been benchmarked up to ~1M counterparties (the opt-in `scale_1m` suite; the older 10M-row benchmarks were removed as un-runnable on commodity CI) but not optimised end-to-end.
- **`DOCS_IMPLEMENTATION_PLAN.md`** still has open items, mostly small documentation gaps the doc agent has not gotten to yet.

This is not a small backlog. It is also not a hopeless one. The agent workflow throughput on `/next-items 3` runs is roughly three closed Tier 1 items per build iteration when items are non-conflicting, which means the open backlog is closeable in a few months of consistent effort. Whether it gets closed before PS1/26 goes live on 1 January 2027 is a question of priority, not feasibility.

## The gap between reference and regulated

The series-opening claim was that this is *a reference implementation*, not a regulated production system, and that the gap matters. Here is what the gap actually contains.

The calculator is not validated against the PRA's [SS1/23 Model Risk Management Principles](https://www.bankofengland.co.uk/prudential-regulation/publication/2023/may/model-risk-management-principles-for-banks-ss). It has no independent validation function, no model inventory, no governance committee, no annual revalidation cycle, no signed-off model risk policy. A firm using this calculator inside a regulated capital-reporting process would owe the PRA every one of those things, and producing them is not engineering work — it is governance work that surrounds the engineering and outweighs it on cost.

The calculator is not under firm change control. Every commit lands when it lands; there is no sign-off path, no model committee, no segregation of duties between the developer and the reviewer (because there is one of me). Under SS1/23 expectations, model changes are tracked, justified, validated, and approved by named individuals with documented authority. None of that infrastructure exists here.

The calculator is not running on production data with full data-quality assurance. The acceptance suite covers roughly 1,449 hand-derived test functions across ~182 named scenarios; real bank portfolios contain millions of exposures with combinations of attributes I have not enumerated. The test discipline gives statistical confidence about correctness on the scenarios tested, not absolute confidence on portfolios I have not seen. Real production deployment requires a parallel-run discipline against an existing system, signed-off reconciliation thresholds, and a rollback plan I have not built.

The calculator is not signed off by an external auditor. It has not been through a model validation engagement, an internal-audit review, or an independent quantitative testing effort. The hash-locked oracle suite from [post 7](2026-07-21-testing-a-regulatory-engine.md) is the closest thing it has to independent validation; it is a useful start and it is not a substitute.

What it *is* useful for: a public reference for understanding how the rules behave; a comparator engine that a firm's in-house team can run alongside their own to triangulate disagreements; an educational artefact for engineers learning the regulation; and a demonstration that PS1/26 is implementable to roughly 7,450 tests of discipline by one person directing an agent pipeline. None of that is small. It is also not the same thing as a regulated production system. A firm that adopts this in earnest owes itself everything in the four paragraphs above.

## What's next

Three things on the roadmap, before PS1/26 lands on 1 January 2027.

**Closing the Tier 1 backlog.** Roughly 21 open P1 items, the bulk of which are S-effort and addressable by the agent pipeline at current throughput. The blockers are not technical; they are the regulatory-judgement calls that gate each item — the decision of which interpretation to implement when the rule book is genuinely ambiguous. Those decisions cannot be delegated to the agents.

**Expanding the oracle suite.** Three exposures today, ten on the prioritised roadmap, ~50 on the audit's recommendation. Each addition is a four-file lockstep commit (markdown, derive script, JSON, test) and takes a measured day to a measured week depending on the calculation pathway. This is not work the agents can usefully accelerate — the derivations have to be auditable by a regulatory reader, which means a human writes them.

**Documentation completeness.** The Zensical site has comprehensive coverage of the architecture and major specifications, but `DOCS_IMPLEMENTATION_PLAN.md` still names gaps the doc agent has not closed. The agent runs in `loop.sh docs_build` mode in parallel with the main build; the doc backlog will close at roughly the same rate the calculation backlog does.

The framing question is not "can the calculator be made fully correct before PS1/26" — it can, with a few months of consistent effort. The framing question is *whether the right ambition for an open-source reference implementation is full compliance or transparent partial compliance with a clear backlog and a credible path*. I am increasingly convinced the second is more useful than the first. A reference implementation that closes its backlog in public, with each closed item carrying a regulatory citation and a hand-derived test, is more credible than a closed-source production system that says "trust us." The series has been an attempt to make that argument by demonstrating it.

## Closing season one

Eight posts. About 22,000 words. One repository, one calculator, one solo developer with a Claude Code agent pipeline. The argument across the posts has been a single one in three parts:

- **Architecture is downstream of audit demands.** Frozen bundles, structural protocols, lazy graphs, error accumulators, and a strict data/engine split are not stylistic preferences. They are what regulation does to engineering when you take the regulation seriously.
- **Regulation is harder than it looks because the routing is the work.** SA appears simple because its lookup tables are short. The classification logic that decides which lookup table applies — exposure class, approach, default state, group-of-connected-clients aggregation, real-estate split, ECRA versus SCRA, defaulted-with-collateral routing — is where most of the regulatory judgement lives. SA exposes this; IRB hides it inside models. Both have it.
- **AI-assisted engineering at this scale is real, finite, and not autonomous.** The agents do the typing. The architecture, the prompts, the validation gates, and the regulatory reading are the work that makes the typing produce correct code. Those parts stayed with me through every iteration of the build, and they are the parts that did not displace.

The calculator continues. The agent loop will run again tomorrow. The PS1/26 effective date is sixteen months away. The backlog gets shorter, then it doesn't, then it does. If you are reading this from a UK firm preparing for the same deadline, I hope some of what is here is useful. If you are reading it from somewhere else entirely, I hope at least one of the eight posts taught you something about regulation, software architecture, or how AI-assisted engineering looks when the rule book is unforgiving.

The repository is at [github.com/OpenAfterHours/rwa_calculator](https://github.com/OpenAfterHours/rwa_calculator). Season one ends here; season two begins with the CCR epic.

---

**The series so far:**

1. [Building a UK Basel 3.1 RWA Calculator in Public](2026-04-28-building-a-uk-basel-31-rwa-calculator-in-public.md)
2. [The Pipeline: Why Regulation Forced an Immutable Design](2026-05-12-the-pipeline.md)
3. [Risk Weights Are Not a Lookup Table](2026-05-26-risk-weights-are-not-a-lookup-table.md)
4. [Building With an Agent Swarm](2026-06-09-building-with-an-agent-swarm.md)
5. [The Output Floor and Why Basel 3.1 Bites](2026-06-23-the-output-floor-and-why-basel-31-bites.md)
6. [CRM, MOFs, and Other Edge-Case Archaeology](2026-07-07-crm-mofs-and-other-edge-case-archaeology.md)
7. [Testing a Regulatory Engine](2026-07-21-testing-a-regulatory-engine.md)
8. *What I Got Wrong, What's Next* — the season-one finale (this post)

*Season two continues the story — posts on the SA-CCR/CCR epic, the rulebook-as-data migration, the web app, and how the agent swarm matured are in the pipeline.*
