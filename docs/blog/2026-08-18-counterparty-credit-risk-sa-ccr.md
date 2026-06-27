# Counterparty Credit Risk: Teaching the Engine SA-CCR

*SA-CCR is the single largest subsystem added to the calculator since the original series — twelve engine modules that turn a book of OTC derivatives into one exposure-at-default per netting set. This post is how the rules actually work, and how they slot into a pipeline that was built without ever knowing counterparty risk existed.*

Published 2026-08-18. Code references are pinned to commit [`7e7ed7ec`](https://github.com/OpenAfterHours/rwa_calculator/tree/7e7ed7ec).

---

This post picks the series back up after the season-one finale. The first eight posts ran from April to early August and closed with a ledger of what got built and what didn't. The single largest body of work in the whole calculator is something those posts barely touch: counterparty credit risk. It was not part of the original eight-post plan — it did not exist when the early posts were written — and it grew, across the 0.2.x and 0.3.x line, into the largest subsystem in the engine. It now spans twelve modules under [`engine/ccr/`](https://github.com/OpenAfterHours/rwa_calculator/tree/7e7ed7ec/src/rwa_calc/engine/ccr), a dedicated pipeline stage, a thirteen-page specification cluster, and its own family of COREP and Pillar 3 templates. This post is the regulatory and engineering tour of how the Standardised Approach for Counterparty Credit Risk (SA-CCR) got built and wired in.

It is worth being precise about why CCR is hard in a way that the lending book is not. A term loan has an exposure: the drawn amount. A five-year interest-rate swap with a notional of £100m has an exposure of *almost nothing today* and an unknown, market-driven amount at some point before it matures. SA-CCR is the regulatory answer to the question "what number do I put in the EAD column for a derivative?" — and the answer is a small calculation engine, not a lookup.

## EAD = α × (RC + PFE)

The whole of SA-CCR collapses, at the top, into one line. CRR Article 274(2):

```
EAD = α × (RC + PFE)
```

where α is a fixed supervisory multiplier of 1.4, RC is the **replacement cost** (what it would cost to replace the netting set if the counterparty defaulted today), and PFE is the **potential future exposure** (a supervisory estimate of how much worse that could get over the close-out period). The top-level composition lives in [`engine/ccr/sa_ccr.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/7e7ed7ec/src/rwa_calc/engine/ccr/sa_ccr.py) — `compute_ead` is, almost literally, `alpha_expr * (rc + pfe_addon)`.

The α = 1.4 is not a fudge factor a firm gets to argue about. It is the calibration the Basel Committee chose to scale a current-exposure-plus-add-on figure up to something closer to an effective-EPE-times-alpha measure from the internal model method. The calculator sources it from the rulepack — [`packs/common.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/7e7ed7ec/src/rwa_calc/rulebook/packs/common.py) carries `sa_ccr_alpha = 1.4` with citation `CRR Art. 274(2)` — rather than baking it into an engine module, exactly as [post 2](2026-05-12-the-pipeline.md) described for every other regulatory scalar.

There are two wrinkles in α worth surfacing because they are PRA-specific and easy to miss. CRR Art. 274(2) second sub-paragraph grants an **α = 1.0 carve-out** for non-financial counterparties and pension-scheme arrangements (EMIR Art. 2(9)/2(10)). And PS1/26 layers an **Art. 274(2A)–(2B) transitional add-on** on top of the Basel 3.1 adoption: for legacy CVA-exempt netting sets sitting on that α = 1.0 carve-out, a phased fraction of the difference between α = 1.4 and α = 1.0 is folded back into EAD across 2027–2029, falling to zero from 2030. The calculator implements the carve-out as a per-netting-set `alpha_applied` column (1.0 or 1.4) and the transitional as a separately-surfaced `transitional_add_on`, both in [`engine/ccr/pipeline_adapter.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/7e7ed7ec/src/rwa_calc/engine/ccr/pipeline_adapter.py). Art. 274(2B)'s leverage-ratio exclusion is moot here — this engine exposes no leverage EAD path, so there is no bifurcation to build.

## The replacement cost is the easy half

RC is the part you could compute on the back of an envelope. For an **unmargined** netting set (CRR Art. 275(1)):

```
RC = max(V_net − C_net, 0)
```

V_net is the sum of trade mark-to-market values; C_net is net collateral held. If the netting set is in the money to the bank and the counterparty defaults, the bank is out the positive value; if it is out of the money, RC floors at zero (you would not pay to replace a liability). For a **margined** netting set (Art. 275(2)) the formula adds the margining frictions:

```
RC = max(V_net − C_net, TH + MTA − NICA, 0)
```

where TH is the margin threshold, MTA the minimum transfer amount, and NICA the net independent collateral amount. The second limb captures the largest uncollateralised exposure that can build up *before* a margin call is triggered. Both forms live in [`engine/ccr/rc.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/7e7ed7ec/src/rwa_calc/engine/ccr/rc.py) as two small typed functions; the pipeline adapter coalesces the margined form over the unmargined one to produce a single unified `rc` column feeding EAD.

## The PFE is where the regulation lives

PFE is the interesting half, and it is built bottom-up from individual trades. CRR Art. 278:

```
PFE = multiplier × AddOn(aggregate)
```

The `AddOn(aggregate)` is the supervisory potential-future-exposure estimate, summed across **five hedging-set asset classes**: interest rate, foreign exchange, credit (single-name and index), equity, and commodity. Each asset class has its own aggregation geometry — IR uses a three-bucket maturity correlation matrix, FX sums currency-pair hedging sets with no cross-set correlation, credit and equity use a systematic-plus-idiosyncratic decomposition with single-name/index correlations, commodity nets within five buckets at ρ = 0.40. All five are implemented in [`engine/ccr/pfe.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/7e7ed7ec/src/rwa_calc/engine/ccr/pfe.py), each as a private `_compute_addon_*` function dispatched off `asset_class`.

Underneath the asset-class aggregation, every trade contributes an **effective notional** `δ × d × MF`:

- **Adjusted notional `d`** (Art. 279b). For interest-rate and credit derivatives this is the trade notional scaled by a supervisory duration `SD(S, E) = (e^(−0.05·S) − e^(−0.05·E)) / 0.05`, where S is years-to-start (floored at ten business days) and E is years-to-maturity. For FX it is the larger converted leg; for equity and commodity it is `market_price × units`. See [`engine/ccr/adjusted_notional.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/7e7ed7ec/src/rwa_calc/engine/ccr/adjusted_notional.py).
- **Supervisory delta `δ`** (Art. 279a). ±1 for linear directional trades; a Black-Scholes Φ(d₁) for European options (Art. 279a(2)); a closed-form `15 / ((1 + 14A)(1 + 14D))` for CDO tranches (Art. 279a(3)). All three branches are in [`engine/ccr/supervisory_delta.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/7e7ed7ec/src/rwa_calc/engine/ccr/supervisory_delta.py).
- **Maturity factor `MF`** (Art. 279c). For unmargined trades, `MF = √(min(M, 1y) / 1y)`; for margined trades, `MF = 1.5 × √(MPOR_eff / 250)`, where the effective margin period of risk runs through the Art. 285 cascade. See [`engine/ccr/maturity_factor.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/7e7ed7ec/src/rwa_calc/engine/ccr/maturity_factor.py).

The trades are then partitioned into **hedging sets** — one per currency-and-maturity-bucket for IR, one per currency pair for FX, one per netting set for credit and equity, one per commodity bucket for commodity ([`engine/ccr/hedging_sets.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/7e7ed7ec/src/rwa_calc/engine/ccr/hedging_sets.py), Art. 277). The hedging-set structure is what lets offsetting positions net: two interest-rate swaps in the same currency and maturity bucket partially cancel; a GBP swap and a USD swap do not.

The **multiplier** (Art. 278(3)) is the term that rewards over-collateralisation and being out of the money:

```
multiplier = min(1, F + (1 − F) × exp((V − C) / (2 × (1 − F) × AddOn_agg)))
```

with the floor F = 0.05. When the netting set is at or above water (`V − C ≥ 0`) the exponent is non-negative and the `min(1, …)` cap pins the multiplier to 1.0 — you get the full add-on. When the set is deeply out of the money or heavily over-collateralised, the multiplier compresses the PFE toward its 5% floor, recognising that a counterparty default on a position you are already underwater on costs you less.

### The Art. 285 MPOR cascade

The margined maturity factor hides a five-step cascade that took real care to get right. The effective margin period of risk starts at a 10-business-day floor for an OTC derivative netting set (Art. 285(2)(b)), upgrades to 20 BD when the set has more than 5,000 trades or contains illiquid collateral (Art. 285(3)), doubles if there have been more than two margin disputes in the prior quarter (Art. 285(4)), and is then adjusted for remargining frequency as `MPOR_eff = base + remargining_frequency_days − 1` (Art. 285(5)). The cascade is the single most fiddly arithmetic in the subsystem, and it is deliberately kept derivatives-only: the 5-BD SFT/repo base of Art. 285(2)(a) never fires here, because securities-financing transactions are priced by a separate FCCM subsystem (more on that below).

## A worked example: one uncollateralised swap

Take a single GBP **pay-fixed interest-rate swap**: notional £100m, starting today, maturing in five years. The netting set is uncollateralised and currently £2m in the money to the bank. No collateral is held.

**Adjusted notional.** With S floored at 10 BD (≈ 0.04 years) and E = 5:

```
SD = (e^(−0.05 × 0.04) − e^(−0.05 × 5)) / 0.05
   = (0.998002 − 0.778801) / 0.05
   = 4.3840
d  = 100,000,000 × 4.3840 = £438.4m
```

**Effective notional.** The trade is long its primary risk driver, so δ = +1. Five years to maturity is well over a year, so the unmargined `MF = √(min(1250, 250)/250) = 1.0`. The effective notional is `δ × d × MF = £438.4m`.

**Add-on.** A single swap sits alone in the 1y–5y IR bucket, so the bucket correlation matrix collapses to `√(D²) = D`, and with the IR supervisory factor of 0.5% (`sa_ccr_supervisory_factor_ir = 0.005`, Art. 280 Table 1):

```
AddOn_IR = 0.005 × 438,400,000 = £2.192m
```

**PFE.** Because `V − C = £2m ≥ 0`, the multiplier caps at 1.0:

```
PFE = 1.0 × 2,192,000 = £2.192m
```

**Replacement cost.** `RC = max(2,000,000 − 0, 0) = £2.0m`.

**EAD.** Finally:

```
EAD = 1.4 × (2,000,000 + 2,192,000) = 1.4 × 4,192,000 = £5.87m
```

A £100m-notional swap becomes a £5.87m exposure-at-default. If the counterparty is a CQS-2 institution, the SA institution table (CRR Art. 120(1) Table 3) applies a 50% risk weight, so the swap contributes roughly £2.93m of RWA — a long way from its notional, and a long way from zero.

The multiplier earns its keep when the sign flips. Hold the same swap but suppose it is now £3m *out of the money*. RC floors to zero, and the multiplier compresses the PFE:

```
exponent  = −3,000,000 / (2 × 0.95 × 2,192,000) = −0.7203
multiplier = 0.05 + 0.95 × e^(−0.7203) = 0.05 + 0.95 × 0.4866 = 0.512
PFE        = 0.512 × 2,192,000 = £1.12m
EAD        = 1.4 × (0 + 1,122,000) = £1.57m
```

Same trade, same notional, same supervisory factor — and the EAD falls from £5.87m to £1.57m because the bank is underwater on the position and the regulation recognises that a default there is cheaper to absorb.

## Slotting SA-CCR into an immutable pipeline

Here is where the engineering gets interesting, and where the architecture from [post 2](2026-05-12-the-pipeline.md) paid off. The pipeline as originally built had no concept of a derivative. It loaded facilities, loans, and contingents; it resolved hierarchies; it classified exposures; it ran SA and IRB calculators. There was nowhere obvious to insert "and also, here is a book of swaps."

The trick — and it is the central engineering decision of the whole subsystem — is that **SA-CCR does not run as a calculator at all. It runs as a row source.** The `ccr_sa_ccr` stage in [`engine/registry.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/7e7ed7ec/src/rwa_calc/engine/registry.py) sits third in the ten-stage pipeline, between the hierarchy resolver and the classifier:

```
securitisation_allocator → hierarchy_resolver → ccr_sa_ccr → sft_fccm
    → classifier → crm_processor → re_splitter → calculators
    → equity_calculator → aggregator
```

The stage adapter ([`engine/stages/ccr.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/7e7ed7ec/src/rwa_calc/engine/stages/ccr.py)) drives the full Art. 274 chain over the firm's netting sets and emits **one synthetic exposure row per netting set**, with `drawn_amount = ead_ccr`. Those rows are concatenated onto the resolved-hierarchy frame with a `diagonal_relaxed` join, so any `RAW_EXPOSURE_SCHEMA` column they do not carry is null-filled. From that point on, a swap netting set *is* an exposure — it flows through the classifier, CRM, the SA calculator, and the aggregator with no CCR-aware special-casing anywhere downstream. The synthetic row is tagged `risk_type = "CCR_DERIVATIVE"`, `ccr_method = "sa_ccr"`, and carries the counterparty reference so the SA institution lookup and any IRB routing see the same rating a traditional lending row would.

This is the immutable-bundle discipline doing exactly what [post 2](2026-05-12-the-pipeline.md) claimed it would: a new row in a new frame, not a mutation of an upstream one. The CCR stage reads the resolved hierarchy and returns a new resolved hierarchy with more rows. Nothing reaches back.

The decomposition inside [`pipeline_adapter.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/7e7ed7ec/src/rwa_calc/engine/ccr/pipeline_adapter.py) is the plain-typed-function pattern carried to its conclusion. `ccr_rows_to_exposures` is a sequence of `.pipe`-style calls — adjusted notional (one call per asset class), supervisory delta, the MPOR cascade denormalisation, the two maturity factors coalesced, hedging-set assignment, per-asset-class add-on, the per-netting-set aggregate, replacement cost, alpha selection, PFE, the transitional add-on — each a free function that takes a LazyFrame and returns a LazyFrame. One regulatory term, one function, in regulatory order.

A small detail I am fond of: the synthetic row surfaces an `addon_by_asset_class` **struct** — `{interest_rate, fx, credit, equity, commodity}` — built so that the five components always sum exactly to `addon_aggregate`. That is not for the calculation; the aggregate is what feeds PFE. It is for **audit**: a reviewer (or a COREP C 34.02 grid) can reconcile a netting set's EAD back to its five asset-class add-ons without re-running the chain. The same row preserves `pfe_multiplier`, `pfe_addon`, `rc_unmargined`, `rc_margined`, `rc`, `alpha_applied`, and `transitional_add_on` as audit columns. The whole calculation is reconstructable from the output row.

## Why a swap has to be two exposures at once

There is a subtle routing requirement that the pipeline architecture makes almost free. A CCR netting set faces a counterparty, and that counterparty may be IRB-permissioned. So the same EAD has to be available to **both** engines: the SA calculator (always, because S-TREA — the standardised floor comparator from [post 5](2026-06-23-the-output-floor-and-why-basel-31-bites.md) — is computed across the entire book as if IRB had never been permitted) and the IRB calculator (when the counterparty carries an internal PD).

Because the synthetic CCR row is just an exposure, both calculators pick it up automatically — the classifier routes it on the counterparty's permissions exactly as it would a loan. The `enrich_ccr_rows_with_ratings` helper in [`engine/stages/_ccr_shared.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/7e7ed7ec/src/rwa_calc/engine/stages/_ccr_shared.py) joins the resolved counterparty rating columns — `cqs`, `internal_pd`, `external_cqs` — onto the CCR rows after hierarchy resolution, so the IRB routing keyed on `internal_pd` and the SA institution lookup keyed on `cqs` both see the right number. Without it, CCR rows would arrive with `cqs = None` and fall through to the unrated 100% fallback.

IRB then needs an **effective maturity** for the CCR exposure, and CRR Art. 162 has opinions. The F-IRB supervisory-maturity helper `_apply_firb_sft_supervisory_maturity` in [`engine/irb/transforms.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/7e7ed7ec/src/rwa_calc/engine/irb/transforms.py) pins repo-style SFT rows to the 0.5-year fixed maturity of Art. 162(1) — but explicitly **excludes** `CCR_DERIVATIVE` rows, because Art. 162(1) covers repos and securities-or-commodities lending only, not derivatives. (Basel 3.1 deletes Art. 162(1) entirely, so under B31 every IRB firm computes M the general way and that branch goes quiet.) The distinction between an SFT carrier and a derivative carrier is exactly the kind of two-answer regulatory question the series keeps running into.

## The edges: CCPs, default funds, failed trades, wrong-way risk

Around the SA-CCR core sit the cases that make CCR genuinely large. The same stage adapter also handles:

- **QCCP trade exposures** ([`engine/ccr/ccp.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/7e7ed7ec/src/rwa_calc/engine/ccr/ccp.py)). A clearing member's own trade exposure to a qualifying CCP gets a 2% risk weight (Art. 306(1)(a)); a client-cleared trade through a clearing member gets 4% (Art. 306(1)(c)). The EAD is the SA-CCR number; only the risk weight changes.
- **Default-fund contributions** ([`engine/ccr/default_fund.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/7e7ed7ec/src/rwa_calc/engine/ccr/default_fund.py)). A clearing member's share of the CCP's hypothetical capital, `K_CM = K_CCP × DF_i / DF_CM` (Art. 308(2)), converted to RWEA via the 12.5 own-funds factor (Art. 308(3)/309(2)).
- **Failed and settlement trades** ([`engine/ccr/failed_trades.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/7e7ed7ec/src/rwa_calc/engine/ccr/failed_trades.py)). The DvP price-difference multiplier ladder of Art. 378 Table 1 and the non-DvP free-delivery treatment of Art. 379 Table 2, both pinned to the 12.5 factor.
- **Wrong-way risk** ([`engine/ccr/wwr.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/7e7ed7ec/src/rwa_calc/engine/ccr/wwr.py)). Trades flagged with specific WWR (Art. 291(1)(b)) are broken out into their own single-trade synthetic netting sets and tagged `wwr_lgd_override = 1.0` so downstream IRB applies LGD = 100% (Art. 291(5)(c)). General WWR raises a diagnostic.

Each of these is a synthetic-row source feeding the same concat. The legal-enforceability gate (Art. 272(4)) runs first of all: if a netting agreement fails the Art. 295–297 recognition test, each trade is expanded into its own single-trade netting set so no netting benefit is recognised on an unenforceable agreement, with a CCR001 warning per affected set. Errors accumulate, as everywhere in this codebase — they never raise.

## Two adjacent subsystems, kept at arm's length

SA-CCR has two close neighbours that deserve a sentence so the spotlight stays clear. **BA-CVA** ([`engine/cva/ba_cva.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/7e7ed7ec/src/rwa_calc/engine/cva/ba_cva.py)) computes the Basel 3.1 Basic Approach to credit-valuation-adjustment risk — the capital charge for the *volatility* of CCR, as opposed to default. Crucially, it consumes the live SA-CCR EAD: the CVA stage joins onto the same `ccr__<ns_id>` synthetic rows, so the CVA charge is computed off the real EAD, not a hand-coded duplicate. And **FCCM** ([`engine/sft/fccm.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/7e7ed7ec/src/rwa_calc/engine/sft/fccm.py)) is the peer `sft_fccm` stage that prices securities-financing transactions via the Financial Collateral Comprehensive Method (Art. 271(2), Art. 220–223) rather than the SA-CCR derivative chain. The separation is enforced: `partition_out_sft_rows` strips any `transaction_type == "sft"` row that wanders into the SA-CCR input and raises a CCR020 data-quality error rather than mis-pricing a repo as a swap.

## What it cost, and the canonical numbers

The CCR subsystem is the clearest demonstration in the project that the architecture from posts 1–8 was the load-bearing investment. Adding an entire new risk type — twelve engine modules, a new pipeline stage, four COREP grids (C 34.01/02/04/08), four Pillar 3 tables (CCR1, CCR2, CCR3, CCR8) — required no change to the classifier's contract, the CRM processor, the SA calculator, the aggregator, or the output floor. The new risk type entered the system as rows, and the rows obeyed the existing contracts. The ten-stage registry grew by two literal entries; everything else was new modules behind old protocols.

The figures, as of HEAD `7e7ed7ec` (in `[Unreleased]`, ~six commits past the 0.3.5 release of 2026-06-26): roughly 7,450 test functions across the suite (about 8,100 collected once parametrised), 186 source files, 17 architectural checks in `scripts/arch_check.py`, and the same seven role-agents driving the build that [post 4](2026-06-09-building-with-an-agent-swarm.md) described. Those numbers move daily; there is now a `scripts/blog_counts.py` that prints the live figures, so a future reader does not have to trust a frozen count in a blog post.

The honest caveat, consistent with the season-one finale: SA-CCR's correctness rests on the same test discipline as everything else — hand-derived acceptance scenarios, an `arch_check` gate, and citation tracking — not on independent model validation. The watchfire CRR index does not yet carry Art. 274–285, so several of these functions keep their article attribution in docstrings with a documented waiver rather than a `@cites` decorator. It is a reference implementation of SA-CCR, transparently partial where it is partial. But it is a real one: a derivative book goes in, and one auditable exposure-at-default per netting set comes out the other side, reconcilable line by line back to the five hedging-set add-ons that produced it.

---

**Read next:** [*Making Regulation Data, Not Code*](2026-09-01-making-regulation-data-not-code.md) — the rulepack packs, cited scalars, and why `sa_ccr_alpha = 1.4` lives in a data file with a `Citation` rather than in an engine module.

**Further reading:**

- [SA-CCR specification cluster](../specifications/crr/ccr/index.md) — the thirteen pages covering EAD composition, replacement cost, the PFE multiplier, hedging sets, the maturity factor, supervisory delta, adjusted notional, wrong-way risk, CCP exposures, failed trades, legal enforceability, and FX treatment.
- [Architecture: Pipeline](../architecture/pipeline.md) — the ten-stage model the `ccr_sa_ccr` stage slots into.
- [The Output Floor and Why Basel 3.1 Bites](2026-06-23-the-output-floor-and-why-basel-31-bites.md) — why CCR EAD feeds S-TREA, the standardised floor comparator.
- [CRR Articles 271–311 (onshored)](https://www.legislation.gov.uk/eur/2013/575/contents) and [BCBS CRE52 (SA-CCR)](https://www.bis.org/basel_framework/standard/CRE.htm) — the underlying methodology.
