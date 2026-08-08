# CRR Exposure Classification

**Regulatory Reference:** CRR Articles 112, 147

> Classification maps and thresholds are generated from the rulepack — see the tables
> below. Regenerate with `uv run python scripts/generate_regulatory_tables.py`.

---

## Entity type to exposure class

`entity_type_to_sa_class` and `entity_type_to_irb_class` are the authoritative maps —
and they are **not** the same map. An entity type can land in different classes under SA
and IRB (`crr_non_named_mdb_institution_irb_class` is the clearest example: an unnamed MDB
is an institution for IRB purposes). Read the map for the approach you are calculating.

## Retail qualification and thresholds

`regulatory_thresholds` holds the aggregate retail limit, the QRRE limit and the SME
turnover test. `regulatory_thresholds_fx_derived` records whether the limits are applied
in their native currency or converted — which changes marginal cases.

Breaching a retail threshold reclassifies the exposure as **corporate**.
`retail_art_123a_two_path_applicable` gates the Basel 3.1 Art. 123A two-path test, and
`b31_retail_granularity_limit` the granularity condition.

> ⚠️ Do not quote these limits from memory or from a spec page — they have been wrong in
> this skill before. Read the generated table.

<!-- BEGIN GENERATED: crr-classification-maps -->
### `entity_type_to_sa_class`

**Both regimes** — CRR Art. 112
 *(Table A2 SA exposure-class mapping by entity type)*

Key column: `entity_type`

| Key | Value |
|---|---|
| `sovereign` | `central_govt_central_bank` |
| `central_bank` | `central_govt_central_bank` |
| `central_bank_ecb` | `central_govt_central_bank` |
| `rgla_sovereign` | `rgla` |
| `rgla_institution` | `rgla` |
| `pse_sovereign` | `pse` |
| `pse_institution` | `pse` |
| `mdb` | `mdb` |
| `mdb_named` | `mdb` |
| `international_org` | `international_organisation` |
| `institution` | `institution` |
| `bank` | `institution` |
| `ccp` | `institution` |
| `financial_institution` | `institution` |
| `corporate` | `corporate` |
| `company` | `corporate` |
| `individual` | `retail_other` |
| `retail` | `retail_other` |
| `natural_person` | `retail_other` |
| `specialised_lending` | `corporate` |
| `equity` | `equity` |
| `covered_bond` | `covered_bond` |
| `other_cash` | `other` |
| `other_gold` | `other` |
| `other_items_in_collection` | `other` |
| `other_tangible` | `other` |
| `other_residual_lease` | `other` |
| `high_risk` | `high_risk` |
| `high_risk_venture_capital` | `high_risk` |
| `high_risk_private_equity` | `high_risk` |
| `high_risk_speculative_re` | `high_risk` |

### `entity_type_to_irb_class`

**Both regimes** — CRR Art. 147
 *(IRB exposure-class mapping by entity type)*

Key column: `entity_type`

| Key | Value |
|---|---|
| `sovereign` | `central_govt_central_bank` |
| `central_bank` | `central_govt_central_bank` |
| `central_bank_ecb` | `central_govt_central_bank` |
| `rgla_sovereign` | `central_govt_central_bank` |
| `rgla_institution` | `institution` |
| `pse_sovereign` | `central_govt_central_bank` |
| `pse_institution` | `institution` |
| `mdb` | `central_govt_central_bank` |
| `mdb_named` | `central_govt_central_bank` |
| `international_org` | `central_govt_central_bank` |
| `institution` | `institution` |
| `bank` | `institution` |
| `ccp` | `institution` |
| `financial_institution` | `institution` |
| `corporate` | `corporate` |
| `company` | `corporate` |
| `individual` | `retail_other` |
| `retail` | `retail_other` |
| `natural_person` | `retail_other` |
| `specialised_lending` | `specialised_lending` |
| `equity` | `equity` |
| `covered_bond` | `covered_bond` |
| `other_cash` | `other` |
| `other_gold` | `other` |
| `other_items_in_collection` | `other` |
| `other_tangible` | `other` |
| `other_residual_lease` | `other` |
| `high_risk` | `high_risk` |
| `high_risk_venture_capital` | `high_risk` |
| `high_risk_private_equity` | `high_risk` |
| `high_risk_speculative_re` | `high_risk` |

### `regulatory_thresholds`

**CRR** — CRR Art. 123
 *(EUR monetary thresholds (× EUR/GBP rate → GBP))*

| Parameter | Value |
|---|---|
| `sme_turnover_threshold` | `50000000` |
| `sme_balance_sheet_threshold` | `43000000` |
| `sme_exposure_threshold` | `2500000` |
| `large_corporate_revenue_threshold` | `0` |
| `retail_max_exposure` | `1000000` |
| `qrre_max_limit` | `100000` |
| `lfse_total_assets_threshold` | `70000000000` |

**Basel 3.1** — PS1/26, paragraph 147
 *(PRA-native GBP thresholds (sme_balance_sheet frozen))*

| Parameter | Value |
|---|---|
| `sme_turnover_threshold` | `44000000` |
| `sme_balance_sheet_threshold` | `37547600` |
| `sme_exposure_threshold` | `0` |
| `large_corporate_revenue_threshold` | `440000000` |
| `retail_max_exposure` | `880000` |
| `qrre_max_limit` | `90000` |
| `lfse_total_assets_threshold` | `79000000000` |

| Name | CRR | Basel 3.1 | Citation |
|---|---|---|---|
| `regulatory_thresholds_fx_derived` | on | off | CRR Art. 123 / PS1/26, paragraph 147 |
| `b31_retail_granularity_limit` | — | `0.002` | PS1/26, paragraph 123 |
| `retail_art_123a_two_path_applicable` | off | on | CRR Art. 123 / PS1/26, paragraph 123A |
| `b31_high_risk_class_applicable` | off | on | CRR Art. 128 / PS1/26, paragraph 128 |
| `b31_exposure_subclass_reporting_applies` | off | on | CRR Art. 147 / PS1/26, paragraph 147A |
| `crr_non_named_mdb_institution_irb_class` | on | off | CRR Art. 147 / PS1/26, paragraph 147 |
| `central_bank_uses_sovereign_cqs` | off | on | CRR Art. 114 / PS1/26, paragraph 114 |

### `eu_country_domestic_currency`

**Both regimes** — CRR Art. 114
 *((4)/(7) EU member-state domestic currency 0% CGCB RW)*

Key column: `country_code`

| Key | Value |
|---|---|
| `AT` | `EUR` |
| `BE` | `EUR` |
| `HR` | `EUR` |
| `CY` | `EUR` |
| `EE` | `EUR` |
| `FI` | `EUR` |
| `FR` | `EUR` |
| `DE` | `EUR` |
| `GR` | `EUR` |
| `IE` | `EUR` |
| `IT` | `EUR` |
| `LV` | `EUR` |
| `LT` | `EUR` |
| `LU` | `EUR` |
| `MT` | `EUR` |
| `NL` | `EUR` |
| `PT` | `EUR` |
| `SK` | `EUR` |
| `SI` | `EUR` |
| `ES` | `EUR` |
| `BG` | `BGN` |
| `CZ` | `CZK` |
| `DK` | `DKK` |
| `HU` | `HUF` |
| `PL` | `PLN` |
| `RO` | `RON` |
| `SE` | `SEK` |
<!-- END GENERATED: crr-classification-maps -->

## Counterparty hierarchy

- Child counterparties **inherit internal ratings** from a parent when they lack their own,
  traversed upward until a rated entity is found.
- **External ratings are not inherited.** Each counterparty's own ECAI assessments are
  resolved in place per **CRR Art. 138**: per-agency dedup to the most recent, then one
  assessment → use it; two → the higher risk weight (worse); three or more → the higher
  of the two lowest risk weights (second-best).
- Internal and external ratings are resolved independently.

## Lending group aggregation

- Members are defined via `lending_mappings`, with the parent automatically included.
- Duplicate membership resolves to the first occurrence.
- Residential property exposures are **excluded** from retail aggregation (Art. 123(c)).

## Approach assignment

```
Exposure -> SA / IRB / Slotting / Equity
```

Driven by IRB permissions plus internal rating availability. A counterparty with only
**external** ratings and no internal PD falls to SA even where IRB permission exists.

---

> **Full detail:** `docs/specifications/common/hierarchy-classification.md`
> **All pack entries:** `docs/data-model/regulatory-tables.md`
