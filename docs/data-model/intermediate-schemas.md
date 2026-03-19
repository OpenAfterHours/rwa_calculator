# Intermediate Schemas

This page documents the schemas for intermediate data structures produced during pipeline
execution. Each schema represents the state of exposure data after a specific pipeline stage.

Why these schemas matter: Column names accumulate through the pipeline — each stage adds
columns to the exposure records rather than replacing them. Understanding what each stage
contributes is essential for debugging calculation results and writing correct joins.

> **Source of truth**: All schemas are defined in `src/rwa_calc/data/schemas.py`.
> Column names throughout the codebase use `_reference` suffixes (never `_id`).

## Raw Exposure Schema

After the loader unifies facilities, loans, and contingents into a single exposure stream.
Each record gets an `exposure_reference` synthesised from the original entity key:

- Loans: `loan_reference` → `exposure_reference`
- Contingents: `contingent_reference` → `exposure_reference`
- Facility undrawn: `facility_reference` + `"_UNDRAWN"` → `exposure_reference`

**Source**: `RAW_EXPOSURE_SCHEMA` in `data/schemas.py`, `HierarchyResolver._unify_exposures()` in `engine/hierarchy.py`

| Column | Type | Description |
|--------|------|-------------|
| `exposure_reference` | `String` | Unique identifier (synthesised from loan/contingent/facility reference) |
| `exposure_type` | `String` | `"loan"`, `"contingent"`, or `"facility_undrawn"` |
| `product_type` | `String` | Product classification |
| `book_code` | `String` | Portfolio/book classification |
| `counterparty_reference` | `String` | Foreign key to counterparty |
| `value_date` | `Date` | Origination date |
| `maturity_date` | `Date` | Contractual maturity date |
| `currency` | `String` | Exposure currency |
| `drawn_amount` | `Float64` | Drawn balance (0 for facility undrawn records) |
| `interest` | `Float64` | Accrued interest (adds to on-balance-sheet EAD) |
| `undrawn_amount` | `Float64` | Undrawn commitment (limit − drawn for facilities) |
| `nominal_amount` | `Float64` | Total nominal (for contingents) |
| `lgd` | `Float64` | Internal LGD estimate (A-IRB modelled, if available) |
| `beel` | `Float64` | Best estimate expected loss |
| `seniority` | `String` | `"senior"` or `"subordinated"` — affects F-IRB supervisory LGD |
| `risk_type` | `String` | `"FR"`, `"MR"`, `"MLR"`, `"LR"` — determines CCF (CRR Art. 111) |
| `ccf_modelled` | `Float64` | A-IRB modelled CCF (0.0–1.5) |
| `is_short_term_trade_lc` | `Boolean` | Short-term LC for goods movement — 20% CCF under F-IRB |
| `is_buy_to_let` | `Boolean` | BTL property lending — excluded from SME supporting factor |
| `original_currency` | `String` | Currency before FX conversion (audit trail) |
| `original_amount` | `Float64` | Amount before FX conversion (audit trail) |
| `fx_rate_applied` | `Float64` | Rate used for conversion (null if no conversion) |

## Resolved Hierarchy Schema

After hierarchy resolution, exposures gain counterparty hierarchy, facility hierarchy,
rating inheritance, and lending group columns. This is the most column-rich intermediate
stage, adding 14+ columns to each exposure record.

**Source**: `RESOLVED_HIERARCHY_SCHEMA` in `data/schemas.py`, `HierarchyResolver.resolve()` in `engine/hierarchy.py`

### Counterparty hierarchy columns

| Column | Type | Description |
|--------|------|-------------|
| `counterparty_has_parent` | `Boolean` | Whether counterparty is part of an org hierarchy |
| `parent_counterparty_reference` | `String` | Immediate parent in org structure |
| `ultimate_parent_reference` | `String` | Top-level parent (for group-level analysis) |
| `counterparty_hierarchy_depth` | `Int8` | Levels from ultimate parent (0 = top) |

### Rating inheritance columns

| Column | Type | Description |
|--------|------|-------------|
| `rating_inherited` | `Boolean` | Whether rating came from a parent counterparty |
| `rating_source_counterparty` | `String` | Counterparty whose rating was used |
| `rating_inheritance_reason` | `String` | `"own_rating"`, `"parent_rating"`, `"group_rating"`, `"unrated"` |

### Facility hierarchy columns

| Column | Type | Description |
|--------|------|-------------|
| `exposure_has_parent` | `Boolean` | Whether exposure is child of a facility |
| `parent_facility_reference` | `String` | Parent facility reference |
| `root_facility_reference` | `String` | Top-level facility in hierarchy |
| `facility_hierarchy_depth` | `Int8` | Levels from root facility (0 = top) |

### Lending group columns

| Column | Type | Description |
|--------|------|-------------|
| `lending_group_reference` | `String` | Lending group parent if applicable |
| `lending_group_total_exposure` | `Float64` | Aggregated exposure across lending group |
| `lending_group_adjusted_exposure` | `Float64` | Excludes residential RE for retail threshold test |
| `residential_collateral_value` | `Float64` | Residential RE collateral securing this exposure |
| `exposure_for_retail_threshold` | `Float64` | This exposure's contribution (excl. residential RE) |

## Classified Exposure Schema

After classification, each exposure has a regulatory exposure class, approach assignment,
and entity flags. The classifier joins counterparty attributes (prefixed `cp_*`) and derives
classification in five phases.

**Source**: `CLASSIFIED_EXPOSURE_SCHEMA` in `data/schemas.py`, `ExposureClassifier.classify()` in `engine/classifier.py`

| Column | Type | Description |
|--------|------|-------------|
| `exposure_reference` | `String` | Unique exposure identifier |
| `exposure_type` | `String` | `"loan"`, `"contingent"`, or `"facility_undrawn"` |
| `counterparty_reference` | `String` | Foreign key to counterparty |
| `currency` | `String` | Exposure currency |
| `drawn_amount` | `Float64` | Drawn balance |
| `interest` | `Float64` | Accrued interest |
| `undrawn_amount` | `Float64` | Undrawn commitment |
| `seniority` | `String` | `"senior"` or `"subordinated"` |
| `risk_type` | `String` | CCF category (`"FR"`, `"MR"`, `"MLR"`, `"LR"`) |
| `ccf_modelled` | `Float64` | A-IRB modelled CCF |
| `is_short_term_trade_lc` | `Boolean` | Short-term LC for goods movement |
| `is_buy_to_let` | `Boolean` | BTL property lending flag |
| `exposure_class` | `String` | Regulatory exposure class (see values below) |
| `exposure_class_reason` | `String` | Explanation of classification decision |
| `approach_permitted` | `String` | `"standardised"`, `"foundation_irb"`, `"advanced_irb"` based on IRB permissions |
| `approach_applied` | `String` | Actual approach used for this exposure |
| `approach_selection_reason` | `String` | Why this approach was selected |
| `cqs` | `Int8` | Credit Quality Step (1–6, 0 for unrated) |
| `pd` | `Float64` | Probability of default (for IRB exposures) |
| `rating_agency` | `String` | Source of external rating |
| `rating_value` | `String` | Original rating value |
| `is_sme` | `Boolean` | SME classification flag |
| `is_retail_eligible` | `Boolean` | Meets retail criteria |

**Valid `exposure_class` values:**

- `central_govt_central_bank`
- `institution`
- `corporate`
- `corporate_sme`
- `retail_mortgage`
- `retail_qrre`
- `retail_other`
- `specialised_lending`
- `equity`
- `defaulted`
- `pse`
- `mdb`
- `rgla`
- `other`

**Valid `approach_applied` values:**

- `standardised` — Standardised Approach
- `foundation_irb` — Foundation IRB
- `advanced_irb` — Advanced IRB
- `slotting` — Slotting Approach

## CRM Adjusted Schema

After CRM processing, exposures include the full EAD waterfall: provisions → CCF →
collateral → guarantees → final EAD. The CRM processor also determines LGD values
(supervisory for F-IRB, modelled for A-IRB with optional floors).

**Source**: `CRM_ADJUSTED_SCHEMA` in `data/schemas.py`, `CRMProcessor.apply_crm()` in `engine/crm/processor.py`

### EAD calculation columns

| Column | Type | Description |
|--------|------|-------------|
| `drawn_amount` | `Float64` | Original drawn balance |
| `interest` | `Float64` | Accrued interest |
| `undrawn_amount` | `Float64` | Undrawn commitment |
| `ccf_applied` | `Float64` | Credit conversion factor applied |
| `converted_undrawn` | `Float64` | `undrawn_amount × ccf_applied` |
| `gross_ead` | `Float64` | `drawn_amount + interest + converted_undrawn` |

### Collateral impact columns

| Column | Type | Description |
|--------|------|-------------|
| `collateral_gross_value` | `Float64` | Total market value before haircuts |
| `collateral_haircut_applied` | `Float64` | Weighted average haircut percentage |
| `fx_haircut_applied` | `Float64` | FX mismatch haircut (8% or 0%) |
| `collateral_adjusted_value` | `Float64` | Net collateral value after haircuts |
| `ead_after_collateral` | `Float64` | EAD after collateral deduction |

### Guarantee impact columns

| Column | Type | Description |
|--------|------|-------------|
| `guarantee_coverage_pct` | `Float64` | Percentage of exposure guaranteed |
| `guaranteed_amount` | `Float64` | Amount covered by guarantee |
| `ead_after_guarantee` | `Float64` | Portion not guaranteed |

### Final EAD and LGD columns

| Column | Type | Description |
|--------|------|-------------|
| `final_ead` | `Float64` | Final EAD for RWA calculation |
| `lgd_type` | `String` | `"supervisory"` (F-IRB) or `"modelled"` (A-IRB) |
| `lgd_value` | `Float64` | LGD for calculation |
| `lgd_floor` | `Float64` | Applicable LGD floor (Basel 3.1 only) |
| `lgd_floored` | `Float64` | `max(lgd_value, lgd_floor)` |

### Pre/Post CRM columns (regulatory reporting)

These columns support COREP dual-view reporting — pre-CRM shows the original borrower
exposure, post-CRM shows the split between borrower (unguaranteed) and guarantor (guaranteed).

**Source**: `CRM_PRE_POST_COLUMNS` in `data/schemas.py`

| Column | Type | Description |
|--------|------|-------------|
| `pre_crm_counterparty_reference` | `String` | Original borrower reference |
| `pre_crm_exposure_class` | `String` | Original exposure class before substitution |
| `post_crm_counterparty_guaranteed` | `String` | Guarantor reference for guaranteed exposures |
| `post_crm_exposure_class_guaranteed` | `String` | Derived from guarantor's entity_type |
| `is_guaranteed` | `Boolean` | Whether exposure has effective guarantee |
| `guaranteed_portion` | `Float64` | EAD covered by guarantee |
| `unguaranteed_portion` | `Float64` | EAD not covered by guarantee |
| `guarantor_reference` | `String` | Foreign key to guarantor counterparty |
| `pre_crm_risk_weight` | `Float64` | Borrower's RW before guarantee substitution |
| `guarantor_rw` | `Float64` | Guarantor's RW (SA lookup or IRB-calculated) |
| `guarantee_benefit_rw` | `Float64` | RW reduction from guarantee |
| `rwa_irb_original` | `Float64` | IRB RWA before guarantee substitution |
| `risk_weight_irb_original` | `Float64` | IRB RW before guarantee substitution |
| `guarantee_method_used` | `String` | `"SA_RW_SUBSTITUTION"`, `"PD_SUBSTITUTION"`, or `"NO_GUARANTEE"` |
| `is_guarantee_beneficial` | `Boolean` | Whether guarantee reduces RWA |
| `guarantee_status` | `String` | Detailed status (incl. non-beneficial flag) |

## Specialised Lending Schema

For slotting approach exposures. The slotting category and type are determined during
classification based on counterparty and product attributes.

**Source**: `SLOTTING_RESULT_SCHEMA` in `data/schemas.py`, `SlottingCalculator` in `engine/slotting/`

| Column | Type | Description |
|--------|------|-------------|
| `exposure_reference` | `String` | Exposure identifier |
| ... | ... | (all CRM adjusted columns carried forward) |
| `sl_type` | `String` | Type of specialised lending (see values below) |
| `slotting_category` | `String` | Supervisory category (see values below) |
| `is_hvcre` | `Boolean` | High Volatility CRE indicator |
| `remaining_maturity_years` | `Float64` | Remaining maturity for CRR maturity-band differentiation |

**Valid `sl_type` values:**

- `project_finance`
- `object_finance`
- `commodities_finance`
- `ipre` — Income-producing real estate
- `hvcre` — High volatility CRE

**Valid `slotting_category` values:**

- `strong`
- `good`
- `satisfactory`
- `weak`
- `default`

## Transformation Examples

### Hierarchy Resolution

```python
import polars as pl

# Input: counterparties with parent relationships
counterparties = pl.DataFrame({
    "counterparty_reference": ["C001", "C002"],
    "entity_type": ["corporate", "corporate"],
})

# Org mappings define the hierarchy
org_mappings = pl.DataFrame({
    "parent_counterparty_reference": ["C001"],
    "child_counterparty_reference": ["C002"],
})

# After resolution, hierarchy columns are added to exposures
resolved_exposure = {
    "exposure_reference": "L001",
    "counterparty_reference": "C002",
    "counterparty_has_parent": True,
    "parent_counterparty_reference": "C001",
    "ultimate_parent_reference": "C001",
    "counterparty_hierarchy_depth": 1,
    "rating_inherited": True,
    "rating_source_counterparty": "C001",
    "rating_inheritance_reason": "parent_rating",
}
```

### Classification

```python
# After classification, exposures get regulatory class and approach
classified = {
    "exposure_reference": "L001",
    "counterparty_reference": "C002",
    "exposure_class": "CORPORATE_SME",  # Turnover < EUR 50m
    "exposure_class_reason": "corporate with turnover < 50m EUR",
    "approach_applied": "SA",
    "approach_permitted": "SA",
    "is_sme": True,
}
```

### CRM Application

```python
# After CRM, exposures have the full EAD waterfall
crm_adjusted = {
    "exposure_reference": "L001",
    "drawn_amount": 10_000_000,
    "ccf_applied": 0.5,
    "converted_undrawn": 2_500_000,
    "gross_ead": 12_500_000,
    "collateral_gross_value": 8_000_000,
    "collateral_haircut_applied": 0.02,  # 2% for 1-5yr govt bond
    "collateral_adjusted_value": 7_840_000,
    "ead_after_collateral": 4_660_000,
    "final_ead": 4_660_000,
}
```

## Next Steps

- [Output Schemas](output-schemas.md)
- [Regulatory Tables](regulatory-tables.md)
- [Pipeline Architecture](../architecture/pipeline.md)
