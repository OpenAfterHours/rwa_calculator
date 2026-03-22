# Fix: Specialised Lending Maturity Calculation in Slotting RWA

## Problem

The `is_short_maturity` flag (remaining maturity < 2.5 years) is **never calculated from exposure dates**. In `namespace.py:126`, `prepare_columns()` defaults it to `False` when the column is missing. This means:

- **All exposures are treated as >= 2.5yr maturity** regardless of their actual `maturity_date`
- Strong category exposures with <2.5yr maturity get 70% RW instead of the correct 50% (CRR non-HVCRE)
- Good category exposures with <2.5yr maturity get 90% RW instead of the correct 70%
- HVCRE Strong: 95% instead of 70%; HVCRE Good: 120% instead of 95%
- This is a **regulatory compliance gap** under CRR Art. 153(5)

The risk weight tables and lookup logic are correct — only the maturity derivation step is missing.

## Root Cause

`SlottingLazyFrame.prepare_columns()` (namespace.py:117-147) does not compute `is_short_maturity` from `maturity_date` and `config.reporting_date`. It just defaults to `lit(False)`. Unlike the IRB namespace (irb/namespace.py:262-276) which correctly derives maturity from `maturity_date` using `_exact_fractional_years_expr()`, the slotting namespace skips this step.

## Plan

### Step 1: Add maturity calculation to `prepare_columns()` in slotting namespace

**File:** `src/rwa_calc/engine/slotting/namespace.py`

- Change `prepare_columns()` to accept `config: CalculationConfig` parameter (needed for `reporting_date`)
- When `is_short_maturity` is not in the schema but `maturity_date` is, calculate:
  ```python
  remaining_years = _exact_fractional_years_expr(config.reporting_date, "maturity_date")
  is_short_maturity = remaining_years < 2.5
  ```
- Reuse the existing `_exact_fractional_years_expr` helper from the IRB namespace (extract to a shared location or import it)
- Keep the `lit(False)` default only when neither `is_short_maturity` nor `maturity_date` columns exist
- Also add a `remaining_maturity_years` column for the audit trail

### Step 2: Extract `_exact_fractional_years_expr` to shared utilities

**File:** Create or use existing shared module (e.g., `src/rwa_calc/engine/common.py` or similar)

- Move `_exact_fractional_years_expr` from `irb/namespace.py` to a shared location so both IRB and slotting can use it without cross-importing
- Update IRB namespace import to use the shared location

### Step 3: Update `calculate_branch()` to pass config to `prepare_columns()`

**File:** `src/rwa_calc/engine/slotting/calculator.py`

- `calculate_branch()` (line 136-140) currently calls `exposures.slotting.prepare_columns()` without config
- Update to pass config: `exposures.slotting.prepare_columns(config)`
- Same for `calculate_unified()` and any other callers

### Step 4: Add `remaining_maturity_years` to audit trail

**File:** `src/rwa_calc/engine/slotting/namespace.py`

- In `build_audit()`, include `remaining_maturity_years` so the maturity derivation is traceable

### Step 5: Add short-maturity test fixtures

**File:** `tests/fixtures/exposures/loans.py`

- Add slotting loan fixtures with maturity < 2.5 years from reporting date (e.g., maturity_date = 2027-06-01 with reporting_date = 2026-01-01 = 1.5yr remaining)
- Cover: non-HVCRE Strong, non-HVCRE Good, HVCRE Strong, HVCRE Good (these are the categories with maturity-dependent weights)

### Step 6: Add unit tests for maturity derivation

**File:** `tests/unit/crr/test_slotting_namespace.py`

- Test that `prepare_columns()` correctly sets `is_short_maturity=True` when remaining maturity < 2.5yr
- Test that `is_short_maturity=False` when remaining maturity >= 2.5yr
- Test null `maturity_date` defaults to `is_short_maturity=False` (conservative)
- Test that a pre-existing `is_short_maturity` column is NOT overwritten (user override)

### Step 7: Add acceptance tests for short-maturity slotting scenarios

**File:** `tests/acceptance/crr/test_scenario_crr_e_slotting.py`

- CRR-E scenario: PF Strong with 1.5yr maturity → expect 50% RW
- CRR-E scenario: PF Good with 2yr maturity → expect 70% RW
- CRR-E scenario: HVCRE Strong with 2yr maturity → expect 70% RW
- CRR-E scenario: HVCRE Good with 2yr maturity → expect 95% RW
- Boundary test: exactly 2.5yr remaining → expect >= 2.5yr weights (not short)

### Step 8: Verify Basel 3.1 is unaffected

- Confirm Basel 3.1 path does not use `is_short_maturity` (it uses `is_pre_operational` instead)
- Ensure the maturity calculation doesn't interfere with Basel 3.1 slotting tests

### Step 9: Update documentation and changelog

- Update `docs/appendix/changelog.md` with the fix
- Update `docs/user-guide/methodology/specialised-lending.md` if needed to clarify maturity derivation
