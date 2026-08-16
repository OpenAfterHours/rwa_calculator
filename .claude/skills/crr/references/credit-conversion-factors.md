# CRR Credit Conversion Factors

**Regulatory Reference:** CRR Articles 111, 166

> Values are generated from the rulepack — see the table below. Regenerate with
> `uv run python scripts/generate_regulatory_tables.py`.

---

## The CRR shape

CRR runs **two separate CCF schedules**, and the F-IRB one is generally *more* punitive
than SA for the middle categories — the opposite of the intuition that IRB is always the
lighter approach:

- **SA (Art. 111)** — `sa_ccf`, keyed by risk category. A risk category the ladder does
  not name falls to **Annex I item 1(k)**, "other items also carrying full risk". That is
  the only residual with no supervisory-notification condition: items 2(b)(iv), 3(b)(ii)
  and 4(c) each read "and as communicated to the competent authority", and an item the
  engine could not classify has by definition not been notified. There is deliberately no
  shared `sa_ccf_default` entry — PS1/26 Table A1 writes its residuals differently, so
  the two regimes must not share one (see `basel31/references/credit-conversion-factors.md`).
- **F-IRB (Art. 166(8)-(9))** — `firb_credit_line_ccf` for general commitments, with
  `firb_trade_lc_ccf` as the Art. 166(9) exception for short-term trade letters of credit
  covering goods movements, and `firb_obs_fallback_ccf` for anything unmapped.

Basel 3.1 collapses both onto SA Table A1 (`firb_uses_sa_ccf`) — so a CRR F-IRB CCF must
never be reused in a Basel 3.1 scenario.

Commitment classification under CRR turns on **maturity**: `oc_short_maturity_ccf` applies
below `oc_short_maturity_threshold_days`, with the longer-dated case taking the medium-risk
category. Basel 3.1 replaces that split with a single flat "other commitments" factor.

`obs_product_to_risk_type` is the map from product string to risk category. It is the
classification step that decides *which* CCF applies, and the usual reason a hand-calc
disagrees with the engine.

<!-- BEGIN GENERATED: crr-ccf-values -->
### `sa_ccf`

**CRR** — CRR Art. 111
 *(SA CCFs (Annex I): FR/FRC 100%, MR/OC 50%, MLR 20%, LR 0%)*

Key column: `risk_type`

| Key | Value |
|---|---|
| `FR` | `1.00` |
| `FRC` | `1.00` |
| `MR` | `0.50` |
| `MR_ISSUED` | `0.50` |
| `OC` | `0.50` |
| `MLR` | `0.20` |
| `LR` | `0.00` |

**Basel 3.1** — PS1/26, paragraph 111
 *(Table A1 SA CCFs (OC 40% Row 5, LR/UCC 10% Row 6))*

Key column: `risk_type`

| Key | Value |
|---|---|
| `FR` | `1.00` |
| `FRC` | `1.00` |
| `MR` | `0.50` |
| `MR_ISSUED` | `0.50` |
| `OC` | `0.40` |
| `MLR` | `0.20` |
| `LR` | `0.10` |

### `obs_product_to_risk_type`

**Both regimes** — CRR Art. 111
 *(Annex I OBS product -> risk_type bucket)*

Key column: `obs_product`

| Key | Value |
|---|---|
| `ACCEPTANCE` | `FR` |
| `PERFORMANCE_BOND` | `MLR` |
| `WARRANTY` | `MLR` |
| `TENDER_BOND` | `MLR` |
| `BID_BOND` | `MLR` |
| `DOCUMENTARY_CREDIT` | `MLR` |
| `TRADE_LC` | `MLR` |

| Name | CRR | Basel 3.1 | Citation |
|---|---|---|---|
| `oc_short_maturity_ccf` | `0.20` | `0.20` | CRR Art. 111 |
| `oc_short_maturity_threshold_days` | `365` | `365` | CRR Art. 111 |
| `firb_credit_line_ccf` | `0.75` | — | CRR Art. 166 |
| `firb_trade_lc_ccf` | `0.20` | — | CRR Art. 166 |

### `firb_obs_fallback_ccf`

**CRR** — CRR Art. 166
 *((10) F-IRB fallback: FR 100%, MR/OC 50%, MLR 20%, LR 0%)*

Key column: `risk_type`; default `0.50`

| Key | Value |
|---|---|
| `FR` | `1.00` |
| `FRC` | `1.00` |
| `MR` | `0.50` |
| `MR_ISSUED` | `0.50` |
| `OC` | `0.50` |
| `MLR` | `0.20` |
| `LR` | `0.00` |
<!-- END GENERATED: crr-ccf-values -->

## EAD Formula

```
EAD = drawn_amount + accrued_interest + (undrawn_amount x CCF)
```

Where provisions are present (**SA only**), they are deducted before the CCF is applied,
using the drawn-first deduction approach — see
[provisions-and-el.md](provisions-and-el.md).

---

> **Full detail:** `docs/specifications/crr/credit-conversion-factors.md`
> **All pack entries:** `docs/data-model/regulatory-tables.md`
