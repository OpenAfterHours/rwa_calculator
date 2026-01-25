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

The system supports 17 entity types organised into logical groups:

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
}
```

## Dual Exposure Class Mapping

Each entity type maps to **both** an SA exposure class and an IRB exposure class. These can differ for certain entity types based on regulatory requirements.

### SA Exposure Class Mapping

Used for SA risk weight table lookups:

| Entity Type | SA Exposure Class | Regulatory Reference |
|-------------|-------------------|---------------------|
| `sovereign` | SOVEREIGN | CRR Art. 112(a) |
| `central_bank` | SOVEREIGN | CRR Art. 112(a) |
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

### IRB Exposure Class Mapping

Used for IRB formula selection:

| Entity Type | IRB Exposure Class | Notes |
|-------------|-------------------|-------|
| `sovereign` | SOVEREIGN | Standard sovereign treatment |
| `central_bank` | SOVEREIGN | Standard sovereign treatment |
| `rgla_sovereign` | SOVEREIGN | Sovereign IRB formula |
| `rgla_institution` | INSTITUTION | Institution IRB formula |
| `pse_sovereign` | SOVEREIGN | Sovereign IRB formula |
| `pse_institution` | INSTITUTION | Institution IRB formula |
| `mdb` | SOVEREIGN | CRR Art. 147(3) |
| `international_org` | SOVEREIGN | CRR Art. 147(3) |
| `institution` | INSTITUTION | Standard institution treatment |
| `bank` | INSTITUTION | Standard institution treatment |
| `ccp` | INSTITUTION | Standard institution treatment |
| `financial_institution` | INSTITUTION | Standard institution treatment |
| `corporate` | CORPORATE | Standard corporate treatment |
| `company` | CORPORATE | Standard corporate treatment |
| `individual` | RETAIL_OTHER | Standard retail treatment |
| `retail` | RETAIL_OTHER | Standard retail treatment |
| `specialised_lending` | SPECIALISED_LENDING | Slotting or IRB |

### Why Classes Can Differ

The SA and IRB exposure classes differ for RGLA, PSE, and MDB entity types because:

- **SA treatment**: Uses specific risk weight tables for RGLA, PSE, and MDB
- **IRB treatment**: Uses the underlying IRB formula (sovereign or institution) based on the nature of the entity's credit support

For example, a government-guaranteed PSE (`pse_sovereign`) uses the PSE risk weight table under SA but the sovereign IRB formula because its credit risk is backed by the government.

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
- `is_regulated` - For FI scalar determination
- `is_managed_as_retail` - For SME retail treatment

### Step 2: Classify Exposure Class

```python
_classify_exposure_class(exposures, config)
```

Maps `entity_type` to exposure classes using the constant mappings:

```python
# Result columns:
exposure_class_sa   # SA class for risk weight lookup
exposure_class_irb  # IRB class for formula selection
exposure_class      # Unified class (SA class for backwards compatibility)
```

### Step 3: Apply SME Classification

```python
_apply_sme_classification(exposures, config)
```

Checks SME criteria per CRR Art. 501:
- Entity must be classified as CORPORATE
- `annual_revenue < EUR 50m` (converted to GBP using config FX rate)
- Revenue must be > 0 (excludes missing data)

If criteria met:
- Sets `is_sme = True`
- Updates `exposure_class` to `CORPORATE_SME`

### Step 4: Apply Retail Classification

```python
_apply_retail_classification(exposures, lending_group_totals, config)
```

Checks retail eligibility per CRR Art. 123:

1. **Mortgage detection**: Identifies mortgages via product_type pattern matching
2. **Threshold check**: Aggregated exposure to lending group < EUR 1m
3. **Residential exclusion**: Residential property collateral excluded from threshold (CRR Art. 123(c))

Classification outcomes:
- Mortgages to individuals → `RETAIL_MORTGAGE`
- Retail exceeding threshold + SME revenue → `CORPORATE_SME`
- Retail exceeding threshold + no SME criteria → `CORPORATE`
- Retail within threshold → remains `RETAIL_OTHER`

### Step 5: Identify Defaults

```python
_identify_defaults(exposures)
```

Checks `default_status` flag:
- Sets `is_defaulted = True`
- Sets `exposure_class_for_sa = DEFAULTED` (SA treatment)
- IRB exposures keep their class but use default LGD

### Step 5a: Infrastructure Classification

```python
_apply_infrastructure_classification(exposures)
```

Identifies infrastructure exposures per CRR Art. 501a:
- Checks product_type for "INFRASTRUCTURE" pattern
- Sets `is_infrastructure = True`
- Eligible for 0.75 supporting factor under CRR (not Basel 3.1)

### Step 5b: FI Scalar Classification

```python
_apply_fi_scalar_classification(exposures, config)
```

Determines Financial Sector Entity (FSE) status and FI scalar eligibility per CRR Art. 153(2):

**Financial Sector Entity Types:**
```python
FINANCIAL_SECTOR_ENTITY_TYPES = {
    "institution",
    "bank",
    "ccp",
    "financial_institution",
    "pse_institution",
    "rgla_institution",
}
```

**Output columns:**
- `is_financial_sector_entity` - True if entity_type in FSE set
- `is_large_financial_sector_entity` - FSE with total_assets >= EUR 70bn
- `requires_fi_scalar` - True if large FSE OR unregulated FSE

**FI Scalar effect**: 1.25x multiplier on IRB correlation

### Step 6: Determine Approach

```python
_determine_approach(exposures, config)
```

Assigns calculation approach based on IRB permissions:

| Condition | Approach |
|-----------|----------|
| Specialised lending + A-IRB permission for SL | AIRB |
| Specialised lending + Slotting permission | SLOTTING |
| Retail classes + A-IRB permission | AIRB |
| Corporate classes + A-IRB permission | AIRB |
| Corporate/Institution/Sovereign + F-IRB (no A-IRB) | FIRB |
| Default / No IRB permission | SA |

### Step 7: Add Classification Audit

```python
_add_classification_audit(exposures)
```

Builds audit trail string for each exposure:
```
entity_type=corporate; exp_class_sa=CORPORATE; exp_class_irb=CORPORATE;
is_sme=true; is_mortgage=false; is_defaulted=false; is_infrastructure=false;
requires_fi_scalar=false; qualifies_as_retail=true
```

### Step 7a: Enrich Slotting Exposures

```python
_enrich_slotting_exposures(exposures)
```

Derives slotting metadata from patterns in reference fields:

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

### Step 8: Split by Approach

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
| `is_financial_sector_entity` | Boolean | FSE flag |
| `is_large_financial_sector_entity` | Boolean | Large FSE (>= EUR 70bn assets) |
| `requires_fi_scalar` | Boolean | Requires 1.25x correlation |
| `approach` | String | Calculation approach (SA/FIRB/AIRB/SLOTTING) |
| `firb_permitted` | Boolean | F-IRB permitted by config |
| `airb_permitted` | Boolean | A-IRB permitted by config |
| `slotting_category` | String | Slotting category (for SL) |
| `sl_type` | String | Specialised lending type |
| `is_hvcre` | Boolean | High-volatility CRE flag |
| `classification_reason` | String | Full audit trail |

## Exposure Classes

The system supports these exposure classes (defined in `domain/enums.py`):

| Class | Description | SA Treatment | IRB Treatment |
|-------|-------------|--------------|---------------|
| `SOVEREIGN` | Central governments, central banks | CQS-based (0%-150%) | Sovereign formula |
| `RGLA` | Regional govts, local authorities | CQS-based | Sovereign or Institution |
| `PSE` | Public sector entities | CQS-based | Sovereign or Institution |
| `MDB` | Multilateral development banks | 0% (eligible) or CQS | Sovereign formula |
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
