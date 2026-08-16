# CRR SA Risk Weights

**Regulatory Reference:** CRR Articles 112-134

> **Every number on this page is generated from the rulepack.** The tables inside
> `<!-- BEGIN/END GENERATED -->` markers are rendered from
> `src/rwa_calc/rulebook/packs/{common,crr}.py` by
> `uv run python scripts/generate_regulatory_tables.py`. Do not hand-edit them, and do
> not restate their values in prose — a wrong value here is a **rulepack finding**, not a
> docs edit.
>
> Each `### entry_name` heading is the literal pack key. Grep it in
> `src/rwa_calc/rulebook/packs/` for the citation, or in `src/rwa_calc/engine/` for the
> code that reads it.

---

## Corporates, Institutions and Covered Bonds (Art. 120-122, 129)

⚠️ **Trap:** the CRR CQS 2 institution weight is *not* the Basel 3.1 ECRA weight for the
same CQS. Carrying the ECRA figure into a CRR scenario is a recurring error — read
`institution_rw_crr` for CRR and `institution_rw_b31_ecra` for Basel 3.1, and never
assume one from the other. CRR Art. 120 Table 3 is the source; no PRA instrument modifies
it.

Unrated institutions under CRR derive their weight from the **sovereign's** CQS
(`institution_rw_sovereign_derived`) — Basel 3.1 replaces this entirely with the SCRA
grade method. Short-term exposures have their own tables under both regimes.

<!-- BEGIN GENERATED: crr-sa-corporate-and-institution -->
### `corporate_risk_weights`

**CRR** — CRR Art. 122
 *(Table 6 corporate RW by CQS)*

Key column: `cqs`; default `1.00`

| Key | Value |
|---|---|
| `1` | `0.20` |
| `2` | `0.50` |
| `3` | `1.00` |
| `4` | `1.00` |
| `5` | `1.50` |
| `6` | `1.50` |
| `0` | `1.00` |

### `corporate_cqs_rw`

**CRR** — CRR Art. 122

Key column: `cqs`; default `1.00`

| Key | Value |
|---|---|
| `1` | `0.20` |
| `2` | `0.50` |

### `crr_short_term_ecai_risk_weights`

**CRR** — CRR Art. 131
 *(Table 7 short-term ECAI RW)*

Key column: `cqs`; default `1.50`

| Key | Value |
|---|---|
| `1` | `0.20` |
| `2` | `0.50` |
| `3` | `1.00` |
| `4` | `1.50` |
| `5` | `1.50` |
| `6` | `1.50` |

| Name | CRR | Basel 3.1 | Citation |
|---|---|---|---|
| `crr_corporate_sme_rw` | `1.00` | — | CRR Art. 122 |

### `institution_rw_crr`

**CRR** — CRR Art. 120
 *(Table 3 institution RW by CQS (CQS2 50%))*

Key column: `cqs`; default `1.00`

| Key | Value |
|---|---|
| `1` | `0.20` |
| `2` | `0.50` |
| `3` | `0.50` |
| `4` | `1.00` |
| `5` | `1.00` |
| `6` | `1.50` |
| `0` | `1.00` |

### `institution_rw_sovereign_derived`

**CRR** — CRR Art. 121
 *(Table 5 sovereign-derived institution RW (unrated))*

Key column: `cqs`; default `1.00`

| Key | Value |
|---|---|
| `1` | `0.20` |
| `2` | `0.50` |
| `3` | `1.00` |
| `4` | `1.00` |
| `5` | `1.00` |
| `6` | `1.50` |

### `institution_short_term_rw_crr`

**CRR** — CRR Art. 120
 *((2) Table 4 short-term institution RW (<=3m))*

Key column: `cqs`; default `0.20`

| Key | Value |
|---|---|
| `1` | `0.20` |
| `2` | `0.20` |
| `3` | `0.20` |
| `4` | `0.50` |
| `5` | `0.50` |
| `6` | `1.50` |
| `0` | `0.20` |

| Name | CRR | Basel 3.1 | Citation |
|---|---|---|---|
| `institution_short_term_unrated_rw_crr` | `0.20` | — | CRR Art. 121 |

### `covered_bond_risk_weights`

**CRR** — CRR Art. 129
 *(Table 6A covered-bond RW by CQS (rated))*

Key column: `cqs`; default `1.00`

| Key | Value |
|---|---|
| `1` | `0.10` |
| `2` | `0.20` |
| `3` | `0.20` |
| `4` | `0.50` |
| `5` | `0.50` |
| `6` | `1.00` |

### `covered_bond_unrated_derivation_crr`

**CRR** — CRR Art. 129
 *((5)(a)-(d) unrated CB derivation from issuer RW)*

Key column: `issuer_institution_rw`; default `1.00`

| Key | Value |
|---|---|
| `0.20` | `0.10` |
| `0.50` | `0.20` |
| `1.00` | `0.50` |
| `1.50` | `1.00` |
<!-- END GENERATED: crr-sa-corporate-and-institution -->

## Sovereign and Public Sector (Art. 114-117)

`cgcb_risk_weights` is the central government / central bank CQS table; sovereigns are
the anchor for several derived treatments, so a change here propagates widely.

The derivation rules matter as much as the tables:

- **PSEs and RGLAs** may be weighted from their **own** rating or derived from their
  sovereign, and the choice is not free — it follows the jurisdiction's treatment.
- `rgla_uk_devolved_rw` and `rgla_uk_local_auth_rw` are **UK-specific** treatments for
  devolved administrations and local authorities.
- `pse_non_equivalent_jurisdiction_rw` catches PSEs in jurisdictions without an
  equivalence determination.
- **MDBs**: `mdb_named_zero_rw` applies to the exhaustively named list in Art. 117(2);
  everything else takes `mdb_unrated_rw` or the CQS table. Check the name is on the list
  before assuming a zero weight.
- `central_bank_uses_sovereign_cqs` gates whether a central bank inherits its sovereign's
  CQS.

<!-- BEGIN GENERATED: crr-sa-public-sector -->
### `cgcb_risk_weights`

**CRR** — CRR Art. 114
 *(central govt / central bank RW by CQS)*

Key column: `cqs`; default `1.00`

| Key | Value |
|---|---|
| `1` | `0.00` |
| `2` | `0.20` |
| `3` | `0.50` |
| `4` | `1.00` |
| `5` | `1.00` |
| `6` | `1.50` |
| `0` | `1.00` |

| Name | CRR | Basel 3.1 | Citation |
|---|---|---|---|
| `central_bank_uses_sovereign_cqs` | off | on | CRR Art. 114 / PS1/26, paragraph 114 |
| `ecb_zero_rw` | `0.00` | `0.00` | CRR Art. 114 |

### `eca_meip_risk_weights`

**Both regimes** — CRR Art. 137
 *((1)-(2) Table 9 ECA/MEIP score -> sovereign RW)*

Key column: `eca_meip_score`; default `1.00`

| Key | Value |
|---|---|
| `0` | `0.00` |
| `1` | `0.00` |
| `2` | `0.20` |
| `3` | `0.50` |
| `4` | `1.00` |
| `5` | `1.00` |
| `6` | `1.00` |
| `7` | `1.50` |

### `pse_risk_weights_own_rating`

**CRR** — CRR Art. 116
 *((2) Table 2A PSE own-rating RW)*

Key column: `cqs`; default `1.00`

| Key | Value |
|---|---|
| `1` | `0.20` |
| `2` | `0.50` |
| `3` | `0.50` |
| `4` | `1.00` |
| `5` | `1.00` |
| `6` | `1.50` |

### `pse_risk_weights_sovereign_derived`

**CRR** — CRR Art. 116
 *((1) Table 2 PSE sovereign-derived RW)*

Key column: `cqs`; default `1.00`

| Key | Value |
|---|---|
| `1` | `0.20` |
| `2` | `0.50` |
| `3` | `1.00` |
| `4` | `1.00` |
| `5` | `1.00` |
| `6` | `1.50` |

| Name | CRR | Basel 3.1 | Citation |
|---|---|---|---|
| `pse_short_term_rw` | `0.20` | `0.20` | CRR Art. 116 |
| `pse_unrated_default_rw` | `1.00` | `1.00` | CRR Art. 116 |
| `pse_non_equivalent_jurisdiction_rw` | `1.00` | `1.00` | CRR Art. 116 |

### `rgla_risk_weights_own_rating`

**CRR** — CRR Art. 115
 *((1)(b) Table 1B RGLA own-rating RW)*

Key column: `cqs`; default `1.00`

| Key | Value |
|---|---|
| `1` | `0.20` |
| `2` | `0.50` |
| `3` | `0.50` |
| `4` | `1.00` |
| `5` | `1.00` |
| `6` | `1.50` |

### `rgla_risk_weights_sovereign_derived`

**CRR** — CRR Art. 115
 *((1)(a) Table 1A RGLA sovereign-derived RW)*

Key column: `cqs`; default `1.00`

| Key | Value |
|---|---|
| `1` | `0.20` |
| `2` | `0.50` |
| `3` | `1.00` |
| `4` | `1.00` |
| `5` | `1.00` |
| `6` | `1.50` |

| Name | CRR | Basel 3.1 | Citation |
|---|---|---|---|
| `rgla_domestic_currency_rw` | `0.20` | `0.20` | CRR Art. 115 |
| `rgla_uk_devolved_rw` | `0.00` | `0.00` | CRR Art. 115 |
| `rgla_uk_local_auth_rw` | `0.20` | `0.20` | CRR Art. 115 |
| `rgla_unrated_default_rw` | `1.00` | `1.00` | CRR Art. 115 |

### `mdb_risk_weights_table_2b`

**CRR** — PS1/26, paragraph 117
 *((1)(a) Table 2B non-named MDB RW by CQS)*

Key column: `cqs`; default `0.50`

| Key | Value |
|---|---|
| `1` | `0.20` |
| `2` | `0.30` |
| `3` | `0.50` |
| `4` | `1.00` |
| `5` | `1.00` |
| `6` | `1.50` |
| `0` | `0.50` |

| Name | CRR | Basel 3.1 | Citation |
|---|---|---|---|
| `mdb_named_zero_rw` | `0.00` | `0.00` | CRR Art. 117 |
| `mdb_unrated_rw` | `0.50` | `0.50` | PS1/26, paragraph 117 |
<!-- END GENERATED: crr-sa-public-sector -->

## Retail, Real Estate, Equity and Other Items (Art. 123-134)

**Residential mortgage (Art. 125)** and **commercial real estate (Art. 126)** are
`FormulaParams` bundles, not flat weights, because CRR splits the exposure at an LTV
threshold:

```
avg_RW = secured_rw x (ltv_threshold / LTV) + residual_rw x ((LTV - ltv_threshold) / LTV)
```

CRE additionally requires a rental-income coverage test alongside the LTV condition
before the preferential weight applies. This is the CRR shape — Basel 3.1 replaces it
with loan-splitting at a different cap against a different residual, so the two are not
interchangeable.

`high_risk_rw` is the Art. 128 "items associated with particularly high risk" class,
which Basel 3.1 retires (`b31_high_risk_class_applicable`).

Equity under CRR is SA or IRB; Basel 3.1 makes it SA-only. See
[slotting-and-equity.md](slotting-and-equity.md) for the IRB simple-method tables.

<!-- BEGIN GENERATED: crr-sa-retail-re-and-other -->
| Name | CRR | Basel 3.1 | Citation |
|---|---|---|---|
| `retail_risk_weight` | `0.75` | `0.75` | CRR Art. 123 |
| `crr_non_regulatory_retail_rw` | `1.00` | — | CRR Art. 123 |

### `residential_mortgage_params`

**CRR** — CRR Art. 125
 *(residential mortgage LTV<=80% 35% / excess 75%)*

| Parameter | Value |
|---|---|
| `ltv_threshold` | `0.80` |
| `rw_low_ltv` | `0.35` |
| `rw_high_ltv` | `0.75` |

### `commercial_re_params`

**CRR** — CRR Art. 126
 *(commercial RE LTV<=50%+income 50% / else 100%)*

| Parameter | Value |
|---|---|
| `ltv_threshold` | `0.50` |
| `rw_low_ltv` | `0.50` |
| `rw_standard` | `1.00` |

| Name | CRR | Basel 3.1 | Citation |
|---|---|---|---|
| `high_risk_rw` | `1.50` | `1.50` | CRR Art. 128 |

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
| `other_items_cash_rw` | `0.00` | `0.00` | CRR Art. 134 |
| `other_items_gold_rw` | `0.00` | `0.00` | CRR Art. 134 |
| `other_items_collection_rw` | `0.20` | `0.20` | CRR Art. 134 |
| `other_items_tangible_rw` | `1.00` | `1.00` | CRR Art. 134 |
| `other_items_default_rw` | `1.00` | `1.00` | CRR Art. 134 |
| `qccp_proprietary_rw` | `0.02` | `0.02` | CRR Art. 306 |
| `qccp_client_cleared_rw` | `0.04` | `0.04` | CRR Art. 306 |
| `io_zero_rw` | `0.00` | `0.00` | CRR Art. 118 |
| `intragroup_zero_rw` | on | on | CRR Art. 113 / PS1/26, paragraph 113 |
| `intragroup_zero_rw_pct` | `0.00` | `0.00` | CRR Art. 113 / PS1/26, paragraph 113 |
<!-- END GENERATED: crr-sa-retail-re-and-other -->

## Defaulted Exposures (Art. 127)

The weight turns on specific credit risk adjustments measured against
`crr_defaulted_provision_threshold`, expressed as a proportion of the exposure **plus the
provision already deducted** — not of the net exposure. Getting that denominator wrong is
the usual cause of a hand-calc mismatch.

<!-- BEGIN GENERATED: crr-sa-defaulted -->
| Name | CRR | Basel 3.1 | Citation |
|---|---|---|---|
| `crr_defaulted_provision_threshold` | `0.20` | — | CRR Art. 127 |
| `crr_defaulted_rw_high_provision` | `1.00` | — | CRR Art. 127 |
| `crr_defaulted_rw_low_provision` | `1.50` | — | CRR Art. 127 |
<!-- END GENERATED: crr-sa-defaulted -->

---

> **Full detail:** `docs/specifications/crr/sa-risk-weights.md`
> **All pack entries:** `docs/data-model/regulatory-tables.md`
