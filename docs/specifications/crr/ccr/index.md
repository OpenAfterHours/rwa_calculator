# SA-CCR — Counterparty Credit Risk

Specifications for the Standardised Approach for Counterparty Credit Risk
(SA-CCR), the regulatory method for translating derivatives, long-settlement
transactions and securities financing transactions (SFTs) into a single
exposure-at-default (EAD) figure that then feeds the SA / IRB credit-risk
exposure ladder.

**Primary regulatory source:** PRA PS1/26 Part Three Title II Chapter 6
(Art. 271–311) — the UK SA-CCR regime is largely a verbatim re-export of the
onshored CRR text with the Basel 3.1 alpha (1.4) and supervisory-factor
calibration retained. References on each child page follow the
PRA-priority convention: PRA Art. numbers first, BCBS CRE codes as a
secondary cross-reference.

**Engine entry point:** [`src/rwa_calc/engine/ccr/pipeline_adapter.py::ccr_rows_to_exposures`](https://github.com/OpenAfterHours/rwa_calculator/blob/master/src/rwa_calc/engine/ccr/pipeline_adapter.py)
— shapes SA-CCR netting-set EADs into synthetic exposure rows compatible with
`RAW_EXPOSURE_SCHEMA`, so the downstream Classifier / CRM / SA Calculator
chain consumes a CCR row identically to an on-balance-sheet loan.

---

## Pipeline shape

SA-CCR is a strictly ordered chain. Each stage consumes the prior stage's
LazyFrame and emits a new one — there are no back-edges. The orchestrator at
`engine/ccr/pipeline_adapter.py::ccr_rows_to_exposures` chains the per-trade
stages over the legally-enforceable trades in a `RawCCRBundle`, then aggregates
to one synthetic exposure row per netting set:

```
ccr_rows_to_exposures(raw_ccr, config_ccr, reporting_date)
  │
  ├─ 1. Adjusted notional               (Art. 279b)
  │     ├─ compute_adjusted_notional_ir         (Art. 279b(1)(a))
  │     ├─ compute_adjusted_notional_fx         (Art. 279b(1)(b))   [if fx_rates supplied]
  │     ├─ compute_adjusted_notional_credit     (Art. 279b(1)(a))   [placeholder]
  │     ├─ compute_adjusted_notional_equity     (Art. 279b(1)(c))   [placeholder]
  │     └─ compute_adjusted_notional_commodity  (Art. 279b(1)(c))   [placeholder]
  │
  ├─ 2. Supervisory delta               (Art. 279a)
  │     └─ compute_supervisory_delta_option     (±1 linear / Black-Scholes Φ(d1) for options)
  │
  ├─ 3. Maturity factor                 (Art. 279c unmargined, Art. 285 margined)
  │     └─ compute_maturity_factor_unmargined   (margined branch pending)
  │
  ├─ 4. Hedging-set partition           (Art. 277, 277a)
  │     └─ assign_hedging_set                   (IR per currency / maturity bucket,
  │                                              FX per currency pair, credit/equity per ref,
  │                                              commodity per type)
  │
  ├─ 5. Asset-class add-on              (Art. 277a(2)–(3))
  │     └─ compute_addon_per_asset_class        (SF · |D_HS|, per HS then per NS)
  │
  ├─ 6. Replacement cost (RC)           (Art. 275)
  │     └─ unmargined: RC = max(V − C, 0)       (margined RC pending)
  │
  ├─ 7. PFE multiplier + add-on         (Art. 278)
  │     └─ compute_pfe                          (mult = min(1, 0.05 + 0.95·exp((V−C)/(2·AddOn))))
  │
  └─ 8. EAD                             (Art. 274(2))
        └─ EAD = α · (RC + PFE),  α = 1.4
```

The resulting per-netting-set EAD is written to `drawn_amount` on a synthetic
exposure row with `risk_type = "CCR_DERIVATIVE"`, `ccr_method = "sa_ccr"` and
`source_netting_set_id` for downstream reconciliation. From that point on the
row is treated as any other unsecured exposure — Classifier resolves the
counterparty class, the SA calculator looks up the risk weight from
[Art. 112–134](../sa-risk-weights.md), and the aggregator rolls the resulting
RWA into the firm-level totals.

---

## Specification index

| Page | Topic | Regulatory reference | Status |
|------|-------|----------------------|--------|
| [Adjusted notional](adjusted-notional.md) | Per-asset-class notional adjustments (`d`); IR supervisory duration; FX leg conversion at spot | Art. 279b | Live (IR + FX) |
| [FX treatment](fx-treatment.md) | Two-leg trade schema, FX hedging set, asset-class add-on, CCR-A2 worked example | Art. 277(3)(a), 279b(1)(b), 277a(2) | Live |
| [Supervisory delta](supervisory-delta.md) | Linear ±1 delta for forwards/swaps; Black-Scholes Φ(d1) for options; CDO tranche attachment-point delta | Art. 279a(1)–(3) | Live (IR + FX) |
| [Maturity factor](maturity-factor.md) | Unmargined MF = √(min(M, 1)); margined MF with MPOR + remargining frequency | Art. 279c, 285 | Live |
| [Hedging sets](hedging-sets.md) | Per-asset-class hedging-set partition rules and intra/cross-HS correlation (ρ) | Art. 277, 277a | Live (IR + FX) |
| `rc-calculation.md` | Unmargined `RC = max(V − C, 0)`; margined `RC = max(V − C, TH + MTA − NICA, 0)` | Art. 275 | Pending |
| `pfe-multiplier.md` | PFE add-on aggregation and the multiplier `min(1, 0.05 + 0.95·exp((V−C)/(2·AddOn)))` | Art. 278 | Pending |
| `ead-composition.md` | EAD = α·(RC + PFE) with α = 1.4; SA-CCR → unified exposure ladder via `pipeline_adapter` | Art. 274 | Pending |
| [Legal enforceability](legal-enforceability.md) | Netting-set recognition gate; single-trade synthetic-NS fallback for non-enforceable agreements | Art. 272(4), 295–297 | Live |
| [Wrong-way risk](wrong-way-risk.md) | Specific WWR (legal connection ⇒ LGD = 100% override); general WWR α multiplier | Art. 291 | Live (IR + FX) |
| [CCP exposures](ccp-exposures.md) | QCCP 2% trade-leg RW; default-fund contribution treatment; non-QCCP fallback | Art. 306–311 | Live |
| [Failed trades](failed-trades.md) | Unsettled DvP transactions and free deliveries; multiplier ladder by business-day delay | Art. 378–380 | Live |

The "Pending" pages will land as the SA-CCR engine batches P8.35–P8.38
(credit / equity / commodity add-ons, margined RC, WWR, CCP, failed-trade
ladder) ship — see the project root `IMPLEMENTATION_PLAN.md` for the
ordering. Each page, when written, mirrors the structure of the existing
[adjusted-notional](adjusted-notional.md) and [fx-treatment](fx-treatment.md)
pages: regulatory citation, formula, engine entry point, pipeline ordering
note, and a worked acceptance scenario.

---

## Asset-class coverage

SA-CCR partitions every trade into one of five asset classes (Art. 277(1));
each has its own supervisory factor, hedging-set rule and add-on aggregator.
The engine ships the IR + FX branches; the remaining three classes carry
placeholder no-op functions in `engine/ccr/adjusted_notional.py` and emit
null `adjusted_notional` until the engine batches P8.35–P8.38 land.

| Asset class | Hedging-set rule | Supervisory factor (Art. 280 Table 1) | Status |
|-------------|------------------|---------------------------------------|--------|
| Interest rate | Per currency, with maturity sub-buckets (< 1y / 1–5y / > 5y) per Art. 277(2) | 0.5% (IRS / FRA) | Documented |
| FX | Per currency pair (order-independent) per Art. 277(3)(a); no maturity sub-buckets | 4.0% | Documented |
| Credit | Per single name / index reference per Art. 277(3)(b); cross-HS ρ = 0.5 | 0.38% (IG single name) – 4.7% (sub-IG / index) | Pending engine batch P8.35–P8.38 |
| Equity | Per single name / index reference per Art. 277(3)(c); cross-HS ρ = 0.5 | 32% (single name) / 20% (index) | Pending engine batch P8.35–P8.38 |
| Commodity | Per commodity type (energy / metals / agriculture / climate / other) per Art. 277(3)(d); cross-HS ρ = 0.4 | 4% (electricity) – 18% (electricity, sub-types) | Pending engine batch P8.35–P8.38 |

> **Citation note:** the supervisory factors above are illustrative
> orders-of-magnitude. The authoritative per-row values live in the
> regulatory table at PRA PS1/26 Art. 280 Table 1 and will be reproduced
> verbatim on `hedging-sets.md` when that page lands.

---

## Scenario coverage — `CCR-A`

SA-CCR scenarios use the `CCR-A` prefix, matching the `CRR-*` / `B31-*`
convention documented on the [specifications index](../../index.md#scenario-id-convention).
The table below is a **placeholder roadmap** — to be finalised as scenarios
are implemented in the engine batches P8.35–P8.38 and earlier. Scenario
IDs that are already shipped link to the corresponding acceptance test;
unshipped IDs are reserved.

| Scenario | Description | Primary citation | Status |
|----------|-------------|------------------|--------|
| CCR-A1 | Unmargined single-trade netting set (IR swap) — baseline RC = 0, PFE = α·SF·d·MF | Art. 274–278 | Shipped (`tests/acceptance/ccr/test_ccr_a1_unmargined_ir_swap.py`) |
| CCR-A2 | Unmargined single-trade netting set (FX forward) — FX hedging-set, spot conversion | Art. 277(3)(a), 279b(1)(b) | Shipped (`tests/acceptance/ccr/test_ccr_a2_unmargined_fx_forward.py`) |
| CCR-A3 | Margined netting set with IM / VM, MPOR scaling, threshold + MTA in RC | Art. 275(2), 285 | Placeholder |
| CCR-A4 | Multi-trade netting set with IR maturity-bucket aggregation (`< 1y`, `1–5y`, `> 5y`) | Art. 277(2), 277a(1) | Placeholder |
| CCR-A5 | Non-enforceable netting fallback — each trade in its own synthetic single-trade NS | Art. 272(4) | Placeholder |
| CCR-A6 | Option supervisory delta — Black-Scholes Φ(d1) for puts and calls | Art. 279a(2) | Placeholder |
| CCR-A7 | CDO tranche supervisory delta — attachment / detachment point adjustment | Art. 279a(3) | Placeholder |
| CCR-A8 | QCCP trade-leg exposure — 2% risk weight | Art. 306 | Placeholder |
| CCR-A9 | Non-QCCP fallback — bilateral treatment of CCP exposure | Art. 306(4) | Placeholder |
| CCR-A10 | Specific WWR override — LGD = 100% on the WWR sub-portfolio (synthetic single-trade NS) | Art. 291(4)–(5) | Placeholder |
| CCR-A11 | Failed-trade ladder — DvP unsettled transactions, business-day delay multipliers | Art. 378–380 | Placeholder |

!!! warning "Placeholder — to be finalised"
    Scenarios CCR-A3 through CCR-A11 are reserved IDs only. Names,
    one-line descriptions and citations will be confirmed when the
    matching acceptance tests are committed; expect minor renumbering
    if a new scenario is interleaved. Operators should not cite the
    placeholder rows as evidence of implemented behaviour — the
    [specifications index](../../index.md#scenario-id-convention)
    remains the source of truth for shipped scenarios.

---

## Cross-references

- [Specifications index](../../index.md) — full list of CRR / Basel 3.1 / CCR
  scenario prefixes and per-spec regulatory references.
- [Overview](../../../overview.md) — project overview with the SA-CCR pipeline
  positioned in the broader RWA calculation.
- [SA risk weights (CRR)](../sa-risk-weights.md) — risk-weight lookup the
  CCR EAD flows through downstream of `pipeline_adapter.py`.
- [Adjusted notional](adjusted-notional.md) — per-asset-class `d` formula and
  the IR + FX worked-through reference.
- [FX treatment](fx-treatment.md) — end-to-end CCR-A2 worked example showing
  the full chain from input row to RWA.

## References

- **PRA PS1/26 Part Three Title II Chapter 6 (Art. 271–311)** — UK SA-CCR
  regime; primary regulatory source for every page in this directory.
- **BCBS CRE52** — underlying methodology and Basel-level calibration of
  supervisory factors, correlations and the α = 1.4 scalar.
- **`src/rwa_calc/engine/ccr/pipeline_adapter.py`** — orchestrator that
  chains the per-trade SA-CCR stages and emits the netting-set-grain
  synthetic exposure rows.
