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

## Issue 2: Rename `is_regulated` → `apply_fi_scalar` — COMPLETED

All steps implemented and verified. Summary of changes:

- **Schema**: `is_regulated` renamed to `apply_fi_scalar` in `COUNTERPARTY_SCHEMA` with updated comment
- **Classifier**: `cp_is_regulated` renamed to `cp_apply_fi_scalar`; `requires_fi_scalar` simplified to `is_financial_sector_entity AND cp_apply_fi_scalar` (user-controlled flag replaces complex two-condition inference)
- **`is_large_financial_sector_entity`**: Kept as separate informational column (used in output at line 914), decoupled from `requires_fi_scalar`
- **IRB formulas**: No changes needed — already read `requires_fi_scalar` column correctly
- **Output schema**: `is_regulated` was not in `CALCULATION_OUTPUT_SCHEMA` — no change needed
- **Tests**: All 167 occurrences across 14 test/fixture files renamed with inverted boolean semantics (`is_regulated=True` → `apply_fi_scalar=False`, `is_regulated=False` → `apply_fi_scalar=True`)
- **Benchmark data generator**: Variable and column renamed with inverted logic
- **Results**: 275 acceptance tests pass, 1506 unit tests pass, mypy clean, ruff clean

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
