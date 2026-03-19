# Plan: Fix Schema-Documentation Alignment Issues

## Summary

35 discrepancies found between code schemas (`schemas.py`, `enums.py`, `bundles.py`, `config.py`) and documentation (`docs/`). The code (`schemas.py`) is the single source of truth — all fixes target documentation unless a code bug is identified.

---

## Phase 1: Fix Critical Doc Issues (P1) — Most likely to cause runtime confusion

### 1. Phantom exposure classes in intermediate-schemas.md
- **File**: `docs/data-model/intermediate-schemas.md:127-146`
- **Issue**: Lists `RETAIL`, `CIU`, `SECURED_BY_RE` as valid `exposure_class` values — none exist in `ExposureClass` enum (`domain/enums.py`)
- **Fix**: Remove these 3 values

### 2. Wrong approach_applied values in intermediate-schemas.md
- **File**: `docs/data-model/intermediate-schemas.md:147-153`
- **Issue**: Shows `SA`, `FIRB`, `AIRB`, `SLOTTING` (enum names) but actual column values are `standardised`, `foundation_irb`, `advanced_irb`, `slotting` (enum `.value`)
- **Fix**: Update to show actual string values

### 3. sl_type and slotting_category casing
- **File**: `docs/data-model/intermediate-schemas.md:243-257`
- **Issue**: Shows UPPERCASE (`PROJECT_FINANCE`, `STRONG`) but code uses lowercase (`project_finance`, `strong`)
- **Fix**: Change to lowercase

### 4. _id vs _reference naming in data-flow.md
- **File**: `docs/architecture/data-flow.md:422-434`
- **Issue**: Uses `exposure_id`, `counterparty_id`, `facility_id` — code uses `_reference` suffixes everywhere
- **Fix**: Change all `_id` to `_reference`

### 5. Deprecated pl.Utf8 in data-flow.md
- **File**: `docs/architecture/data-flow.md`
- **Issue**: Uses `pl.Utf8` instead of modern `pl.String`
- **Fix**: Replace with `pl.String`

### 6. Invalid "exposure" beneficiary_type in provision docs
- **File**: `docs/data-model/input-schemas.md:498-506`
- **Issue**: Lists `exposure` as valid provision `beneficiary_type` — not in `VALID_BENEFICIARY_TYPES` (`schemas.py:452`)
- **Fix**: Remove `exposure` from docs (code is authoritative)

### 7. Provision type casing
- **File**: `docs/data-model/input-schemas.md:493-496`
- **Issue**: Shows `SCRA`/`GCRA` (uppercase) — code's `VALID_PROVISION_TYPES` uses `scra`/`gcra` (lowercase)
- **Fix**: Show lowercase as canonical, note case-insensitive validation

### 8. Non-existent config params in API examples
- **Files**: `docs/api/index.md:71`, `docs/api/pipeline.md:48`, `docs/architecture/components.md:447`
- **Issue**: Reference `apply_sme_supporting_factor` and `apply_infrastructure_factor` — don't exist on `CalculationConfig`
- **Fix**: Update examples to use `SupportingFactors` config pattern

### 9. Non-existent output_floor_percentage kwarg
- **File**: `docs/api/index.md:78`
- **Issue**: Passes `output_floor_percentage=0.725` to `CalculationConfig.basel_3_1()` — not a valid param
- **Fix**: Remove parameter from example

---

## Phase 2: Add Missing Fields to Docs (P2)

### 10. Loan schema missing netting fields
- **File**: `docs/data-model/input-schemas.md:250-265`
- **Code**: `schemas.py:91-92` has `has_netting_agreement` (Boolean) and `netting_facility_reference` (String)
- **Fix**: Add both fields to Loan schema table

### 11. Output schema missing model_id
- **File**: `docs/data-model/output-schemas.md:84-95`
- **Code**: `schemas.py:773` has `model_id: pl.String`
- **Fix**: Add to identification/lineage section

### 12. Output schema missing internal_pd and external_cqs
- **File**: `docs/data-model/output-schemas.md:99-107`
- **Code**: `schemas.py:782-783` has both fields
- **Fix**: Add to counterparty hierarchy section

### 13. RawDataBundle missing model_permissions
- **File**: `docs/api/contracts.md:34-54`
- **Code**: `bundles.py` has `model_permissions: pl.LazyFrame | None = None`
- **Fix**: Add field to bundle code block

### 14. ResolvedHierarchyBundle missing model_permissions
- **File**: `docs/api/contracts.md:78-87`
- **Code**: `bundles.py` has same field
- **Fix**: Add field to bundle code block

### 15. Missing "equity" entity type
- **File**: `docs/data-model/input-schemas.md` entity type table
- **Code**: `VALID_ENTITY_TYPES` (`schemas.py:404`) includes `"equity"`
- **Fix**: Add `equity` row to entity type table

---

## Phase 3: Fix Wrong Regulatory Values (P3)

### 16. Slotting "good" category wrong RW
- **File**: `docs/data-model/input-schemas.md:675`
- **Issue**: Says "70% RW (same as Strong under CRR)" — actually 90% (≥2.5yr) / 70% (<2.5yr)
- **Fix**: Correct to "90% RW (70% if <2.5yr maturity)"

### 17. Equity central_bank wrong RW
- **File**: `docs/data-model/input-schemas.md:703`
- **Issue**: Shows `central_bank` at 100% RW — should be 0% per enum docstring and regulatory-tables.md
- **Fix**: Change to 0%

### 18. Equity private_equity_diversified wrong RW
- **File**: `docs/data-model/input-schemas.md:709`
- **Issue**: Shows 190% (IRB Simple weight) — SA weight should be 250%
- **Fix**: Change to 250%

### 19. Missing 40% CCF value
- **File**: `docs/data-model/output-schemas.md:164`
- **Issue**: Lists "0%, 20%, 50%, 100%" — missing 40%
- **Fix**: Add 40% to the list

---

## Phase 4: Update Stale Architecture Docs (P4)

### 20-23. data-flow.md stale inline schema copies
- **File**: `docs/architecture/data-flow.md`
- Counterparty schema missing `scra_grade`, `is_investment_grade` (lines 67-78)
- Facility schema missing `is_qrre_transactor` (lines 84-102)
- Ratings schema missing `rating_date`, `is_solicited`, `model_id` (lines 128-137)
- Collateral schema missing 6 fields (lines 142-159)
- **Fix**: Add all missing fields to inline schema copies

### 24. CRMProcessorProtocol wrong method name
- **File**: `docs/architecture/components.md:329-337`
- **Issue**: Shows `process()` method — should be `apply_crm()` / `get_crm_adjusted_bundle()`
- **Fix**: Update method names

### 25. LoaderProtocol wrong signature
- **File**: `docs/architecture/components.md:57-59`
- **Issue**: Shows `load(self, path: Path)` — should be `load(self)` (path in constructor)
- **Fix**: Remove `path` parameter

### 26. LazyFrameResult wrong field name
- **File**: `docs/architecture/design-principles.md:120-125`
- **Issue**: Shows `data` field and `warnings` list — should be `frame`, no separate warnings
- **Fix**: Change `data` to `frame`, remove `warnings` field

### 27. Wrong config attribute references
- **File**: `docs/architecture/components.md:447`
- **Issue**: `config.apply_sme_supporting_factor` — should be `config.supporting_factors.enabled`
- **Fix**: Update config references

### 28. Wrong data type for CQS in index.md
- **File**: `docs/data-model/index.md:110`
- **Issue**: Shows `pl.Int32` for CQS — code uses `pl.Int8`
- **Fix**: Change to `pl.Int8`

### 29-30. Wrong column names in examples
- **Files**: `docs/data-model/index.md:98-124`, `docs/architecture/index.md:101,200-211`
- **Issue**: Use `counterparty_id`, `facility_id`, `annual_turnover`, `parent_id`, `exposure_id`
- **Fix**: Change to `_reference` suffixes and correct field names

---

## Phase 5: Fix Code Inconsistencies (P5)

### 31. guarantor_rw vs guarantor_risk_weight naming
- **Code**: `schemas.py:671` uses `guarantor_rw`; `schemas.py:851` uses `guarantor_risk_weight`
- **Fix**: Standardize to `guarantor_risk_weight` in `CRM_PRE_POST_COLUMNS`

### 32. Missing is_guarantee_beneficial in output schema
- **Code**: `schemas.py:677` has it in `CRM_PRE_POST_COLUMNS` but not in `CALCULATION_OUTPUT_SCHEMA`
- **Fix**: Add to `CALCULATION_OUTPUT_SCHEMA` if needed for output

### 33. Incomplete EQUITY_EXPOSURE_SCHEMA comment
- **Code**: `schemas.py:243` comment lists only 5 equity types; `VALID_EQUITY_TYPES` has 10
- **Fix**: Update comment

### 34. Incomplete SPECIALISED_LENDING_SCHEMA comment
- **Code**: `schemas.py:229` comment omits `hvcre`
- **Fix**: Add `hvcre` to comment

### 35. PropertyType enum vs VALID_PROPERTY_TYPES mismatch
- **Code**: `enums.py:267` has `ADC`; `schemas.py:419` has only `{residential, commercial}`
- **Fix**: Clarify that ADC is flagged via `is_adc` boolean, not `property_type` column

### 36. IRB risk weight formula inconsistency
- **File**: `docs/data-model/output-schemas.md:256`
- **Issue**: Says `12.5 × K` — should be `12.5 × K × scaling_factor`
- **Fix**: Add scaling_factor to formula

---

## Phase 6: Update Changelog

- Add entry to `docs/appendix/changelog.md` documenting all schema-documentation alignment fixes

---

## Files to Modify

| File | Changes |
|------|---------|
| `docs/data-model/input-schemas.md` | Items 6, 7, 10, 15, 16, 17, 18 |
| `docs/data-model/intermediate-schemas.md` | Items 1, 2, 3 |
| `docs/data-model/output-schemas.md` | Items 11, 12, 19, 36 |
| `docs/data-model/index.md` | Items 28, 29 |
| `docs/architecture/data-flow.md` | Items 4, 5, 20-23 |
| `docs/architecture/components.md` | Items 8 (partial), 24, 25, 27 |
| `docs/architecture/design-principles.md` | Item 26 |
| `docs/architecture/index.md` | Item 30 |
| `docs/api/index.md` | Items 8, 9 |
| `docs/api/pipeline.md` | Item 8 (partial) |
| `docs/api/contracts.md` | Items 13, 14 |
| `src/rwa_calc/data/schemas.py` | Items 31, 32, 33, 34 |
| `src/rwa_calc/domain/enums.py` | Item 35 (comment only) |
| `docs/appendix/changelog.md` | Phase 6 |

**Total**: ~14 files, 36 individual fixes across 6 phases.
