# Counterparty Schema Remediation Plan

## Executive Summary

This plan consolidates exposure-class-determining flags into `entity_type`, removes redundant `is_...` columns, implements the missing FI scalar (Article 153, paragraph 2), and properly handles PSE/RGLA dual treatment for SA vs IRB.

---

## Current State vs Target State

### Current Schema (8 boolean flags)
```python
COUNTERPARTY_SCHEMA = {
    "entity_type": pl.String,  # Limited values
    "is_financial_institution": pl.Boolean,
    "is_regulated": pl.Boolean,
    "is_pse": pl.Boolean,
    "is_mdb": pl.Boolean,
    "is_international_org": pl.Boolean,
    "is_central_counterparty": pl.Boolean,
    "is_regional_govt_local_auth": pl.Boolean,
    "is_managed_as_retail": pl.Boolean,
}
```

### Target Schema (2 boolean flags)
```python
COUNTERPARTY_SCHEMA = {
    "entity_type": pl.String,  # Expanded to include all exposure classes + IRB treatment variants
    "is_regulated": pl.Boolean,  # For FI scalar (unregulated FI treatment)
    "is_managed_as_retail": pl.Boolean,  # Orthogonal to entity type (SME retail treatment)
}
```

---

## Expanded entity_type Values

The `entity_type` field becomes the **single source of truth** for exposure class determination, with explicit subtypes for PSE/RGLA to capture their IRB treatment.

### Complete entity_type Mapping

| entity_type | SA ExposureClass | IRB ExposureClass | Regulatory Reference |
|-------------|------------------|-------------------|---------------------|
| `"sovereign"` | SOVEREIGN | SOVEREIGN | CRR Art. 112(a) |
| `"central_bank"` | SOVEREIGN | SOVEREIGN | CRR Art. 112(a) |
| `"rgla_sovereign"` | RGLA | SOVEREIGN | CRR Art. 115, 147(3) |
| `"rgla_institution"` | RGLA | INSTITUTION | CRR Art. 115, 147(3) |
| `"pse_sovereign"` | PSE | SOVEREIGN | CRR Art. 116, 147(3) |
| `"pse_institution"` | PSE | INSTITUTION | CRR Art. 116, 147(3) |
| `"mdb"` | MDB | SOVEREIGN | CRR Art. 117, 147(3) |
| `"international_org"` | MDB | SOVEREIGN | CRR Art. 118, 147(3) |
| `"institution"` | INSTITUTION | INSTITUTION | CRR Art. 112(d) |
| `"bank"` | INSTITUTION | INSTITUTION | CRR Art. 112(d) |
| `"ccp"` | INSTITUTION | INSTITUTION | CRR Art. 300-311 |
| `"financial_institution"` | INSTITUTION | INSTITUTION | CRR Art. 112(d) |
| `"corporate"` | CORPORATE | CORPORATE | CRR Art. 112(g) |
| `"company"` | CORPORATE | CORPORATE | CRR Art. 112(g) |
| `"individual"` | RETAIL_OTHER | RETAIL_OTHER | CRR Art. 112(h) |
| `"retail"` | RETAIL_OTHER | RETAIL_OTHER | CRR Art. 112(h) |
| `"specialised_lending"` | SPECIALISED_LENDING | SPECIALISED_LENDING | CRR Art. 147(8) |

### Why PSE/RGLA Need Subtypes

Under **SA** (CRR Art. 112), PSE and RGLA are distinct exposure classes with their own risk weight treatments.

Under **IRB** (CRR Art. 147), there are NO separate PSE/RGLA exposure classes. Per Art. 147(3):
> "Exposures to regional governments, local authorities and public sector entities shall be treated as exposures to the central government, to regional governments or local authorities, or to institutions."

The IRB treatment is a **regulatory/policy decision** based on:
- **Sovereign treatment**: Entity has taxing powers, explicit government guarantee, or equivalent risk to central government
- **Institution treatment**: Otherwise

This cannot be derived from other fields - it must be explicitly captured in `entity_type`.

### Treatment Examples

| Entity | entity_type | SA Treatment | IRB Treatment |
|--------|-------------|--------------|---------------|
| UK Local Council (with taxing powers) | `"rgla_sovereign"` | RGLA RW table | Sovereign IRB formula |
| Foreign Municipality (no guarantee) | `"rgla_institution"` | RGLA RW table | Institution IRB formula |
| NHS Trust (govt guaranteed) | `"pse_sovereign"` | PSE RW table | Sovereign IRB formula |
| State-owned Enterprise (commercial) | `"pse_institution"` | PSE RW table | Institution IRB formula |
| World Bank | `"mdb"` | MDB RW table (0%) | Sovereign IRB formula |
| European Investment Bank | `"mdb"` | MDB RW table (0%) | Sovereign IRB formula |
| Bank for International Settlements | `"international_org"` | MDB RW table (0%) | Sovereign IRB formula |

---

## Columns to Remove

| Column | Replacement | Migration |
|--------|-------------|-----------|
| `is_pse` | `entity_type = "pse_sovereign"` or `"pse_institution"` | Update all fixtures/data |
| `is_mdb` | `entity_type = "mdb"` | Update all fixtures/data |
| `is_international_org` | `entity_type = "international_org"` | Update all fixtures/data |
| `is_regional_govt_local_auth` | `entity_type = "rgla_sovereign"` or `"rgla_institution"` | Update all fixtures/data |
| `is_central_counterparty` | `entity_type = "ccp"` | Update all fixtures/data |
| `is_financial_institution` | Derive from entity_type in classifier | Logic change only |

---

## Columns to Keep

### `is_regulated` (Boolean)

**Purpose**: Determines if a financial institution is prudentially regulated.

**Regulatory Basis**: CRR Article 153(2) - Unregulated financial sector entities require 1.25x correlation multiplier.

**Why it can't be in entity_type**: An institution, bank, or financial_institution can be either regulated or unregulated. This is orthogonal to the entity classification.

**Default**: `True` (most financial institutions are regulated)

### `is_managed_as_retail` (Boolean)

**Purpose**: Indicates if an SME corporate exposure is managed on a pooled retail basis.

**Regulatory Basis**: CRR Article 123 - SME corporates meeting retail criteria can receive 75% RW instead of 100%.

**Why it can't be in entity_type**: A corporate/company entity may or may not be managed as retail depending on the bank's internal processes and the exposure amount. This is orthogonal to the entity classification.

**Default**: `False`

---

## Classifier Implementation

### Mapping Constants

```python
# entity_type → SA exposure class (for risk weight lookup)
ENTITY_TYPE_TO_SA_CLASS: dict[str, ExposureClass] = {
    "sovereign": ExposureClass.SOVEREIGN,
    "central_bank": ExposureClass.SOVEREIGN,
    "rgla_sovereign": ExposureClass.RGLA,
    "rgla_institution": ExposureClass.RGLA,
    "pse_sovereign": ExposureClass.PSE,
    "pse_institution": ExposureClass.PSE,
    "mdb": ExposureClass.MDB,
    "international_org": ExposureClass.MDB,
    "institution": ExposureClass.INSTITUTION,
    "bank": ExposureClass.INSTITUTION,
    "ccp": ExposureClass.INSTITUTION,
    "financial_institution": ExposureClass.INSTITUTION,
    "corporate": ExposureClass.CORPORATE,
    "company": ExposureClass.CORPORATE,
    "individual": ExposureClass.RETAIL_OTHER,
    "retail": ExposureClass.RETAIL_OTHER,
    "specialised_lending": ExposureClass.SPECIALISED_LENDING,
}

# entity_type → IRB exposure class (for IRB formula selection)
ENTITY_TYPE_TO_IRB_CLASS: dict[str, ExposureClass] = {
    "sovereign": ExposureClass.SOVEREIGN,
    "central_bank": ExposureClass.SOVEREIGN,
    "rgla_sovereign": ExposureClass.SOVEREIGN,  # Sovereign IRB treatment
    "rgla_institution": ExposureClass.INSTITUTION,  # Institution IRB treatment
    "pse_sovereign": ExposureClass.SOVEREIGN,  # Sovereign IRB treatment
    "pse_institution": ExposureClass.INSTITUTION,  # Institution IRB treatment
    "mdb": ExposureClass.SOVEREIGN,  # Sovereign IRB treatment (CRR Art. 147(3))
    "international_org": ExposureClass.SOVEREIGN,  # Sovereign IRB treatment (CRR Art. 147(3))
    "institution": ExposureClass.INSTITUTION,
    "bank": ExposureClass.INSTITUTION,
    "ccp": ExposureClass.INSTITUTION,
    "financial_institution": ExposureClass.INSTITUTION,
    "corporate": ExposureClass.CORPORATE,
    "company": ExposureClass.CORPORATE,
    "individual": ExposureClass.RETAIL_OTHER,
    "retail": ExposureClass.RETAIL_OTHER,
    "specialised_lending": ExposureClass.SPECIALISED_LENDING,
}

# Financial sector entity types (for FI scalar determination)
# Note: MDB and international_org are excluded as they receive sovereign IRB treatment
FINANCIAL_SECTOR_ENTITY_TYPES: set[str] = {
    "institution",
    "bank",
    "ccp",
    "financial_institution",
    "pse_institution",  # PSE treated as institution = financial sector
    "rgla_institution",  # RGLA treated as institution = financial sector
}
```

### Classification Logic

```python
def _classify_exposure_class(
    self,
    exposures: pl.LazyFrame,
    config: CalculationConfig,
) -> pl.LazyFrame:
    """
    Determine exposure class based on entity_type.

    Sets both:
    - exposure_class_sa: For SA risk weight lookup
    - exposure_class_irb: For IRB formula selection
    """
    # Build replacement mappings
    sa_mapping = {k: v.value for k, v in ENTITY_TYPE_TO_SA_CLASS.items()}
    irb_mapping = {k: v.value for k, v in ENTITY_TYPE_TO_IRB_CLASS.items()}

    return exposures.with_columns([
        # SA exposure class
        pl.col("cp_entity_type")
        .replace(sa_mapping, default=ExposureClass.OTHER.value)
        .alias("exposure_class_sa"),

        # IRB exposure class
        pl.col("cp_entity_type")
        .replace(irb_mapping, default=ExposureClass.OTHER.value)
        .alias("exposure_class_irb"),

        # Unified exposure_class (SA class for backwards compatibility)
        pl.col("cp_entity_type")
        .replace(sa_mapping, default=ExposureClass.OTHER.value)
        .alias("exposure_class"),
    ])
```

---

## FI Scalar Implementation

### What is the FI Scalar?

CRR Article 153(2):
> "For all exposures to large financial sector entities, the coefficient of correlation is multiplied by 1.25. For all exposures to unregulated financial sector entities, the coefficients of correlation are multiplied by 1.25."

### Implementation Approach

**Step 1: Derive `is_financial_sector_entity` in classifier**

```python
is_financial_sector_entity = pl.col("cp_entity_type").is_in(FINANCIAL_SECTOR_ENTITY_TYPES)
```

**Step 2: Derive `is_large_financial_sector_entity` in classifier**

```python
# LFSE threshold: EUR 70bn (CRR Art. 4(1)(146))
lfse_threshold_gbp = 70_000_000_000 * eur_gbp_rate

is_large_fse = (
    is_financial_sector_entity &
    (pl.col("cp_total_assets") >= lfse_threshold_gbp)
)
```

**Step 3: Derive `requires_fi_scalar` in classifier**

```python
requires_fi_scalar = (
    is_large_fse |  # Large FSE
    (is_financial_sector_entity & (pl.col("cp_is_regulated") == False))  # Unregulated FSE
)
```

**Step 4: Apply in IRB correlation formula**

```python
# In formulas.py _polars_correlation_expr()
fi_scalar = pl.when(pl.col("requires_fi_scalar")).then(1.25).otherwise(1.0)
final_correlation = base_correlation * fi_scalar
```

---

## Schema Changes

### Updated COUNTERPARTY_SCHEMA

```python
COUNTERPARTY_SCHEMA = {
    "counterparty_reference": pl.String,
    "counterparty_name": pl.String,
    "entity_type": pl.String,  # See expanded values table above
    "country_code": pl.String,
    "annual_revenue": pl.Float64,  # For SME classification (EUR 50m threshold)
    "total_assets": pl.Float64,  # For LFSE threshold (EUR 70bn)
    "default_status": pl.Boolean,
    "sector_code": pl.String,  # Based on SIC
    # Retained boolean flags (orthogonal to entity_type)
    "is_regulated": pl.Boolean,  # For FI scalar - unregulated FSE gets 1.25x correlation
    "is_managed_as_retail": pl.Boolean,  # SME managed on pooled retail basis - 75% RW
}
```

### Validation for entity_type

```python
VALID_ENTITY_TYPES = {
    "sovereign",
    "central_bank",
    "rgla_sovereign",
    "rgla_institution",
    "pse_sovereign",
    "pse_institution",
    "mdb",
    "international_org",
    "institution",
    "bank",
    "ccp",
    "financial_institution",
    "corporate",
    "company",
    "individual",
    "retail",
    "specialised_lending",
}

def validate_entity_type(lf: pl.LazyFrame) -> ValidationResult:
    """Validate entity_type values against allowed list."""
    invalid = lf.filter(~pl.col("entity_type").is_in(VALID_ENTITY_TYPES))
    # ... return validation result
```

---

## Implementation Tasks

### Phase 1: Schema Update
1. Update COUNTERPARTY_SCHEMA to remove 6 boolean columns
2. Add entity_type validation with VALID_ENTITY_TYPES
3. Update schema documentation with expanded entity_type values

### Phase 2: Data Migration
4. Update all test fixtures to use new entity_type values
5. Map existing `is_pse=True` → `entity_type="pse_sovereign"` or `"pse_institution"`
6. Map existing `is_rgla=True` → `entity_type="rgla_sovereign"` or `"rgla_institution"`
7. Create migration guide for external data sources

### Phase 3: Classifier Update
8. Add ENTITY_TYPE_TO_SA_CLASS and ENTITY_TYPE_TO_IRB_CLASS mappings
9. Simplify `_classify_exposure_class()` to use entity_type mapping
10. Add `exposure_class_sa` and `exposure_class_irb` columns
11. Remove loading of removed `is_...` columns in `_add_counterparty_attributes()`
12. Add FI scalar flag derivation logic

### Phase 4: IRB Formula Update
13. Add `requires_fi_scalar` column handling in pipeline
14. Implement 1.25x correlation multiplier in `_polars_correlation_expr()`
15. Update scalar `calculate_correlation()` function for consistency

### Phase 5: SA Calculator Update
16. Update SA calculator to use `exposure_class_sa` for RW lookup
17. Ensure RGLA/PSE use correct RW tables regardless of IRB treatment

### Phase 6: Testing
18. Update unit tests for new entity_type values
19. Add tests for PSE/RGLA with different IRB treatments
20. Add FI scalar tests (LFSE and unregulated FSE scenarios)
21. Regression test all existing scenarios

---

## Files to Modify

| File | Changes |
|------|---------|
| `src/rwa_calc/data/schemas.py` | Remove 6 `is_...` columns, add validation |
| `src/rwa_calc/engine/classifier.py` | Add mappings, simplify classification, add FI scalar |
| `src/rwa_calc/engine/irb/formulas.py` | Add FI scalar to correlation |
| `src/rwa_calc/engine/sa/calculator.py` | Use `exposure_class_sa` for RW lookup |
| `tests/fixtures/counterparty/*.py` | Update entity_type values |
| `tests/fixtures/exposures/*.py` | Remove references to removed columns |
| `docs/data-model/input-schemas.md` | Document new entity_type values |

---

## Before/After Comparison

### Before (PSE Counterparty Data)
```python
{
    "counterparty_reference": "CP_NHS_TRUST",
    "entity_type": "corporate",  # Unclear!
    "is_pse": True,
    "is_mdb": False,
    "is_international_org": False,
    "is_regional_govt_local_auth": False,
    "is_central_counterparty": False,
    "is_financial_institution": False,
    "is_regulated": True,
    "is_managed_as_retail": False,
}
# SA class: PSE (from is_pse=True)
# IRB class: ??? (not captured - defaults to corporate?)
```

### After (PSE Counterparty Data)
```python
{
    "counterparty_reference": "CP_NHS_TRUST",
    "entity_type": "pse_sovereign",  # Explicit: PSE with sovereign IRB treatment
    "is_regulated": True,  # N/A for PSE, but kept for consistency
    "is_managed_as_retail": False,
}
# SA class: PSE (for RW lookup)
# IRB class: SOVEREIGN (for IRB formula)
```

### Before (RGLA Counterparty Data)
```python
{
    "counterparty_reference": "CP_LOCAL_COUNCIL",
    "entity_type": "institution",  # Misleading!
    "is_regional_govt_local_auth": True,
    # ... other flags
}
# SA class: RGLA (from is_rgla=True)
# IRB class: ??? (not captured)
```

### After (RGLA Counterparty Data)
```python
{
    "counterparty_reference": "CP_LOCAL_COUNCIL",
    "entity_type": "rgla_sovereign",  # Explicit: RGLA with sovereign IRB treatment
    "is_regulated": True,
    "is_managed_as_retail": False,
}
# SA class: RGLA (for RW lookup)
# IRB class: SOVEREIGN (for IRB formula)
```

---

## Summary

| Change | Impact |
|--------|--------|
| Remove 6 `is_...` columns | Simplifies schema, reduces redundancy |
| Expand entity_type with PSE/RGLA subtypes | Captures IRB treatment explicitly |
| Dual mapping (SA + IRB) | Correct exposure class for each approach |
| Keep `is_regulated` | Required for FI scalar (unregulated FSE) |
| Keep `is_managed_as_retail` | Required for SME retail treatment |
| Implement FI scalar | Fixes missing regulatory requirement |

---

## Regulatory References

- **CRR Article 4(1)(27)**: Financial sector entity definition
- **CRR Article 4(1)(146)**: Large financial sector entity definition (EUR 70bn)
- **CRR Article 112**: SA exposure classes
- **CRR Article 115**: RGLA treatment (sovereign or institution)
- **CRR Article 116**: PSE treatment (sovereign or institution)
- **CRR Article 117**: MDB treatment
- **CRR Article 118**: International organisation treatment
- **CRR Article 123**: Retail exposure criteria (`is_managed_as_retail`)
- **CRR Article 147**: IRB exposure classes
- **CRR Article 147(3)**: PSE/RGLA IRB treatment assignment
- **CRR Article 153(2)**: FI scalar (1.25x correlation)
- **CRR Article 300-311**: CCP exposure treatment
