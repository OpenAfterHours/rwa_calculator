# Implementation Plan — Model-Level IRB Permissions & FI Scalar Rename

## Status: All Core Work Complete

Both issues fully implemented and verified. 1925 tests pass.

---

## Issue 1: Model-Level IRB Permissions — COMPLETE

All steps implemented:

- **Schema & Loading**: `MODEL_PERMISSIONS_SCHEMA` in `data/schemas.py`, `model_id` on facility/loan/contingent schemas, `model_permissions` field on `RawDataBundle` and `ResolvedHierarchyBundle`, registered as OPTIONAL in `DataSourceRegistry`
- **Config**: `IRBPermissions` kept as org-wide fallback; model permissions take precedence when present
- **Classifier**: `_resolve_model_permissions()` joins on model_id, filters by exposure_class/geography/book_code; AIRB requires internal_pd + lgd, FIRB requires only internal_pd
- **Pipeline**: `model_permissions` flows through all stages; `model_id` in output for audit trail
- **Validation**: model_permissions in both bundle validators; approach column validated via `COLUMN_VALUE_CONSTRAINTS`
- **Unit Tests**: 10 tests covering AIRB/FIRB permissions, geography filtering, book code exclusion, backward compat
- **API Documentation**: `CalculationRequest` docstring documents precedence; `RWAService` explains dual permission modes; `_create_config` explains fallback
- **Fixture Generation**: `model_permissions/model_permissions.py` generates 7 permission records (corporate FIRB/AIRB, institution FIRB, retail AIRB x3, German FIRB); `model_id` field added to Facility/Loan/Contingent dataclasses; integrity check for model_id references in `generate_all.py`
- **Docs**: Changelog entries, input-schemas.md updated, classification docs updated

## Issue 2: Rename `is_regulated` → `apply_fi_scalar` — COMPLETE

All steps implemented (schema, classifier, tests, docs, benchmark generator).

---

## Spec Fixes Applied

- **FI scalar terminology**: A-IRB spec corrected from "capital multiplier" to "correlation multiplier" (matching F-IRB and framework-differences specs)
- **FI scalar threshold**: Framework-differences spec clarified with separate CRR (EUR 70bn) and BCBS/Basel 3.1 (USD 100bn) thresholds
- **Stale `is_regulated` references**: Fixed in 4 doc files

## Known Issues / Future Work

- **Referential integrity validation**: Cross-table model_id validation (exposures → model_permissions) not yet in production validators — only in fixture integrity check. Deferred as low priority since invalid model_ids simply fall back to SA.
- **Pre-existing fixture integrity errors**: Collateral, guarantee, and provision fixtures reference test loans not in the loans fixture (e.g., `LOAN_COLL_TEST_CORP_001`). These are CRM test-specific references that exist in test conftest but not in the fixture generator.
- **Spec version staleness**: `overview.md` says v0.1.29, `milestones.md` says v0.1.28 — both significantly behind current version.
- **Missing spec coverage**: No dedicated equity SA risk weight table in specs; SCRA grade determination logic not documented; ADC/income-producing RE classification criteria not documented.
- **fastexcel vs xlsxwriter**: overview.md lists fastexcel for Excel export; output-reporting.md says xlsxwriter. Both may be used but specs are inconsistent.
