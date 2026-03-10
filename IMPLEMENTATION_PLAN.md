# Implementation Plan — Model-Level IRB Permissions & FI Scalar Rename

## Overview

Two changes required:

1. **Model-level IRB permissions**: Replace the current org-wide `IRBPermissions` config with a data-driven model permissions input file. Each model can have different FIRB/AIRB approvals, optionally scoped by geography and excluding specific book codes. The classifier must resolve permissions per-exposure by joining model permissions, then gate approach on both permission AND data availability (internal PD, modelled LGD).
2. **Rename `is_regulated` → `apply_fi_scalar`**: Simplify the counterparty schema by replacing the intermediate `is_regulated` boolean with a direct `apply_fi_scalar` flag. Review and verify the FI scalar is correctly applied everywhere.

---

## Issue 1: Model-Level IRB Permissions

### Current State

- `IRBPermissions` is a frozen dataclass in `contracts/config.py` (line 315) holding a `dict[ExposureClass, set[ApproachType]]`.
- Permissions are set org-wide via factory methods (`sa_only()`, `full_irb()`, `firb_only()`, etc.).
- The classifier (`engine/classifier.py`, line 560-608) reads permissions at Python-side as `bool` literals and inlines them as `pl.lit(True/False)` per exposure class.
- There is **no concept of model_id, book_code filtering, or geography scoping** in the current permission system.
- The approach decision gates only on: (a) exposure class, (b) `internal_pd` not null. There is **no LGD-based gating** for AIRB vs FIRB fallback (except for managed-as-retail-without-LGD → SA).

### Requirements

1. A new **model permissions input file** (`model_permissions.parquet`) defining per-model IRB approvals.
2. Each model permission row specifies:
   - `model_id`: Unique identifier for the IRB model
   - `exposure_class`: Which exposure class this permission covers
   - `approach`: The approved approach (FIRB, AIRB)
   - `country_codes`: Optional list/comma-separated of ISO country codes where this permission applies (null = all geographies)
   - `excluded_book_codes`: Optional list/comma-separated of book codes excluded from this permission (null = no exclusions)
3. **Approach determination logic** (classifier):
   - If a model has AIRB permission but the exposure lacks modelled LGD (`lgd` is null) AND has `internal_pd` → fall back to **SA** (not FIRB, unless FIRB permission also exists for a different model).
   - If a model has FIRB permission and the exposure has `internal_pd` but no modelled LGD → **FIRB** (correct — FIRB uses regulatory LGD floors).
   - If a model has AIRB permission and the exposure has both `internal_pd` and modelled `lgd` → **AIRB**.
   - Geography gate: if permission specifies `country_codes`, only exposures with matching `cp_country_code` qualify.
   - Book code exclusion: if permission specifies `excluded_book_codes`, exposures with matching `book_code` are excluded from that permission.
4. Exposures must be linked to a model via `model_id` on the exposure (facility/loan/contingent schemas) or via a mapping table.

### Design Decisions

**Option A (chosen): `model_id` column on facility/loan/contingent + model permissions input table.**

This is simpler than a separate mapping table and aligns with how banks typically tag exposures to models. Each exposure carries a `model_id` that references the permissions table. Exposures without a `model_id` default to SA.

**Option B (rejected): Separate exposure-to-model mapping table.**

Adds an unnecessary join layer. Banks already know which model an exposure belongs to at the exposure level.

### Schema Changes

#### New: `MODEL_PERMISSIONS_SCHEMA` (in `data/schemas.py`)
```python
MODEL_PERMISSIONS_SCHEMA = {
    "model_id": pl.String,               # Unique model identifier (e.g., "UK_CORP_PD_01")
    "exposure_class": pl.String,          # ExposureClass value this permission covers
    "approach": pl.String,                # "foundation_irb" or "advanced_irb"
    "country_codes": pl.String,           # Comma-separated ISO codes, null = all
    "excluded_book_codes": pl.String,     # Comma-separated book codes to exclude, null = none
}
```

#### Modified: `FACILITY_SCHEMA`, `LOAN_SCHEMA`, `CONTINGENTS_SCHEMA`
Add `model_id: pl.String` (optional — null means SA-only).

#### Modified: `RawDataBundle` (in `contracts/bundles.py`)
Add `model_permissions: pl.LazyFrame | None = None` field.

#### Modified: `DataSourceRegistry` (in `config/data_sources.py`)
Add `model_permissions` as an OPTIONAL input file at `config/model_permissions.parquet`.

### Implementation Steps

#### Step 1: Schema & Loading
- [ ] Add `MODEL_PERMISSIONS_SCHEMA` to `data/schemas.py`
- [ ] Add `model_id: pl.String` to `FACILITY_SCHEMA`, `LOAN_SCHEMA`, `CONTINGENTS_SCHEMA`
- [ ] Add `model_permissions` field to `RawDataBundle`
- [ ] Register `model_permissions` in `DataSourceRegistry` as OPTIONAL
- [ ] Update `ParquetLoader` and `CSVLoader` to load model_permissions
- [ ] Add `model_permissions` to `COLUMN_VALUE_CONSTRAINTS` for validation of `approach` column values
- [ ] Add `model_id` to `CALCULATION_OUTPUT_SCHEMA` for audit trail

#### Step 2: Config Changes
- [ ] Keep `IRBPermissions` class but make it a **fallback** — when no model_permissions file is provided, the existing org-wide permissions still work (backward compatible)
- [ ] Add `has_model_permissions: bool` flag to `CalculationConfig` (or derive from bundle)
- [ ] Document that model_permissions file takes precedence over org-wide `IRBPermissions` when present

#### Step 3: Classifier Refactor
- [ ] Add new method `_resolve_model_permissions()` that:
  1. Joins exposures with model_permissions on `model_id`
  2. Filters by `exposure_class` match
  3. Applies geography filter: `country_codes` is null OR `cp_country_code` is in the comma-separated list
  4. Applies book code exclusion: `excluded_book_codes` is null OR `book_code` NOT in the comma-separated list
  5. Resolves best permission per exposure (AIRB > FIRB priority)
  6. Produces columns: `model_airb_permitted: bool`, `model_firb_permitted: bool`
- [ ] Modify `_determine_approach_and_finalize()` to:
  - When model_permissions are present: use `model_airb_permitted` / `model_firb_permitted` columns (per-row) instead of org-wide `pl.lit(bool)` values
  - Add LGD-based gating: AIRB requires `internal_pd.is_not_null() AND lgd.is_not_null()`; FIRB requires `internal_pd.is_not_null()` only
  - When no model_permissions: retain current org-wide permission behaviour (backward compat)
- [ ] Update FIRB LGD clearing logic to work with per-row permissions

#### Step 4: Pipeline Integration
- [ ] Pass `model_permissions` from `RawDataBundle` through to classifier
- [ ] Update `ResolvedHierarchyBundle` if needed to carry `model_id` through hierarchy resolution
- [ ] Ensure `model_id` flows through to output for traceability

#### Step 5: API Updates
- [ ] Keep existing `irb_approach` on `CalculationRequest` as fallback when no model_permissions file exists
- [ ] Document that when model_permissions.parquet is present in the data directory, it overrides `irb_approach`

#### Step 6: Validation
- [ ] Validate `model_id` references: warn if exposure has `model_id` that doesn't exist in model_permissions
- [ ] Validate `exposure_class` values in model_permissions against `ExposureClass` enum
- [ ] Validate `approach` values against `ApproachType` enum (only FIRB/AIRB valid)
- [ ] Validate `country_codes` format (comma-separated 2-letter codes)

#### Step 7: Tests
- [ ] Unit tests for `_resolve_model_permissions()` with:
  - Basic AIRB permission resolution
  - FIRB fallback when no AIRB permission
  - Geography filtering (UK-only permission)
  - Book code exclusion
  - Missing model_id → SA
  - AIRB permission but no LGD → SA (not FIRB)
  - AIRB permission with LGD → AIRB
  - FIRB permission without LGD → FIRB (uses regulatory floors)
  - Multiple models with different permissions for same exposure class
- [ ] Unit tests for backward compatibility (no model_permissions → org-wide permissions work)
- [ ] Acceptance tests with model_permissions fixtures
- [ ] Update existing classifier tests that use org-wide permissions

#### Step 8: Fixture Generation
- [ ] Add model_permissions fixture generation to `tests/fixtures/generate_all.py`
- [ ] Create sample model_permissions.parquet for test data

#### Step 9: Documentation
- [ ] Update `docs/user-guide/` with model permissions input file format
- [ ] Update changelog
- [ ] Update docstrings on config, classifier, schemas

---

## Issue 2: Rename `is_regulated` → `apply_fi_scalar`

### Current State

- `is_regulated: pl.Boolean` exists in `COUNTERPARTY_SCHEMA` (`schemas.py`, line 153)
- Classifier joins it as `cp_is_regulated` (`classifier.py`, line 234)
- FI scalar flag `requires_fi_scalar` is computed in classifier Phase 3 (`classifier.py`, lines 439-450):
  - `True` when: (FSE AND total_assets >= EUR 70bn) OR (FSE AND `cp_is_regulated == False`)
- `requires_fi_scalar` is consumed by IRB correlation formula (`irb/formulas.py`, lines 461-473) as a 1.25x multiplier
- SA does **not** use FI scalar (correct — SA uses fixed risk weight tables)

### Problem

`is_regulated` is only one part of the FI scalar equation. The other condition (LFSE by total assets) is separate. Renaming to `apply_fi_scalar` makes the intent clearer: the user explicitly flags whether the FI scalar should apply, rather than the system inferring it from `is_regulated` + `total_assets`.

### Design Decision

**Rename `is_regulated` → `apply_fi_scalar`** and change the semantics:
- When `apply_fi_scalar = true` on a counterparty, the 1.25x correlation multiplier applies (if the counterparty is a financial sector entity)
- The classifier will still compute `requires_fi_scalar` but the logic simplifies: `requires_fi_scalar = is_financial_sector_entity AND apply_fi_scalar`
- The user controls when the scalar applies, covering both conditions (unregulated FSE, large FSE) in a single flag

### Implementation Steps

#### Step 1: Schema Change
- [ ] Rename `is_regulated` → `apply_fi_scalar` in `COUNTERPARTY_SCHEMA` (`schemas.py`, line 153)
- [ ] Update comment to: `"apply_fi_scalar": pl.Boolean,  # 1.25x IRB correlation for LFSE/unregulated FSE (CRR Art. 153(2))`

#### Step 2: Classifier Update
- [ ] Rename `cp_is_regulated` → `cp_apply_fi_scalar` in `_add_counterparty_attributes()` (`classifier.py`, line 234)
- [ ] Simplify `requires_fi_scalar` logic in `_classify_sme_and_retail()` (`classifier.py`, lines 439-450):
  ```python
  # Before: complex two-condition check
  # After: direct flag from user
  pl.when(
      (pl.col("is_financial_sector_entity") == True)
      & (pl.col("cp_apply_fi_scalar") == True)
  )
  .then(pl.lit(True))
  .otherwise(pl.lit(False))
  .alias("requires_fi_scalar")
  ```
- [ ] Remove the `is_large_financial_sector_entity` derived column (line 438) — this is now covered by the user's `apply_fi_scalar` flag, OR keep it as a separate informational column but decouple from `requires_fi_scalar`

#### Step 3: Verify FI Scalar Application
- [ ] **IRB correlation** (`irb/formulas.py`, lines 461-473): Already correct — reads `requires_fi_scalar` column, multiplies correlation by 1.25x. No change needed.
- [ ] **IRB parametric formulas** (`irb/formulas.py`, lines 596-603): Already correct — same pattern. No change needed.
- [ ] **IRB namespace defaults** (`irb/namespace.py`): Already defaults `requires_fi_scalar` to False. No change needed.
- [ ] **SA path**: Confirmed no FI scalar in SA (correct per regulation). No change needed.
- [ ] **Output schema**: Check if `is_regulated` appears in `CALCULATION_OUTPUT_SCHEMA` and rename to `apply_fi_scalar`

#### Step 4: Validation Update
- [ ] No value constraint changes needed (boolean field, not categorical)
- [ ] Update any documentation references to `is_regulated`

#### Step 5: Tests
- [ ] Update all test fixtures that set `is_regulated` → `apply_fi_scalar`
- [ ] Verify FI scalar unit tests pass with renamed column
- [ ] Add explicit test: `apply_fi_scalar=True` on non-FSE entity → `requires_fi_scalar=False` (FSE gate still applies)
- [ ] Add explicit test: `apply_fi_scalar=True` on FSE → `requires_fi_scalar=True`
- [ ] Add explicit test: `apply_fi_scalar=False` on LFSE → `requires_fi_scalar=False` (user override)

#### Step 6: Fixture Generation
- [ ] Update `tests/fixtures/generate_all.py` to use `apply_fi_scalar` column name
- [ ] Regenerate all fixture parquet files

#### Step 7: Documentation
- [ ] Update schema documentation
- [ ] Update changelog
- [ ] Update any workbook/notebook references

---

## Implementation Order

1. **Issue 2 first** (rename `is_regulated` → `apply_fi_scalar`) — smaller, self-contained change
2. **Issue 1 second** (model-level permissions) — larger, builds on a clean baseline

## Risk Assessment

| Risk | Mitigation |
|------|-----------|
| Breaking existing tests (rename) | Search-and-replace with test run verification |
| Backward compat (model permissions) | Fallback to org-wide permissions when no file present |
| Performance (per-row permission join) | Single lazy join + filter, no collect barrier needed |
| Complex geography/book_code parsing | Use Polars `str.contains()` for comma-separated lists |
| Multiple models matching same exposure | Priority rule: AIRB > FIRB, first match wins |

## Files Affected

### Issue 1 (Model Permissions)
- `src/rwa_calc/data/schemas.py` — new schema, model_id on exposure schemas
- `src/rwa_calc/contracts/bundles.py` — model_permissions field on RawDataBundle
- `src/rwa_calc/contracts/config.py` — minor: document fallback behaviour
- `src/rwa_calc/config/data_sources.py` — register new input file
- `src/rwa_calc/engine/loader.py` — load model_permissions
- `src/rwa_calc/engine/classifier.py` — major: new permission resolution + approach gating
- `src/rwa_calc/engine/pipeline.py` — pass model_permissions through
- `src/rwa_calc/contracts/validation.py` — validate model_permissions
- `src/rwa_calc/api/models.py` — document precedence
- `src/rwa_calc/api/service.py` — no change needed (model_permissions loaded from data dir)
- `tests/fixtures/generate_all.py` — new fixtures
- `tests/unit/test_classifier.py` — new + updated tests

### Issue 2 (FI Scalar Rename)
- `src/rwa_calc/data/schemas.py` — rename column
- `src/rwa_calc/engine/classifier.py` — rename + simplify logic
- `tests/` — update fixtures and assertions
- `docs/` — update references
