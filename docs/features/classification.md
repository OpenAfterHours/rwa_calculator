# Exposure Classification

This document provides comprehensive documentation of the exposure classification system used to determine regulatory exposure classes and calculation approaches.

## Overview

The classifier (`src/rwa_calc/engine/classifier.py`) is responsible for:

1. Mapping counterparty entity types to regulatory exposure classes
2. Determining the calculation approach (SA, F-IRB, A-IRB, Slotting)
3. Applying SME and retail classification rules
4. Identifying defaulted exposures
5. Determining FI scalar eligibility for IRB correlation adjustment

## Entity Type: The Single Source of Truth

The `entity_type` field on counterparties is the **authoritative source** for exposure class determination. This design eliminates ambiguity from overlapping boolean flags and ensures consistent classification.

### Valid Entity Types

The system supports 18 entity types organised into logical groups:

```python
VALID_ENTITY_TYPES = {
    # Sovereign class
    "sovereign",
    "central_bank",

    # RGLA class (Regional Governments/Local Authorities)
    "rgla_sovereign",      # Has taxing powers or government guarantee
    "rgla_institution",    # No sovereign equivalence

    # PSE class (Public Sector Entities)
    "pse_sovereign",       # Government guaranteed
    "pse_institution",     # Commercial PSE

    # MDB/International org class
    "mdb",
    "international_org",

    # Institution class
    "institution",
    "bank",
    "ccp",
    "financial_institution",

    # Corporate class
    "corporate",
    "company",

    # Retail class
    "individual",
    "retail",

    # Specialised lending
    "specialised_lending",

    # Equity
    "equity",
}
```

## Dual Exposure Class Mapping

Each entity type maps to **both** an SA exposure class and an IRB exposure class. These can differ for certain entity types based on regulatory requirements.

### SA Exposure Class Mapping

Used for SA risk weight table lookups:

| Entity Type | SA Exposure Class | Regulatory Reference |
|-------------|-------------------|---------------------|
| `sovereign` | CENTRAL_GOVT_CENTRAL_BANK | CRR Art. 112(a) |
| `central_bank` | CENTRAL_GOVT_CENTRAL_BANK | CRR Art. 112(a) |
| `rgla_sovereign` | RGLA | CRR Art. 115 |
| `rgla_institution` | RGLA | CRR Art. 115 |
| `pse_sovereign` | PSE | CRR Art. 116 |
| `pse_institution` | PSE | CRR Art. 116 |
| `mdb` | MDB | CRR Art. 117 |
| `international_org` | MDB | CRR Art. 118 |
| `institution` | INSTITUTION | CRR Art. 112(d) |
| `bank` | INSTITUTION | CRR Art. 112(d) |
| `ccp` | INSTITUTION | CRR Art. 300-311 |
| `financial_institution` | INSTITUTION | CRR Art. 112(d) |
| `corporate` | CORPORATE | CRR Art. 112(g) |
| `company` | CORPORATE | CRR Art. 112(g) |
| `individual` | RETAIL_OTHER | CRR Art. 112(h) |
| `retail` | RETAIL_OTHER | CRR Art. 112(h) |
| `specialised_lending` | SPECIALISED_LENDING | CRR Art. 147(8) |
| `equity` | EQUITY | CRR Art. 112(p) |

### IRB Exposure Class Mapping

Used for IRB formula selection:

| Entity Type | IRB Exposure Class | Notes |
|-------------|-------------------|-------|
| `sovereign` | CENTRAL_GOVT_CENTRAL_BANK | Standard central govt/central bank treatment |
| `central_bank` | CENTRAL_GOVT_CENTRAL_BANK | Standard central govt/central bank treatment |
| `rgla_sovereign` | CENTRAL_GOVT_CENTRAL_BANK | Central govt/central bank IRB formula |
| `rgla_institution` | INSTITUTION | Institution IRB formula |
| `pse_sovereign` | CENTRAL_GOVT_CENTRAL_BANK | Central govt/central bank IRB formula |
| `pse_institution` | INSTITUTION | Institution IRB formula |
| `mdb` | CENTRAL_GOVT_CENTRAL_BANK | CRR Art. 147(3) |
| `international_org` | CENTRAL_GOVT_CENTRAL_BANK | CRR Art. 147(3) |
| `institution` | INSTITUTION | Standard institution treatment |
| `bank` | INSTITUTION | Standard institution treatment |
| `ccp` | INSTITUTION | Standard institution treatment |
| `financial_institution` | INSTITUTION | Standard institution treatment |
| `corporate` | CORPORATE | Standard corporate treatment |
| `company` | CORPORATE | Standard corporate treatment |
| `individual` | RETAIL_OTHER | Standard retail treatment |
| `retail` | RETAIL_OTHER | Standard retail treatment |
| `specialised_lending` | SPECIALISED_LENDING | Slotting or IRB |
| `equity` | EQUITY | CRE60 |

### Why Classes Can Differ

The SA and IRB exposure classes differ for RGLA, PSE, and MDB entity types because:

- **SA treatment**: Uses specific risk weight tables for RGLA, PSE, and MDB
- **IRB treatment**: Uses the underlying IRB formula (central govt/central bank or institution) based on the nature of the entity's credit support

For example, a government-guaranteed PSE (`pse_sovereign`) uses the PSE risk weight table under SA but the central govt/central bank IRB formula because its credit risk is backed by the government.

## Classification Pipeline

The `ExposureClassifier.classify()` method processes exposures through a defined sequence of steps:

### Step 1: Add Counterparty Attributes

```python
_add_counterparty_attributes(exposures, counterparties)
```

Joins exposure data with counterparty attributes needed for classification:
- `entity_type` - Single source of truth
- `annual_revenue` - For SME check
- `total_assets` - For large FSE threshold
- `default_status` - For default identification
- `apply_fi_scalar` - For FI scalar determination
- `is_managed_as_retail` - For SME retail treatment

### Step 2: Derive Independent Flags

```python
_derive_independent_flags(exposures, config, schema_names)
```

Derives all independent classification flags in a single `.with_columns()` call for
LazyFrame plan optimisation. This batch covers exposure class mapping, default identification,
infrastructure classification, and FI scalar classification.

**Exposure class mapping** — maps `entity_type` to exposure classes using the constant mappings:

```python
# Result columns:
exposure_class_sa   # SA class for risk weight lookup
exposure_class_irb  # IRB class for formula selection
exposure_class      # Unified class (SA class for backwards compatibility)
```

**Default identification** — checks `default_status` flag:
- Sets `is_defaulted = True`
- Sets `exposure_class_for_sa = DEFAULTED` (SA treatment)
- IRB exposures keep their class but use default LGD

**Infrastructure classification** — identifies infrastructure exposures per CRR Art. 501a:
- Checks product_type for "INFRASTRUCTURE" pattern
- Sets `is_infrastructure = True`
- Eligible for 0.75 supporting factor under CRR (not Basel 3.1)

**FI scalar classification** — determines FI scalar eligibility per CRR Art. 153(2):

- `requires_fi_scalar` — derived directly from the user-supplied `apply_fi_scalar` flag on counterparties
- **Effect**: 1.25x multiplier on IRB asset correlation

**Slotting enrichment** — derives slotting metadata from patterns in reference fields:

**Slotting Category** (from counterparty_reference):
- `*_STRONG*` → strong
- `*_GOOD*` → good
- `*_SATISFACTORY*` → satisfactory
- `*_WEAK*` → weak
- `*_DEFAULT*` → default

**Specialised Lending Type** (from product_type):
- `*PROJECT*` → project_finance
- `*OBJECT*` → object_finance
- `*COMMOD*` → commodities_finance
- `IPRE` → ipre
- `HVCRE` → hvcre

**HVCRE Flag**:
- `is_hvcre = True` if sl_type == "hvcre"

### Step 3: SME and Retail Classification

```python
_classify_sme_and_retail(exposures, config)
```

Applies SME and retail classification in a single `.with_columns()` call.

**SME criteria** per CRR Art. 501:
- Entity must be classified as CORPORATE
- `annual_revenue < EUR 50m` (converted to GBP using config FX rate)
- Revenue must be > 0 (excludes missing data)

If criteria met:
- Sets `is_sme = True`
- Updates `exposure_class` to `CORPORATE_SME`

**Retail eligibility** per CRR Art. 123:

1. **Mortgage detection**: Identifies mortgages via product_type pattern matching
2. **Threshold check**: Aggregated exposure to lending group < EUR 1m
3. **Residential exclusion**: Residential property collateral excluded from threshold (CRR Art. 123(c))

### Step 4: Corporate to Retail Reclassification

```python
_reclassify_corporate_to_retail(exposures, config, schema_names)
```

Reclassifies exposures based on retail threshold outcomes:
- Mortgages to individuals → `RETAIL_MORTGAGE`
- Retail exceeding threshold + SME revenue → `CORPORATE_SME`
- Retail exceeding threshold + no SME criteria → `CORPORATE`
- Retail within threshold → remains `RETAIL_OTHER`

### Step 5: Resolve Model Permissions

```python
_resolve_model_permissions(exposures, model_permissions)
```

When `permission_mode=PermissionMode.IRB` and `model_permissions` data is provided,
resolves per-exposure IRB permissions:

1. Joins exposures to `model_permissions` via `model_id` (propagated from internal rating via rating inheritance)
2. Filters by `exposure_class` match
3. Applies geography filter (`country_codes`) and book code exclusions
4. Sets `model_airb_permitted`, `model_firb_permitted`, and `model_slotting_permitted` boolean columns
5. Exposures without `model_id` get all flags set to `False` (fall back to SA)

When model permissions are active, Step 6 uses per-row `model_airb_permitted` /
`model_firb_permitted` / `model_slotting_permitted` flags exclusively. There is
no org-wide fallback — exposures without a matching model permission use SA.

See [Input Schemas — Model Permissions](../data-model/input-schemas.md#model-permissions-schema) for the data schema.

### Step 6: Determine Approach and Finalize

```python
_determine_approach_and_finalize(exposures, config, has_model_permissions)
```

Assigns calculation approach and builds classification audit trail in a single
`.with_columns()` call.

When `permission_mode=PermissionMode.IRB` and model permissions are present,
per-row `model_airb_permitted` / `model_firb_permitted` / `model_slotting_permitted`
flags drive all approach routing. When `permission_mode=PermissionMode.STANDARDISED`,
all exposures are assigned SA.

| Condition | Approach |
|-----------|----------|
| Specialised lending + A-IRB permission for SL | AIRB |
| Specialised lending + Slotting permission | SLOTTING |
| Retail classes + A-IRB permission | AIRB |
| Corporate classes + A-IRB permission | AIRB |
| Corporate/Institution/Central Govt/Central Bank + F-IRB (no A-IRB) | FIRB |
| Default / No IRB permission | SA |

!!! note
    "A-IRB permission", "F-IRB permission", and "Slotting permission" above
    refer to per-row model permission flags when `model_permissions` data is
    provided (IRB mode). In STANDARDISED mode, all exposures use SA regardless
    of model permissions. See [Step 5](#step-5-resolve-model-permissions).

**Audit trail** — builds a classification reason string for each exposure:
```
entity_type=corporate; exp_class_sa=CORPORATE; exp_class_irb=CORPORATE;
is_sme=true; is_mortgage=false; is_defaulted=false; is_infrastructure=false;
requires_fi_scalar=false; qualifies_as_retail=true
```

### Step 7: Split by Approach

Filters exposures into separate LazyFrames:
- `sa_exposures` - Approach = SA
- `irb_exposures` - Approach = FIRB or AIRB
- `slotting_exposures` - Approach = SLOTTING

## Output Schema

The classifier adds these columns to the exposure data:

| Column | Type | Description |
|--------|------|-------------|
| `exposure_class` | String | SA exposure class (backwards compatible) |
| `exposure_class_sa` | String | SA exposure class (explicit) |
| `exposure_class_irb` | String | IRB exposure class |
| `is_sme` | Boolean | SME classification (revenue < EUR 50m) |
| `is_mortgage` | Boolean | Mortgage product flag |
| `qualifies_as_retail` | Boolean | Meets retail threshold |
| `retail_threshold_exclusion_applied` | Boolean | Residential RE excluded from threshold |
| `is_defaulted` | Boolean | Default status |
| `exposure_class_for_sa` | String | SA class (DEFAULTED if in default) |
| `is_infrastructure` | Boolean | Infrastructure lending flag |
| `requires_fi_scalar` | Boolean | Requires 1.25x IRB correlation (from `apply_fi_scalar`) |
| `approach` | String | Calculation approach (SA/FIRB/AIRB/SLOTTING) |
| `model_firb_permitted` | Boolean | F-IRB permitted by model permissions |
| `model_airb_permitted` | Boolean | A-IRB permitted by model permissions |
| `model_slotting_permitted` | Boolean | Slotting permitted by model permissions |
| `slotting_category` | String | Slotting category (for SL) |
| `sl_type` | String | Specialised lending type |
| `is_hvcre` | Boolean | High-volatility CRE flag |
| `classification_reason` | String | Full audit trail |

## Exposure Classes

The system supports these exposure classes (defined in `domain/enums.py`):

| Class | Description | SA Treatment | IRB Treatment |
|-------|-------------|--------------|---------------|
| `CENTRAL_GOVT_CENTRAL_BANK` | Central governments, central banks | CQS-based (0%-150%) | Central govt/central bank formula |
| `RGLA` | Regional govts, local authorities | CQS-based | Central govt/central bank or Institution |
| `PSE` | Public sector entities | CQS-based | Central govt/central bank or Institution |
| `MDB` | Multilateral development banks | 0% (eligible) or CQS | Central govt/central bank formula |
| `INSTITUTION` | Banks, investment firms | CQS-based (20%-150%) | Institution formula |
| `CORPORATE` | Non-financial corporates | CQS-based or 100% | Corporate formula |
| `CORPORATE_SME` | SME corporates (<EUR 50m) | As corporate | SME adjustment |
| `RETAIL_MORTGAGE` | Residential mortgages | LTV-based (20%-70%) | Retail formula |
| `RETAIL_QRRE` | Qualifying revolving retail | 75% | QRRE formula |
| `RETAIL_OTHER` | Other retail | 75% | Retail formula |
| `SPECIALISED_LENDING` | PF, OF, CF, IPRE | Per slotting | Slotting/IRB |
| `EQUITY` | Equity exposures | 100%-400% | SA only (Basel 3.1) |
| `DEFAULTED` | Defaulted exposures | 100%-150% | Default LGD |
| `OTHER` | Unmapped/other | 100% | N/A |

## Regulatory References

- **CRR Art. 112**: SA exposure class definitions
- **CRR Art. 115**: RGLA treatment
- **CRR Art. 116**: PSE treatment
- **CRR Art. 117-118**: MDB and international organisation treatment
- **CRR Art. 123**: Retail exposure criteria
- **CRR Art. 147**: IRB exposure class definitions
- **CRR Art. 153(2)**: FI scalar (1.25x correlation)
- **CRR Art. 501**: SME supporting factor
- **CRR Art. 501a**: Infrastructure supporting factor
- **CRE30.6**: SME classification (Basel Framework)
- **CRE20.65-70**: Retail exposure criteria (Basel Framework)
