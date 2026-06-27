# The Output Floor and Why Basel 3.1 Bites

*The 72.5% output floor is the headline change in Basel 3.1 for IRB banks. It is also one of four drivers, and the relationship between them is more interesting than any single number.*

Published 2026-06-23. Code references are pinned to commit [`cceaee4`](https://github.com/OpenAfterHours/rwa_calculator/tree/cceaee4).

---

This is post 5 in the series on building this UK Basel 3.1 RWA calculator. Posts 1–4 covered why the calculator exists, how its pipeline is shaped, what the Standardised Approach actually does, and how the codebase gets written. This post is back to regulation: specifically, the part of Basel 3.1 that costs UK IRB banks the most capital, and why "the floor binds" turns out to be the start of the analysis rather than the end of it.

## A £100m IG corporate book

Consider a UK bank with a £100m portfolio of investment-grade corporate loans, all using the Foundation IRB approach. Average PD 0.10%, supervisory LGD 45%, effective maturity 2.5 years. Run the IRB formula and the average risk weight comes out around 25% — call it £25m of IRB RWA on the £100m portfolio. The bank's senior unsecured cost of capital, its return-on-RWA targets, its loan-pricing spreadsheets, all assume that £25m number.

Now run the same portfolio through the Standardised Approach. Under PS1/26, an investment-grade corporate gets a 65% risk weight (Art. 122(6)(a)). On £100m of EAD that is £65m of SA-equivalent RWA. Multiply by 72.5% and you get £47.125m. That is the floor.

Under Basel 3.1, the bank's regulatory RWA on this portfolio is `max(£25m, £47.125m) = £47.125m`. Capital required against the same £100m of loans, using the same internal model that produced the same £25m of IRB RWA, is now 89% higher than it was under CRR. The bank did not change. The borrowers did not change. The framework changed.

That £22m delta is the bite. The rest of this post is about where it comes from, why it is there, and why simply observing that "the floor binds" is not yet a useful answer to the question of what to do about it.

## Why the floor exists at all

The output floor is the BCBS's answer to a problem that emerged from the post-2008 review of Basel II's IRB approach. Studies of bank-supplied IRB outputs — most notably the [BCBS 2013 Regulatory Consistency Assessment Programme](https://www.bis.org/bcbs/publ/d240.pdf) and subsequent benchmark portfolio exercises — found risk-weight dispersion across banks that could not be explained by portfolio composition alone. Two banks holding economically identical low-default corporate exposures could produce IRB risk weights differing by a factor of two or more, depending on internal modelling choices. Some of this was statistically defensible. Some of it, particularly at the low-default end of the rating curve, was not.

The output floor is a portfolio-level fail-safe. It does not police any individual model. It says, in effect: regardless of what your IRB models produce, your aggregate IRB RWA cannot fall below 72.5% of what the Standardised Approach would have produced for the same portfolio. The number 72.5% is not principled — it is the calibration point the BCBS settled on after consultation, calibrated to leave most well-modelled IRB books substantially below the floor while pulling outliers up. The floor is meant to bind for some firms on some portfolios. It is not meant to bind universally.

The PRA's implementation in PS1/26 is materially the same as the BCBS standard with one important UK difference: the transitional phase-in. The BCBS gives six years (2023–2028, since deferred). The PRA gives four (2027–2030). Article 92(5) sets out three transitional steps — 60% in 2027, 65% in 2028, 70% in 2029 — after which the steady-state 72.5% under Article 92(2A) applies directly from 2030 onwards. There is no Art. 92(5)(d). The transitional is also *permissive* under PS1/26: a firm may elect to apply the full 72.5% from day one if it prefers. Most will not.

## How the floor works mechanically

The full formula from PS1/26 Art. 92(2A) is:

```
TREA = max{U-TREA; x × S-TREA + OF-ADJ}
```

Where:

- **U-TREA** is the "un-floored" total risk exposure amount — the calculator's headline IRB number for the floor-eligible portfolio, computed using the firm's actual model permissions.
- **S-TREA** is the standardised total risk exposure amount — the same portfolio re-run under the Standardised Approach, with no IRB, no SFT VaR, no SEC-IRBA, no IAA, no IMM, and no IMA.
- **x** is the floor percentage — 72.5% fully phased, or the transitional 60% / 65% / 70% during the phase-in.
- **OF-ADJ** is the own-funds adjustment that reconciles IRB and SA provision treatments so the comparison is on a like-for-like capital basis.

Three things are non-obvious about this.

**First, S-TREA is not the SA RWA of the SA portfolio.** It is an SA-equivalent RWA computed across the *entire IRB portfolio*, in addition to whatever SA exposures the firm holds. Every IRB exposure has to be dragged back through the SA classifier with the same EAD, the same counterparty, the same collateral, but treated *as if IRB had never been permitted*. The calculator's split-once-and-materialise architecture from [post 2](2026-05-12-the-pipeline.md) is what makes this cheap: the upstream stages (loader, hierarchy, classifier, CRM) run once and produce a frame that the SA calculator and the IRB calculator both consume. The cost of computing S-TREA is roughly the cost of one extra calculator pass over the IRB rows, not a second full pipeline.

**Second, the floor applies portfolio-wide, not per-exposure.** The aggregator emits a per-exposure `floor_rwa` column allocated pro-rata to IRB exposures by their share of S-TREA, but that column is a reporting convenience — the regulatory floor is `max(U-TREA, x × S-TREA + OF-ADJ)` at the portfolio level. The shortfall, when it exists, is the amount that the floored TREA exceeds the un-floored TREA. The calculator surfaces both the per-exposure allocation and the portfolio-level summary; consumers that need to feed COREP C 02.00 must read the portfolio-level fields, because OF-ADJ is an own-funds reconciliation defined at the entity level and has no meaningful per-exposure decomposition.

**Third, not every entity is in scope.** Under Art. 92(2A)(a), the floor applies to standalone UK institutions on individual basis, ring-fenced bodies on sub-consolidation basis, and CRR consolidation entities on consolidated basis. Under Art. 92(2A)(b)–(d), it does *not* apply to non-RFB institutions on sub-consolidated basis, ring-fenced bodies in sub-consolidation groups on individual basis, or international subsidiaries on consolidated basis. The carve-outs matter — a firm that is on the wrong side of the entity-type / reporting-basis combination will calculate U-TREA but never compare it to the floor.

## OF-ADJ: the reconciliation no one likes explaining

The OF-ADJ term is the part of the formula that gets hand-waved in most public material. It exists because IRB and SA treat provisions differently, and a naive `max(U-TREA, x × S-TREA)` comparison would conflate the framework difference with the floor.

The full definition from PS1/26 Art. 92(2A):

```
OF-ADJ = 12.5 × (IRB_T2 - IRB_CET1 - GCRA + SA_T2)
```

The 12.5 multiplier converts own-funds amounts to risk-weighted equivalents (the inverse of the 8% minimum capital ratio). The four components are:

- **IRB_T2** — the IRB excess-provisions T2 credit per Art. 62(d), capped at 0.6% of IRB credit-risk RWA. This is the regulatory benefit a firm gets when its IRB provisions exceed expected loss.
- **IRB_CET1** — the IRB EL shortfall CET1 deduction per Art. 36(1)(d), plus any supervisory deductions under Art. 40. The cost when EL exceeds provisions.
- **GCRA** — general credit risk adjustments included in T2, gross of tax effects, capped at 1.25% of S-TREA. (This is *separate* from SA_T2 because the GCRA treatment in OF-ADJ uses a gross figure capped at the S-TREA threshold, while SA_T2 is the post-Art. 62(c) SA-side T2 credit.)
- **SA_T2** — the SA general credit risk adjustments recognised as T2 capital under Art. 62(c).

Why all this: under IRB, EL shortfalls deduct from CET1 and excess provisions add to T2 (Art. 159 pools). Under SA, general credit risk adjustments add to T2 directly. If you compute U-TREA under IRB rules and then compute `x × S-TREA` under SA rules and take the max, you have implicitly switched the firm's own-funds composition between the two limbs. OF-ADJ is the bridge that keeps the comparison consistent.

The General Credit Risk Adjustment / Specific Credit Risk Adjustment distinction is itself non-trivial — Reg (EU) 183/2014 (the onshored RTS) defines GCRA as portfolio-level, non-allocated, non-defaulted-portfolio loss allowances, while SCRAs are allocated to specific exposures. IFRS 9 staging does not map mechanically: Stage 1 is almost always GCRA, Stage 3 is almost always SCRA, and Stage 2 is the genuinely ambiguous bucket. Whether a Stage 2 allowance is GCRA or SCRA depends on whether it was produced by a collective lifetime-ECL model or by individual obligor review. The calculator does not derive this from IFRS 9 balances — the firm supplies the GCRA-qualifying amount and the SA-side T2 credit through `OutputFloorConfig` fields, both of which must reconcile to the same Reg (EU) 183/2014 classification.

## The Art. 122(8) election

There is a subtle lever that determines whether the floor binds for some IRB books. It applies only inside the S-TREA calculation, and only to unrated non-SME corporate exposures.

Article 122(8) gives IRB firms two branches for treating these exposures *for the purposes of S-TREA*:

- **Branch (a)** — flat 100% risk weight on every unrated non-SME corporate. No PRA permission needed. No notification.
- **Branch (b)** — Art. 122(6)(a)/(b) split: 65% for exposures the firm internally assesses as investment-grade, 135% for everything else. Requires Art. 122(6) prior permission and a notification to the PRA on adoption *and* on cessation.

Art. 122(11) SME corporates retain the 85% weight under both branches; the election only governs the unrated non-SME population.

Why this matters for floor-binding firms: branch (a) fixes every unrated non-SME corporate at 100% in S-TREA, which is conservative for an IG-heavy book. Branch (b) lets the firm recognise its internal IG assessment in S-TREA — typically reducing floor impact materially — at the cost of the 135% penalty on any obligor assessed as non-IG. A firm that expects the floor to bind should compare a portfolio-weighted 100% against `w_IG × 65% + w_nonIG × 135%` before electing. For a 70/30 IG/non-IG book the branch-(b) weighted average is 86%, comfortably below the branch-(a) 100%. For a 50/50 book it is exactly 100%, breakeven. For a 30/70 book it is 114%, worse than branch (a).

The election is portfolio-wide *within* the output-floor corporate population — a firm with Art. 122(6) permission cannot cherry-pick branch (a) for non-IG obligors while using branch (b) for IG ones. And because the notification is symmetric on adoption and cessation, switching back and forth across reporting periods costs the firm a record-keeping obligation it may not want.

The calculator does not surface a dedicated S-TREA-only switch. The S-TREA pass inherits the firm's regular Art. 122(5)/(6) branch choice — firms that already apply the IG/non-IG split for their SA exposures automatically get branch (b) in S-TREA; firms on Art. 122(5) flat 100% get branch (a). The Art. 122(8) drafting does technically permit a firm to elect branch (b) only for S-TREA while retaining flat 100% for its regular SA portfolio, but this would require two pipeline runs combined externally and has not been a request from any user yet.

## The PRA transitional schedule

The four-year UK phase-in:

| Year | Floor percentage | Rule reference |
|------|------------------|----------------|
| 2027 | 60% | Art. 92(5)(a) |
| 2028 | 65% | Art. 92(5)(b) |
| 2029 | 70% | Art. 92(5)(c) |
| 2030+ | 72.5% | Art. 92(2A) (steady-state) |

A common confusion: there is no Art. 92(5)(d). The 2030+ row is the steady-state Art. 92(2A) formula taking over once the transitional opt-in expires, not a fourth transitional step. From 1 January 2030 onwards the firm cannot elect a reduced floor — it gets the fully phased 72.5% directly.

The schedule is *permissive*. A firm may apply 72.5% from day one if it wishes; the calculator's `OutputFloorConfig.skip_transitional` flag bypasses the Art. 92(5) election and forces steady-state. Most firms will use the transitional. A few — typically those with very low exposure to floor binding, or with capital headroom — may prefer the certainty of one constant number across the four-year window.

The £100m IG corporate portfolio from the lead, run through the calculator's `TransitionalScheduleBundle` for each year of the phase-in, produces a tidy escalation: at 60% the floor threshold is £39m; at 65% it is £42.25m; at 70% it is £45.5m; at 72.5% it is £47.125m. The IRB number stays at £25m throughout. Each year's 5-percentage-point increment costs £3.25m of additional regulatory RWA on this single £100m book.

## What shows up in real portfolios

The calculator's `CapitalImpactAnalyzer` decomposes the CRR-to-Basel-3.1 RWA delta into four drivers using a sequential waterfall:

1. **Scaling factor removal** (negative, IRB only). CRR multiplies IRB capital by 1.06 under Art. 92(2)(b); Basel 3.1 removes this. For a £25m IRB book, this is a -£1.4m effect — pure relief.
2. **Supporting factor removal** (positive, SA and IRB). CRR applies the SME supporting factor (0.7619 below the threshold, 0.85 above) and the infrastructure supporting factor (0.75) as RWA discounts under Art. 501. Basel 3.1 removes them. The effect is positive — removing the discount increases RWA — and the magnitude depends entirely on how SME-heavy the book is.
3. **Methodology and parameter changes** (varies, all). The residual after the other three drivers — PD/LGD floor changes, SA risk-weight table revisions, F-IRB supervisory LGD changes (0.45 CRR → 0.40 Basel 3.1 for senior non-financial corporate; financial-sector entities retain 45%), correlation formula updates, the Art. 124F/H real-estate splitter from [post 3](2026-05-26-risk-weights-are-not-a-lookup-table.md), every other rule difference. Can be sizeable in either direction.
4. **Output floor impact** (positive, IRB only). The amount the floor adds when it binds. Zero when it doesn't.

The four drivers are additive and they sum exactly to the per-exposure delta; the methodology driver is computed as the residual to enforce this. The point of the decomposition is that "IRB capital went up under Basel 3.1" is not a single phenomenon. For the £100m IG corporate book in the lead — assuming no SME supporting factor applied under CRR and no methodology change of note — the breakdown is roughly: -£1.4m scaling factor, +£0m supporting factor, +£0m methodology, +£23.5m output floor. The floor is essentially the entire story.

For a different portfolio — say, an SME-heavy IRB book with £100m EAD across borrowers below the SME supporting-factor threshold, modelled at PD 1.5% and LGD 45% — the picture inverts. IRB RW is closer to 75%, IRB RWA around £75m. SA-equivalent RW is around 85% (B3.1 SME corporate), S-TREA around £85m, floor threshold £61.6m. The floor does not bind. But the supporting factor was reducing CRR IRB RWA by 23.81% (from 1.0 to 0.7619); removing it adds about £18m. Scaling factor removal recovers £4.5m. Methodology changes might add or subtract a few million more. Net: the SME book gets *more* expensive under Basel 3.1, but the driver is the supporting factor, not the floor.

This matters for capital planning. A firm reading "Basel 3.1 capital impact" as a single number is making a category error. The drivers behave differently across portfolios, regulatory cycles, and supervisory elections. The floor is the headline because it produces the largest single delta on the books that the public cares about (large IG corporate lenders), but the methodology and supporting-factor drivers move the most capital across the UK system in aggregate.

## The shape of the bite

The mental model "Basel 3.1 makes IRB worse and SA the same" is wrong in both directions. SA changed materially under Basel 3.1 — the real-estate splitter, the ECRA/SCRA distinction, the corporate sub-categories, the currency-mismatch multiplier, the due-diligence obligation. The floor matters for IRB firms because the IRB framework that Basel 3.1 is comparing them against — `x × S-TREA + OF-ADJ` — is computed under the *new* SA, not the old one. A firm that wants to anticipate the floor's bite has to anticipate two changes simultaneously: what its IRB book looks like under tightened parameter floors, and what the same exposures look like under PS1/26 SA. The dual-framework runner from [post 2](2026-05-12-the-pipeline.md) is what makes that comparison tractable in code; the regulatory thinking is what makes it meaningful.

There is also a structural point about who the floor was designed for. Most well-run UK IRB books, on most portfolios, will not be floor-binding even in steady state. The floor is calibrated to bite on low-default, high-quality exposures where IRB models can produce risk weights that are statistically defensible but, in the BCBS's judgement, too dispersed across the population of internal models to be relied upon. IG corporate lending, prime mortgages, and senior bank exposures are where the floor shows up. Sub-investment-grade corporate, retail SME, defaulted exposures — the IRB number tends to be higher than 72.5% of S-TREA on these, and the floor is irrelevant.

The floor binds where the model thinks the borrower is safe. That is the regulatory point. It is not a punishment for using IRB; it is a cap on how much benefit modelling sophistication is permitted to extract from low-default-end exposures where the data does not support the model's confidence. Whether you agree with the calibration is a separate argument; whether the architecture is targeting the right regime is not really in dispute.

Post 6 in the series goes back to engineering: a tour of the regulatory edge cases in the calculator that took disproportionate effort — multiple-option facilities, AIRB own-LGD anti-double-counting, the real-estate splitter's collision with IRB correlation, supporting-factor connected-client aggregation. The bits where the implementation looks small from the outside and is several hundred lines of careful classifier and CRM logic underneath.

---

**Read next:** *CRM, MOFs, and Other Edge-Case Archaeology* (in progress).

**Further reading:**

- [Specifications: Output Floor (Basel 3.1)](../specifications/basel31/output-floor.md) — the full Art. 92(2A)–(5) implementation, including OF-ADJ components, GCRA / SCRA boundary, and the Art. 122(8) election.
- [Framework Comparison: Impact Analysis](../framework-comparison/impact-analysis.md) — the four-driver waterfall and how the calculator decomposes CRR-to-Basel-3.1 deltas.
- [BCBS d424 — Basel III: Finalising post-crisis reforms (2017)](https://www.bis.org/bcbs/publ/d424.htm) — the standard the floor was set in.
- [PRA PS1/26 — Implementation of the Basel 3.1 final rules](https://www.bankofengland.co.uk/prudential-regulation/publication/2026/january/implementation-of-the-basel-3-1-final-rules-policy-statement) — the UK adoption.
