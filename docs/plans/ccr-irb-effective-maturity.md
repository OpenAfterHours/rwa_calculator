# CCR / SFT IRB Effective Maturity (Art. 162) — Implementation Plan

> **Status:** Implemented (F-IRB end-to-end; A-IRB routing a follow-up) · **Owner:** orchestrator (main session) · **Created:** 2026-06-20
> **Scope decision:** FCCM SFT (`risk_type = "CCR_SFT"`) and SA-CCR derivative (`risk_type = "CCR_DERIVATIVE"`) synthetic rows that route to IRB. Lending rows were already correct; the change is purely additive.
> **Regulatory basis:** CRR Art. 162(1) / (2)(c)(d) / (3); PRA PS1/26 Art. 162(2) / (2A) / (3).

This is the published narrative companion to the worked implementation plan
(`.claude/state/ccr-irb-maturity-fix-plan.md`). It records *why* the change was needed, the
regulatory model it satisfies, and the design that keeps the two unrelated meanings of "SFT"
separate.

---

## 1. Why — the gap

Synthetic CCR exposure rows — FCCM SFTs (`engine/sft/fccm.py`) and SA-CCR derivatives
(`engine/ccr/pipeline_adapter.py`) — are concatenated into `resolved.exposures` and re-sealed to
the existing `ccr_exit` brand. When the counterparty has an internal PD and the firm holds IRB
permission for the class, these rows route to F-IRB / A-IRB and hit the IRB effective-maturity
(`M`) priority chain in `engine/irb/transforms.py::_build_maturity_exprs`.

That chain reads **lending-side** maturity drivers (`is_sft`, `has_one_day_maturity_floor`,
`is_short_term_trade_lc`, `effective_maturity`, `maturity_date`). The synthetic rows carried
**only `maturity_date`**; every other driver was `diagonal_relaxed`-null-filled to its schema
default. Consequences:

- A repo-style FCCM SFT under **CRR + F-IRB** should get the fixed `M = 0.5y` (Art. 162(1)) — but
  the F-IRB supervisory-maturity rung gated on `is_sft = True`, which is never set, so `M` fell to
  the date-derived value floored at `1.0y`. **Wrong.**
- A daily-remargined repo under a master netting agreement should reach the `~1-day` floor
  (Art. 162(3)); the intermediate `5BD` (repo, Art. 162(2)(d)) and `10BD` (collateralised
  derivative, Art. 162(2)(c)) floors exist below `1y` — but no engine path derived any of them for
  CCR / SFT rows.
- A non-daily-remargined repo correctly defaults to the `1y` catch-all (Art. 162(2)(f)) — the
  **regression anchor**, preserved bit-stable.

## 2. Regulatory model

`Article 162` is corporate / institution-scoped (retail has no `M` term; `MA = 1.0`). The
maturity floors are **minimums on the remaining maturity** at a calendar `/365` day-count, not
fixed replacement values: `M = clip(remaining, floor, 5y)`.

| Regime | Approach | Transaction | `M` rule | Citation |
|---|---|---|---|---|
| CRR | F-IRB | repo-style | fixed **0.5y** (not a floor; not 0.4y) | Art. 162(1) |
| CRR | F-IRB | all other | fixed 2.5y | Art. 162(1) |
| CRR | A-IRB | collateralised derivs / margin lending under MNA | floor **10 days** | Art. 162(2)(c) |
| CRR | A-IRB | repos / securities lending under MNA | floor **5 days** | Art. 162(2)(d) |
| CRR | A-IRB | other / not calculable | floor **1y** (non-daily repo lands here) | Art. 162(2)(f) |
| CRR | A-IRB | daily re-margin **AND** revaluation + prompt liquidation | floor **1 day** | Art. 162(3) |
| **B31** | F+A-IRB | repo-style fixed 0.5y / SME 162(4) | **deleted** ("[Provision left blank]") | PS1/26 Art. 162(1), (4) |
| B31 | F+A-IRB | collateralised derivs / margin lending under MNA (daily re-margin **OR** revaluation + prompt liquidation) | floor **10 days** | PS1/26 Art. 162(2A)(c) |
| B31 | F+A-IRB | repos / securities lending under MNA (daily re-margin **OR** revaluation + prompt liquidation) | floor **5 days** | PS1/26 Art. 162(2A)(d) |
| B31 | F+A-IRB | **mixed MNA** (both (c)- and (d)-type) | floor **10 days** (new, no CRR equiv) | PS1/26 Art. 162(2A)(da) |
| B31 | F+A-IRB | daily re-margin **AND** revaluation + prompt liquidation | floor **1 day** | PS1/26 Art. 162(3) |

> **Correctness traps — verified against `docs/assets/crr.pdf` (pp. 157–159) and
> `docs/assets/ps126app1.pdf` (pp. 111–113):**
> 1. F-IRB repo `M = 0.5y` is **CRR Art. 162(1)** — a fixed value, NOT 0.4y, NOT Art. 162(3).
>    Deleted under Basel 3.1.
> 2. Art. 162(3)'s one-day floor keeps the **conjunctive** "daily re-margining **AND** daily
>    revaluation" trigger under **both** regimes. Only the 10d / 5d Art. 162(2A)(c)/(d) floors
>    switched CRR's "and" to Basel 3.1's "or".
> 3. The floors require the transactions be **subject to a master netting agreement**; without it
>    the row falls to the 162(2)(f) / (2A)(f) `1y` catch-all.

## 3. Design — a dedicated carrier, never `is_sft`

`M` for CCR / SFT rows is computed **at the producer** (where the margining signal lives) and
surfaced on a new dedicated `Float64` column `ccr_effective_maturity` — never on `is_sft`, never
overloading the firm-input `effective_maturity` override. The F-IRB 0.5y signal is delivered by
**widening the IRB-chain gate** to `(is_sft OR risk_type == CCR_SFT)`, downstream of CRM, so
`is_sft` keeps its CRM meaning.

**Why not `is_sft = True` on synthetic rows.** `is_sft` is a live CRM input driving Art. 226(2)
liquidation-period scaling + HE gating, Art. 207(2) covered-bond eligibility, the FCSM Art. 222(4)
simple-method carve-out and multi-level beneficiary resolution. The synthetic row's `drawn_amount`
is **already** the post-haircut `E*`, so re-arming any `is_sft` consumer risks a double haircut.
The carrier keeps all of these provably untouched.

`has_one_day_maturity_floor` is set from the **winning rung inside the IRB chain** (not at the
producer) — so CRM, which runs earlier, never sees a CCR one-day signal and no collateral is
silently zeroed by Art. 237(2). When the carrier resolves to the Art. 162(3) one-day value, the
maturity adjustment uses the actual sub-1-year `M` rather than re-flooring to 1 year.

## 4. Phases

| Phase | What | Status |
|---|---|---|
| 0 | Lock the reg hand-calcs + anchor `M` values; companion design doc | done |
| 1 | Pack scalars + features (`one_day_maturity_floor_years = 1/365`, `firb_sft_supervisory_maturity_years = 0.5`, `ccr_synthetic_maturity` feature) | done |
| 2 | `ccr_effective_maturity` carrier on `CCR_EXIT_EDGE`; MNA + one-day-qualifying input flags | done |
| 3 | Producer projection of the carrier onto CCR / SFT rows (SFT first; derivatives reuse the helper) | done |
| 4 | IRB maturity chain — carrier rung, widened F-IRB gate, clip to `[one-day-floor, 5y]`, winning-rung flag | done |
| 5 | Fixtures, acceptance + contract tests asserting `M` directly under both regimes | done |
| 6 | Docs / specs / changelog / `@cites` | this document |

## 5. Coverage and the A-IRB follow-up

- **F-IRB is proven end-to-end**: a `CCR_SFT` row routes to F-IRB and receives the correct
  Art. 162 `M` (0.5y under CRR; date-derived under Basel 3.1).
- **A-IRB routing for CCR rows is a separate follow-up.** Reaching A-IRB additionally requires an
  own-modelled LGD on the synthetic row, which the FCCM producer does not yet emit. The
  `ccr_effective_maturity` carrier and the new IRB rung are AIRB-ready, so closing that gap is
  purely additive (the A-IRB anchors are currently `xfail`).

## 6. Regression safety

- **SA-path rows are unchanged.** SA risk weights read only `original_maturity_years` /
  `residual_maturity_years`, never the carrier or the one-day flag. The carrier + new rung +
  widened F-IRB gate are IRB-only.
- **`is_sft` stays null/False on all synthetic rows** (pinned by a contract test at the
  `crm_exit` edge), so none of its CRM consumers fire.
- Carrier changes are additive (null off-carve-out), so `CCR-IRB-1` (5y swap, `M = 5.0`) and the
  SA-routed CCR-A11/A12 / CCR-A15..A18 goldens stay bit-stable.
- All tests anchor on `irb_maturity_m` directly — Polars group-by float sums are
  non-process-deterministic, so RWA-level assertions would be flaky.

## 7. References

- **CRR Art. 162(1)** — F-IRB fixed supervisory maturities (repo-style 0.5y; other 2.5y).
- **CRR Art. 162(2)(c)/(d)** — 10-day / 5-day MNA minimums.
- **CRR Art. 162(3)** — one-day floor (daily re-margining **and** revaluation + prompt
  liquidation) and the qualifying short-term carve-out.
- **PRA PS1/26 Art. 162(2A)(c)/(d)/(da)** — the Basel 3.1 floors (daily re-margining **or**
  revaluation) and the new mixed-MNA 10-day floor.
- [`engine/sft/fccm.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/master/src/rwa_calc/engine/sft/fccm.py) — FCCM SFT producer (carrier source).
- [`engine/irb/transforms.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/master/src/rwa_calc/engine/irb/transforms.py) — IRB maturity chain (carrier rung + widened F-IRB gate).
- [CRR F-IRB specification](../specifications/crr/firb-calculation.md) · [Basel 3.1 F-IRB specification](../specifications/basel31/firb-calculation.md) · [FCCM SFT specification](../specifications/crr/sft/index.md).
