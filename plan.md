# Plan: Fix UK Government Guarantee "Not Beneficial" Bug

## Root Cause Analysis

The guarantor risk weight (RW) lookup in both the SA calculator and IRB namespace uses **regex-based** `str.contains()` matching on `guarantor_entity_type` to determine which risk weight table to use. This is inconsistent with the **dict-based** `ENTITY_TYPE_TO_SA_CLASS` mapping used to derive `guarantor_exposure_class`.

### The Mismatch

The regex patterns only match entity types containing "sovereign", "institution", or "corporate":

| Entity Type | Regex Match | Dict Mapping (correct) |
|---|---|---|
| `"sovereign"` | "sovereign" ✓ | CENTRAL_GOVT_CENTRAL_BANK |
| `"central_bank"` | **NONE** ✗ → NULL RW | CENTRAL_GOVT_CENTRAL_BANK |
| `"bank"` | **NONE** ✗ → NULL RW | INSTITUTION |
| `"ccp"` | **NONE** ✗ → NULL RW | INSTITUTION |
| `"mdb"` | **NONE** ✗ → NULL RW | MDB |
| `"international_org"` | **NONE** ✗ → NULL RW | MDB |
| `"company"` | **NONE** ✗ → NULL RW | CORPORATE |

When `guarantor_rw` is NULL, the beneficial check (`guarantor_rw < pre_crm_risk_weight`) evaluates to False, causing the guarantee to be marked as **"GUARANTEE_NOT_APPLIED_NON_BENEFICIAL"**.

If the UK government guarantor uses entity_type `"central_bank"` (Bank of England) or any non-"sovereign" central govt type, the guarantee RW lookup fails silently.

### Secondary Issue: Missing Domestic Sovereign Treatment for Guarantors

The SA calculator applies Art. 114(3) domestic currency treatment for **direct exposures** (UK CGCB + GBP → 0% RW regardless of CQS) at `sa/calculator.py:421-426`. But this treatment is **NOT** applied to the guarantor RW lookup. An unrated UK sovereign guarantor in GBP would get 100% RW (unrated sovereign fallback) instead of 0%.

**Affected files:**
- `src/rwa_calc/engine/sa/calculator.py:662-712` (SA guarantor RW lookup)
- `src/rwa_calc/engine/irb/namespace.py:706-751` (IRB guarantor RW lookup)

## Remediation Plan

### Step 1: Refactor guarantor RW lookup to use `guarantor_exposure_class` instead of regex

**Both SA calculator and IRB namespace** — Replace the `str.contains()` pattern matching with a lookup based on `guarantor_exposure_class`, which is already correctly derived from `ENTITY_TYPE_TO_SA_CLASS`.

Change from:
```python
.when(_ugt.str.contains("SOVEREIGN", literal=True))
.then(sovereign_rw_chain)
.when(_ugt.str.contains("INSTITUTION", literal=True))
.then(institution_rw_chain)
.when(_ugt.str.contains("CORPORATE", literal=True))
.then(corporate_rw_chain)
```

To:
```python
.when(pl.col("guarantor_exposure_class") == "CENTRAL_GOVT_CENTRAL_BANK")
.then(sovereign_rw_chain)
.when(pl.col("guarantor_exposure_class").is_in(["INSTITUTION", "MDB"]))
.then(institution_rw_chain)
.when(pl.col("guarantor_exposure_class").is_in(["CORPORATE", "CORPORATE_SME"]))
.then(corporate_rw_chain)
```

This ensures all entity types that map to a given exposure class get the correct guarantor RW.

**Files to modify:**
- `src/rwa_calc/engine/sa/calculator.py` (~line 662-712)
- `src/rwa_calc/engine/irb/namespace.py` (~line 706-751)

### Step 2: Add domestic sovereign treatment for guarantor RW

Add Art. 114(3)/CRR Art. 114(4) treatment to the guarantor RW lookup: when the guarantor is a UK sovereign/central bank and the exposure is in GBP, the guarantor RW should be 0% regardless of CQS.

Add a pre-check before the CQS-based lookup:
```python
.when(
    (pl.col("guarantor_exposure_class") == "CENTRAL_GOVT_CENTRAL_BANK")
    & (pl.col("guarantor_country_code") == "GB")
    & (pl.col("currency") == "GBP")
)
.then(pl.lit(0.0))
```

This requires the guarantor's country_code to be available. The CRM processor already joins the counterparty_lookup for `entity_type` — extend this to also pick up `country_code` as `guarantor_country_code`.

**Files to modify:**
- `src/rwa_calc/engine/crm/processor.py` (~line 2220-2230) — add `country_code` to guarantor counterparty join
- `src/rwa_calc/engine/crm/namespace.py` (~line 600-620) — same for namespace version
- `src/rwa_calc/engine/sa/calculator.py` — add domestic treatment to guarantor RW
- `src/rwa_calc/engine/irb/namespace.py` — add domestic treatment to guarantor RW

### Step 3: Ensure `guarantor_exposure_class` column is available in IRB namespace

The IRB namespace's `apply_guarantee_substitution` needs `guarantor_exposure_class` for the refactored lookup. This column is set in the CRM processor during `apply_guarantees()`, so it should already be present on exposures reaching the IRB calculator. Verify this is the case and add a fallback computation if needed (from `guarantor_entity_type` via `ENTITY_TYPE_TO_SA_CLASS`).

### Step 4: Write tests

1. **Unit test (IRB namespace)**: FIRB exposure guaranteed by `entity_type="central_bank"` (UK) — should get 0% guarantor RW and be beneficial
2. **Unit test (IRB namespace)**: FIRB exposure guaranteed by `entity_type="sovereign"` with null CQS and GBP currency — should get 0% RW via domestic treatment
3. **Unit test (SA calculator)**: SA exposure guaranteed by `entity_type="bank"` — should get institution RW table
4. **Unit test (SA calculator)**: SA exposure guaranteed by `entity_type="company"` — should get corporate RW table
5. **Acceptance test**: Full pipeline test for FIRB corporate exposure guaranteed by UK government in GBP — should produce 0% RW on guaranteed portion, CGCB post-CRM exposure class

### Step 5: Update docs and changelog

Add entry to `docs/appendix/changelog.md` documenting the fix.

## Files Summary

| File | Changes |
|------|---------|
| `src/rwa_calc/engine/sa/calculator.py` | Refactor guarantor RW lookup + add domestic treatment |
| `src/rwa_calc/engine/irb/namespace.py` | Same as above |
| `src/rwa_calc/engine/crm/processor.py` | Add `country_code` to guarantor counterparty join |
| `src/rwa_calc/engine/crm/namespace.py` | Same as above |
| `tests/unit/irb/test_irb_pre_post_crm.py` | Add tests for central_bank entity type + domestic treatment |
| `tests/unit/crr/test_sa_guarantee.py` (new) | SA guarantee tests for bank/company entity types |
| `docs/appendix/changelog.md` | Add changelog entry |
