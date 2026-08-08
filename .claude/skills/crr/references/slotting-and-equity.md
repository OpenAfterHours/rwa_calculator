# CRR Slotting & Equity

**Regulatory Reference:** CRR Articles 147(8), 153(5), 155

> Values are generated from the rulepack — see the tables below. Regenerate with
> `uv run python scripts/generate_regulatory_tables.py`.

---

## Specialised Lending Types

| Type | Abbreviation | Description |
|------|-------------|-------------|
| Project Finance | PF | Long-term infrastructure/industrial projects |
| Object Finance | OF | Ships, aircraft, physical assets |
| Commodities Finance | CF | Commodity inventory financing |
| Income-Producing RE | IPRE | CRE where repayment depends on rental income |
| High Volatility CRE | HVCRE | CRE with higher risk characteristics |

## Slotting risk weights (Art. 153(5))

Categories are slotted by supervisory criteria, then split by residual maturity against
`slotting_short_maturity_threshold_years`. The short-maturity table is the same grid's
short band, not a separate regulatory concept.

Default slots to a **zero risk weight** and is captured through expected loss instead —
the `slotting_el_*` tables. Reading the RW table alone understates the capital effect of
a defaulted slotted exposure.

> ⚠️ **UK CRR has no HVCRE concept.** The term "high volatility commercial real estate"
> does not appear anywhere in the UK onshored CRR. Art. 153(5) contains **only** Table 1.
> The `slotting_rw_hvcre` / `slotting_el_hvcre` entries below carry the original EU CRR
> table for reference and for the Basel 3.1 regime, which *does* re-introduce HVCRE.
> **Do not apply HVCRE weights under UK CRR.** See
> `docs/specifications/crr/slotting-approach.md` for the carve-out rationale.

<!-- BEGIN GENERATED: crr-slotting-and-equity-values -->
| Name | CRR | Basel 3.1 | Citation |
|---|---|---|---|
| `slotting_short_maturity_threshold_years` | `2.5` | `2.5` | CRR Art. 153(5) |

### `slotting_rw_base`

**CRR** — CRR Art. 153(5)
 *(slotting RW, remaining maturity >= 2.5y)*

Key column: `slotting_category`; default `1.15`

| Key | Value |
|---|---|
| `strong` | `0.70` |
| `good` | `0.90` |
| `satisfactory` | `1.15` |
| `weak` | `2.50` |
| `default` | `0.00` |

**Basel 3.1** — PS1/26, paragraph 153
 *((5) Table A slotting RW (>= 2.5y))*

Key column: `slotting_category`; default `1.15`

| Key | Value |
|---|---|
| `strong` | `0.70` |
| `good` | `0.90` |
| `satisfactory` | `1.15` |
| `weak` | `2.50` |
| `default` | `0.00` |

### `slotting_rw_short`

**CRR** — CRR Art. 153(5)
 *(slotting RW, remaining maturity < 2.5y)*

Key column: `slotting_category`; default `1.15`

| Key | Value |
|---|---|
| `strong` | `0.50` |
| `good` | `0.70` |
| `satisfactory` | `1.15` |
| `weak` | `2.50` |
| `default` | `0.00` |

**Basel 3.1** — PS1/26, paragraph 153
 *((5)(d) Table A slotting RW (< 2.5y))*

Key column: `slotting_category`; default `1.15`

| Key | Value |
|---|---|
| `strong` | `0.50` |
| `good` | `0.70` |
| `satisfactory` | `1.15` |
| `weak` | `2.50` |
| `default` | `0.00` |

### `slotting_rw_hvcre`

**CRR** — CRR Art. 153(5)
 *(HVCRE slotting RW, remaining maturity >= 2.5y)*

Key column: `slotting_category`; default `1.15`

| Key | Value |
|---|---|
| `strong` | `0.95` |
| `good` | `1.20` |
| `satisfactory` | `1.40` |
| `weak` | `2.50` |
| `default` | `0.00` |

**Basel 3.1** — PS1/26, paragraph 153
 *((5) Table A HVCRE slotting RW (>= 2.5y))*

Key column: `slotting_category`; default `1.15`

| Key | Value |
|---|---|
| `strong` | `0.95` |
| `good` | `1.20` |
| `satisfactory` | `1.40` |
| `weak` | `2.50` |
| `default` | `0.00` |

### `slotting_rw_hvcre_short`

**CRR** — CRR Art. 153(5)
 *(HVCRE slotting RW, remaining maturity < 2.5y)*

Key column: `slotting_category`; default `1.15`

| Key | Value |
|---|---|
| `strong` | `0.70` |
| `good` | `0.95` |
| `satisfactory` | `1.40` |
| `weak` | `2.50` |
| `default` | `0.00` |

**Basel 3.1** — PS1/26, paragraph 153
 *((5)(d) Table A HVCRE slotting RW (< 2.5y))*

Key column: `slotting_category`; default `1.15`

| Key | Value |
|---|---|
| `strong` | `0.70` |
| `good` | `0.95` |
| `satisfactory` | `1.40` |
| `weak` | `2.50` |
| `default` | `0.00` |

### `slotting_el_base`

**CRR** — CRR Art. 158(6)
 *(slotting EL rate, remaining maturity >= 2.5y)*

Key column: `slotting_category`; default `0.028`

| Key | Value |
|---|---|
| `strong` | `0.004` |
| `good` | `0.008` |
| `satisfactory` | `0.028` |
| `weak` | `0.08` |
| `default` | `0.50` |

**Basel 3.1** — PS1/26, paragraph 158
 *((6) Table B slotting EL rate (>= 2.5y))*

Key column: `slotting_category`; default `0.028`

| Key | Value |
|---|---|
| `strong` | `0.004` |
| `good` | `0.008` |
| `satisfactory` | `0.028` |
| `weak` | `0.08` |
| `default` | `0.50` |

### `slotting_el_short`

**CRR** — CRR Art. 158(6)
 *(slotting EL rate, remaining maturity < 2.5y)*

Key column: `slotting_category`; default `0.028`

| Key | Value |
|---|---|
| `strong` | `0.0` |
| `good` | `0.004` |
| `satisfactory` | `0.028` |
| `weak` | `0.08` |
| `default` | `0.50` |

**Basel 3.1** — PS1/26, paragraph 158
 *((6) Table B slotting EL rate (< 2.5y))*

Key column: `slotting_category`; default `0.028`

| Key | Value |
|---|---|
| `strong` | `0.0` |
| `good` | `0.004` |
| `satisfactory` | `0.028` |
| `weak` | `0.08` |
| `default` | `0.50` |

### `slotting_el_hvcre`

**CRR** — CRR Art. 158(6)
 *(HVCRE slotting EL rate (flat, no maturity split))*

Key column: `slotting_category`; default `0.028`

| Key | Value |
|---|---|
| `strong` | `0.004` |
| `good` | `0.004` |
| `satisfactory` | `0.028` |
| `weak` | `0.08` |
| `default` | `0.50` |

**Basel 3.1** — PS1/26, paragraph 158
 *((6) Table B HVCRE slotting EL rate (flat))*

Key column: `slotting_category`; default `0.028`

| Key | Value |
|---|---|
| `strong` | `0.004` |
| `good` | `0.004` |
| `satisfactory` | `0.028` |
| `weak` | `0.08` |
| `default` | `0.50` |

### `equity_sa_risk_weights`

**CRR** — CRR Art. 133
 *(Art. 133(2) 100% flat / Art. 132(2) CIU 1250%)*

Key column: `equity_type`; default `1.00`

| Key | Value |
|---|---|
| `central_bank` | `0.00` |
| `subordinated_debt` | `1.00` |
| `listed` | `1.00` |
| `exchange_traded` | `1.00` |
| `government_supported` | `1.00` |
| `unlisted` | `1.00` |
| `speculative` | `1.00` |
| `private_equity` | `1.00` |
| `private_equity_diversified` | `1.00` |
| `ciu` | `12.50` |
| `other` | `1.00` |

**Basel 3.1** — PS1/26, paragraph 133
 *(Art. 133(3)-(5) equity SA RW 250%/400%/150%)*

Key column: `equity_type`; default `2.50`

| Key | Value |
|---|---|
| `central_bank` | `0.00` |
| `subordinated_debt` | `1.50` |
| `listed` | `2.50` |
| `exchange_traded` | `2.50` |
| `government_supported` | `2.50` |
| `unlisted` | `2.50` |
| `speculative` | `4.00` |
| `private_equity` | `4.00` |
| `private_equity_diversified` | `4.00` |
| `ciu` | `12.50` |
| `other` | `2.50` |

| Name | CRR | Basel 3.1 | Citation |
|---|---|---|---|
| `equity_irb_approaches_available` | on | off | CRR Art. 155 / PS1/26, paragraph 133 |

### `equity_irb_simple_risk_weights`

**CRR** — CRR Art. 155
 *((2) IRB simple PE-div 190%/exch 290%/other 370%)*

Key column: `equity_type`; default `3.70`

| Key | Value |
|---|---|
| `central_bank` | `0.00` |
| `subordinated_debt` | `3.70` |
| `private_equity_diversified` | `1.90` |
| `private_equity` | `3.70` |
| `exchange_traded` | `2.90` |
| `listed` | `2.90` |
| `government_supported` | `3.70` |
| `unlisted` | `3.70` |
| `speculative` | `3.70` |
| `ciu` | `3.70` |
| `other` | `3.70` |

### `equity_irb_simple_el`

**CRR** — CRR Art. 158(7)
 *(IRB simple equity EL 0.8% div-PE/exch, 2.4% other)*

Key column: `equity_type`; default `0.024`

| Key | Value |
|---|---|
| `central_bank` | `0.0` |
| `subordinated_debt` | `0.024` |
| `private_equity_diversified` | `0.008` |
| `private_equity` | `0.024` |
| `exchange_traded` | `0.008` |
| `listed` | `0.008` |
| `government_supported` | `0.024` |
| `unlisted` | `0.024` |
| `speculative` | `0.024` |
| `ciu` | `0.024` |
| `other` | `0.024` |

### `equity_pd_floors`

**CRR** — CRR Art. 165
 *((1) minimum PDs by equity sub-type)*

| Parameter | Value |
|---|---|
| `exchange_traded_long_term` | `0.0009` |
| `non_exchange_regular_cashflow` | `0.0009` |
| `exchange_traded` | `0.0040` |
| `other` | `0.0125` |

### `equity_pd_lgd_lgd`

**CRR** — CRR Art. 165
 *((2) supervisory LGD 65% diversified PE / 90% other)*

| Parameter | Value |
|---|---|
| `private_equity_diversified` | `0.65` |
| `other` | `0.90` |

| Name | CRR | Basel 3.1 | Citation |
|---|---|---|---|
| `equity_pd_lgd_maturity` | `5.0` | — | CRR Art. 165 |
| `equity_pd_lgd_no_default_info_scaling` | `1.5` | — | CRR Art. 155(3) |
| `equity_netting_min_hedge_years` | `1.0` | — | CRR Art. 155(2) |
| `equity_transitional` | off | on | CRR Art. 133 / PS1/26, paragraph 4.1 |

### `equity_transitional_std_rw`

**Basel 3.1 only** — PS1/26, paragraph 4.2
 *(transitional standard equity RW (Rules 4.2/4.3))*

Before first step: `0.0`

| Effective date | Value |
|---|---|
| 2027-01-01 | `1.60` |
| 2028-01-01 | `1.90` |
| 2029-01-01 | `2.20` |
| 2030-01-01 | `2.50` |

### `equity_transitional_hr_rw`

**Basel 3.1 only** — PS1/26, paragraph 4.3
 *(transitional higher-risk equity RW (Rules 4.2/4.3))*

Before first step: `0.0`

| Effective date | Value |
|---|---|
| 2027-01-01 | `2.20` |
| 2028-01-01 | `2.80` |
| 2029-01-01 | `3.40` |
| 2030-01-01 | `4.00` |
<!-- END GENERATED: crr-slotting-and-equity-values -->

## Equity treatments

Under CRR equity may be treated under SA or IRB:

- **SA (Art. 133)** — `equity_sa_risk_weights`, keyed by equity type.
- **IRB simple method (Art. 155)** — `equity_irb_simple_risk_weights` with matching
  `equity_irb_simple_el`, distinguishing exchange-traded, diversified private equity, and
  all other holdings.
- **PD/LGD method (Art. 155(3))** — `equity_pd_floors`, `equity_pd_lgd_lgd`,
  `equity_pd_lgd_maturity`, and `equity_pd_lgd_no_default_info_scaling` for the case where
  the firm has no default data.

`equity_irb_approaches_available` is the Feature gating all IRB equity treatment. **Basel
3.1 turns it off** — equity becomes SA-only, phased in via `equity_transitional_std_rw`
and `equity_transitional_hr_rw`.

`equity_netting_min_hedge_years` sets the minimum hedge term for netting short positions
against long equity holdings.

---

> **Full detail:** `docs/specifications/crr/slotting-approach.md`
> **All pack entries:** `docs/data-model/regulatory-tables.md`
