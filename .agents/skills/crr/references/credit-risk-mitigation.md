# CRR Credit Risk Mitigation

**Regulatory Reference:** CRR Articles 192-241

> Values are generated from the rulepack — see the table below. Regenerate with
> `uv run python scripts/generate_regulatory_tables.py`.

---

## Haircuts, ratios and thresholds

`collateral_haircuts` is a decision table keyed by collateral type, CQS **and** residual
maturity band — read the whole key. `fx_haircut` is the Art. 233 currency-mismatch
haircut and is unchanged under Basel 3.1; `zero_haircut_max_sovereign_cqs` bounds which
sovereign collateral qualifies for a zero haircut.

`overcollateralisation_ratios` (Art. 230) and `min_collateralisation_thresholds` are two
independent gates:

```
effectively_secured = adjusted_collateral_value / overcollateralisation_ratio
```

If the minimum coverage threshold is not met, the **non-financial** collateral value is
zeroed entirely rather than reduced.

<!-- BEGIN GENERATED: crr-crm-values -->
### `collateral_haircuts`

**CRR** — CRR Art. 224
 *(FCCM supervisory haircuts Table 1 (3 maturity bands))*

Keys: `collateral_type` , `cqs` , `maturity_band` , `is_main_index`

| Keys | Value |
|---|---|
| `cash`, `None`, `None`, `None` | `0.00` |
| `gold`, `None`, `None`, `None` | `0.15` |
| `govt_bond`, `1`, `0_1y`, `None` | `0.005` |
| `govt_bond`, `1`, `1_5y`, `None` | `0.02` |
| `govt_bond`, `1`, `5y_plus`, `None` | `0.04` |
| `govt_bond`, `2`, `0_1y`, `None` | `0.01` |
| `govt_bond`, `2`, `1_5y`, `None` | `0.03` |
| `govt_bond`, `2`, `5y_plus`, `None` | `0.06` |
| `govt_bond`, `3`, `0_1y`, `None` | `0.01` |
| `govt_bond`, `3`, `1_5y`, `None` | `0.03` |
| `govt_bond`, `3`, `5y_plus`, `None` | `0.06` |
| `govt_bond`, `4`, `0_1y`, `None` | `0.15` |
| `govt_bond`, `4`, `1_5y`, `None` | `0.15` |
| `govt_bond`, `4`, `5y_plus`, `None` | `0.15` |
| `corp_bond`, `1`, `0_1y`, `None` | `0.01` |
| `corp_bond`, `1`, `1_5y`, `None` | `0.04` |
| `corp_bond`, `1`, `5y_plus`, `None` | `0.08` |
| `corp_bond`, `2`, `0_1y`, `None` | `0.02` |
| `corp_bond`, `2`, `1_5y`, `None` | `0.06` |
| `corp_bond`, `2`, `5y_plus`, `None` | `0.12` |
| `corp_bond`, `3`, `0_1y`, `None` | `0.02` |
| `corp_bond`, `3`, `1_5y`, `None` | `0.06` |
| `corp_bond`, `3`, `5y_plus`, `None` | `0.12` |
| `securitisation`, `1`, `0_1y`, `None` | `0.02` |
| `securitisation`, `1`, `1_5y`, `None` | `0.08` |
| `securitisation`, `1`, `5y_plus`, `None` | `0.16` |
| `securitisation`, `2`, `0_1y`, `None` | `0.04` |
| `securitisation`, `2`, `1_5y`, `None` | `0.12` |
| `securitisation`, `2`, `5y_plus`, `None` | `0.24` |
| `securitisation`, `3`, `0_1y`, `None` | `0.04` |
| `securitisation`, `3`, `1_5y`, `None` | `0.12` |
| `securitisation`, `3`, `5y_plus`, `None` | `0.24` |
| `equity`, `None`, `None`, `True` | `0.15` |
| `equity`, `None`, `None`, `False` | `0.25` |
| `real_estate`, `None`, `None`, `None` | `0.00` |
| `receivables`, `None`, `None`, `None` | `0` |
| `other_physical`, `None`, `None`, `None` | `0.40` |

**Basel 3.1** — PS1/26, paragraph 224
 *(Basel 3.1 FCCM supervisory haircuts (5 maturity bands))*

Keys: `collateral_type` , `cqs` , `maturity_band` , `is_main_index`

| Keys | Value |
|---|---|
| `cash`, `None`, `None`, `None` | `0.00` |
| `gold`, `None`, `None`, `None` | `0.20` |
| `govt_bond`, `1`, `0_1y`, `None` | `0.005` |
| `govt_bond`, `1`, `1_3y`, `None` | `0.02` |
| `govt_bond`, `1`, `3_5y`, `None` | `0.02` |
| `govt_bond`, `1`, `5_10y`, `None` | `0.04` |
| `govt_bond`, `1`, `10y_plus`, `None` | `0.04` |
| `govt_bond`, `2`, `0_1y`, `None` | `0.01` |
| `govt_bond`, `2`, `1_3y`, `None` | `0.03` |
| `govt_bond`, `2`, `3_5y`, `None` | `0.03` |
| `govt_bond`, `2`, `5_10y`, `None` | `0.06` |
| `govt_bond`, `2`, `10y_plus`, `None` | `0.06` |
| `govt_bond`, `3`, `0_1y`, `None` | `0.01` |
| `govt_bond`, `3`, `1_3y`, `None` | `0.03` |
| `govt_bond`, `3`, `3_5y`, `None` | `0.03` |
| `govt_bond`, `3`, `5_10y`, `None` | `0.06` |
| `govt_bond`, `3`, `10y_plus`, `None` | `0.06` |
| `govt_bond`, `4`, `0_1y`, `None` | `0.15` |
| `govt_bond`, `4`, `1_3y`, `None` | `0.15` |
| `govt_bond`, `4`, `3_5y`, `None` | `0.15` |
| `govt_bond`, `4`, `5_10y`, `None` | `0.15` |
| `govt_bond`, `4`, `10y_plus`, `None` | `0.15` |
| `corp_bond`, `1`, `0_1y`, `None` | `0.01` |
| `corp_bond`, `1`, `1_3y`, `None` | `0.03` |
| `corp_bond`, `1`, `3_5y`, `None` | `0.04` |
| `corp_bond`, `1`, `5_10y`, `None` | `0.06` |
| `corp_bond`, `1`, `10y_plus`, `None` | `0.12` |
| `corp_bond`, `2`, `0_1y`, `None` | `0.02` |
| `corp_bond`, `2`, `1_3y`, `None` | `0.04` |
| `corp_bond`, `2`, `3_5y`, `None` | `0.06` |
| `corp_bond`, `2`, `5_10y`, `None` | `0.12` |
| `corp_bond`, `2`, `10y_plus`, `None` | `0.20` |
| `corp_bond`, `3`, `0_1y`, `None` | `0.02` |
| `corp_bond`, `3`, `1_3y`, `None` | `0.04` |
| `corp_bond`, `3`, `3_5y`, `None` | `0.06` |
| `corp_bond`, `3`, `5_10y`, `None` | `0.12` |
| `corp_bond`, `3`, `10y_plus`, `None` | `0.20` |
| `securitisation`, `1`, `0_1y`, `None` | `0.02` |
| `securitisation`, `1`, `1_3y`, `None` | `0.08` |
| `securitisation`, `1`, `3_5y`, `None` | `0.08` |
| `securitisation`, `1`, `5_10y`, `None` | `0.16` |
| `securitisation`, `1`, `10y_plus`, `None` | `0.16` |
| `securitisation`, `2`, `0_1y`, `None` | `0.04` |
| `securitisation`, `2`, `1_3y`, `None` | `0.12` |
| `securitisation`, `2`, `3_5y`, `None` | `0.12` |
| `securitisation`, `2`, `5_10y`, `None` | `0.24` |
| `securitisation`, `2`, `10y_plus`, `None` | `0.24` |
| `securitisation`, `3`, `0_1y`, `None` | `0.04` |
| `securitisation`, `3`, `1_3y`, `None` | `0.12` |
| `securitisation`, `3`, `3_5y`, `None` | `0.12` |
| `securitisation`, `3`, `5_10y`, `None` | `0.24` |
| `securitisation`, `3`, `10y_plus`, `None` | `0.24` |
| `equity`, `None`, `None`, `True` | `0.20` |
| `equity`, `None`, `None`, `False` | `0.30` |
| `real_estate`, `None`, `None`, `None` | `0.40` |
| `receivables`, `None`, `None`, `None` | `0.40` |
| `other_physical`, `None`, `None`, `None` | `0.40` |

| Name | CRR | Basel 3.1 | Citation |
|---|---|---|---|
| `fx_haircut` | `0.08` | `0.08` | CRR Art. 224 |
| `zero_haircut_max_sovereign_cqs` | `1` | `1` | CRR Art. 227 |
| `restructuring_exclusion_haircut` | `0.40` | `0.40` | CRR Art. 233(2) |
| `liquidation_period_repo` | `5` | `5` | CRR Art. 224 |
| `liquidation_period_capital_market` | `10` | `10` | CRR Art. 224 |
| `liquidation_period_secured_lending` | `20` | `20` | CRR Art. 224 |

### `overcollateralisation_ratios`

**Both regimes** — CRR Art. 230
 *(Table 5 overcollateralisation divisors)*

Key column: `collateral_category`; default `1.0`

| Key | Value |
|---|---|
| `financial` | `1.0` |
| `receivables` | `1.25` |
| `real_estate` | `1.40` |
| `other_physical` | `1.40` |
| `life_insurance` | `1.0` |

### `min_collateralisation_thresholds`

**Both regimes** — CRR Art. 230
 *(minimum collateralisation thresholds)*

Key column: `collateral_category`; default `0.0`

| Key | Value |
|---|---|
| `financial` | `0.0` |
| `receivables` | `0.0` |
| `real_estate` | `0.30` |
| `other_physical` | `0.30` |
| `life_insurance` | `0.0` |

### `life_insurance_secured_rw_map`

**Both regimes** — CRR Art. 232
 *((3) life-insurance secured-portion RW map)*

Input column: `insurer_risk_weight` (band applies when input <= bound)

| Upper bound | Value |
|---|---|
| `0.20` | `0.20` |
| `0.50` | `0.35` |
| `1.35` | `0.70` |
| — | `1.50` |

| Name | CRR | Basel 3.1 | Citation |
|---|---|---|---|
| `fcsm_rw_floor` | `0.20` | `0.20` | CRR Art. 222(1) |
| `fcsm_equity_collateral_rw` | `1.00` | `2.50` | CRR Art. 222(3) / PS1/26, paragraph 222 |
| `fcsm_sovereign_bond_discount` | `0.20` | `0.20` | CRR Art. 222(4)(b) |
| `fcsm_sft_cmp_floor` | `0.00` | `0.00` | CRR Art. 222(4)(a) |
| `fcsm_sft_non_cmp_floor` | `0.10` | `0.10` | CRR Art. 222(4)(b) |
<!-- END GENERATED: crr-crm-values -->

## Maturity Mismatch Adjustment (Art. 238)

Where collateral matures before the exposure:

```
adjustment_factor = (t - 0.25) / (T - 0.25)
```

t is the residual collateral maturity and T the residual exposure maturity capped at the
Art. 238 bound. Two edge rules:

- Collateral maturity at or beyond exposure maturity: no adjustment.
- Collateral maturity under three months: protection is **disallowed**, not reduced.

## Multi-Level Collateral Allocation

Collateral is pledged at three levels and consumed in order:

1. **Exposure level** — pledged directly against one exposure
2. **Facility level** — shared pro-rata across the facility's exposures
3. **Counterparty level** — shared pro-rata across all the counterparty's exposures

Financial and non-financial collateral are tracked separately throughout.

## Guarantee Substitution (Art. 213-217)

The guarantor's risk weight replaces the borrower's for the guaranteed portion, but only
where the substitution is **beneficial** (guarantor RW below borrower RW).

```
RW_blended = (unguaranteed x borrower_RW + guaranteed x guarantor_RW) / EAD
```

Two scope traps:

- **Art. 201 eligible guarantors is an exhaustive list with no retail limb.** A retail
  guarantor is not eligible. Check the guarantor's entity type before designing a
  substitution scenario.
- **Art. 199 collateral eligibility is IRB-only.** SA property collateral is recognised
  through the real-estate risk weight, not through the CRM chain — routing it through
  both double-counts.

---

> **Full detail:** `docs/specifications/crr/credit-risk-mitigation.md`
> **All pack entries:** `docs/data-model/regulatory-tables.md`
