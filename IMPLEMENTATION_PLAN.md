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

### Implementation Steps — COMPLETED

All core steps implemented and verified. 1925 tests pass, ruff clean on all changed files.

#### Step 1: Schema & Loading — DONE
- [x] Added `MODEL_PERMISSIONS_SCHEMA` to `data/schemas.py`
- [x] Added `model_id: pl.String` to `FACILITY_SCHEMA`, `LOAN_SCHEMA`, `CONTINGENTS_SCHEMA`
- [x] Added `model_permissions` field to `RawDataBundle` and `ResolvedHierarchyBundle`
- [x] Registered `model_permissions` in `DataSourceRegistry` as OPTIONAL at `config/model_permissions`
- [x] Updated `ParquetLoader` and `CSVLoader` to load model_permissions
- [x] Added `model_permissions` to `COLUMN_VALUE_CONSTRAINTS` for validation of `approach` column values
- [x] Added `model_id` to `CALCULATION_OUTPUT_SCHEMA` for audit trail

#### Step 2: Config Changes — DONE
- [x] Kept `IRBPermissions` class as fallback — org-wide permissions work when no model_permissions file present
- [x] Model permissions presence derived from bundle (`model_permissions is not None`)
- [x] Documented precedence in schema and classifier docstrings

#### Step 3: Classifier Refactor — DONE
- [x] Added `_resolve_model_permissions()` method that joins exposures with model_permissions on `model_id`, filters by exposure_class, geography (`str.contains`), and book code exclusion
- [x] Modified `_determine_approach_and_finalize()` with `has_model_permissions` kwarg:
  - Model permissions path: AIRB requires `internal_pd AND lgd`; FIRB requires only `internal_pd`
  - Org-wide path: extracted to `_build_orgwide_permission_exprs()` static method for clarity
- [x] Handles null-typed `model_id` columns via `cast(pl.String)` before join

#### Step 4: Pipeline Integration — DONE
- [x] `model_permissions` passed through `RawDataBundle` → `ResolvedHierarchyBundle` → classifier
- [x] `model_id` flows through hierarchy resolution and to output

#### Step 7: Unit Tests — DONE (10 tests)
- [x] `test_airb_permission_with_pd_and_lgd` — AIRB permission + pd + lgd → AIRB
- [x] `test_airb_permission_without_lgd_falls_to_sa` — AIRB only + no lgd → SA
- [x] `test_firb_permission_without_lgd_uses_firb` — FIRB + no lgd → FIRB
- [x] `test_missing_model_id_defaults_to_sa` — null model_id → SA
- [x] `test_geography_filter_permits` — matching country → AIRB
- [x] `test_geography_filter_excludes` — non-matching country → SA
- [x] `test_book_code_exclusion` — excluded book → SA
- [x] `test_airb_plus_firb_permissions_airb_wins` — both perms + lgd → AIRB
- [x] `test_airb_plus_firb_permissions_firb_when_no_lgd` — both perms + no lgd → FIRB
- [x] `test_no_model_permissions_uses_orgwide` — backward compat test

#### Remaining (lower priority, can be done separately)
- [ ] Step 5: API documentation updates
- [ ] Step 6: Input validation (model_id references, country_codes format)
- [ ] Step 8: Fixture generation for acceptance tests
- [ ] Step 9: User guide documentation and changelog

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
