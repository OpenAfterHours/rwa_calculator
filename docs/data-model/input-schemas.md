# Input Data Schemas

This page documents the authoritative schemas for all input data files required by the RWA calculator. These schemas are defined in `src/rwa_calc/data/schemas.py` and represent the single source of truth.

## Quick Reference

| Data Category | File(s) | Required | Purpose |
|---------------|---------|----------|---------|
| [Counterparty](#counterparty-schema) | `counterparty/*.parquet` | Yes | Borrower/obligor information |
| [Facility](#facility-schema) | `exposures/facilities.parquet` | Yes | Committed credit limits |
| [Loan](#loan-schema) | `exposures/loans.parquet` | Yes | Drawn exposures |
| [Contingent](#contingent-schema) | `exposures/contingents.parquet` | No | Off-balance sheet items |
| [Collateral](#collateral-schema) | `collateral/collateral.parquet` | No | Security/collateral |
| [Guarantee](#guarantee-schema) | `guarantee/guarantee.parquet` | No | Credit protection |
| [Provision](#provision-schema) | `provision/provision.parquet` | No | IFRS 9 provisions |
| [Rating](#rating-schema) | `ratings/ratings.parquet` | No | Credit ratings |
| [FX Rates](#fx-rates-schema) | `fx_rates/fx_rates.parquet` | No | Currency conversion rates |
| [Specialised Lending](#specialised-lending-schema) | N/A | No | Slotting approach data |
| [Equity Exposure](#equity-exposure-schema) | N/A | No | Equity holdings |

**Mapping Files:**

| Mapping | File | Purpose |
|---------|------|---------|
| [Facility Mapping](#facility-mapping-schema) | `exposures/facility_mapping.parquet` | Facility-to-loan hierarchy |
| [Org Mapping](#org-mapping-schema) | `mapping/org_mapping.parquet` | Organisation hierarchy (rating inheritance) |
| [Lending Mapping](#lending-mapping-schema) | `mapping/lending_mapping.parquet` | Lending groups (retail threshold aggregation) |

---

## Counterparty Schema

**Purpose:** Defines borrower/obligor information used for exposure classification, risk weight determination, and hierarchy resolution.

**File:** `counterparty/{entity_type}.parquet` (e.g., `counterparty/corporate.parquet`)

| Column | Type | Required | Description |
|--------|------|----------|-------------|
| `counterparty_reference` | `String` | Yes | Unique identifier for the counterparty |
| `counterparty_name` | `String` | Yes | Legal name of the counterparty |
| `entity_type` | `String` | Yes | **Single source of truth** for exposure class (see valid values below) |
| `country_code` | `String` | Yes | ISO 3166-1 alpha-2 country code |
| `annual_revenue` | `Float64` | No | Annual revenue in GBP (for SME classification - EUR 50m threshold) |
| `total_assets` | `Float64` | No | Total assets in GBP (for large FSE threshold - EUR 70bn per CRR Art. 4(1)(146)) |
| `default_status` | `Boolean` | No | Whether counterparty is in default |
| `sector_code` | `String` | No | Industry sector code (SIC-based) |
| `is_regulated` | `Boolean` | No | Prudentially regulated (affects FI scalar - CRR Art. 153(2)) |
| `is_managed_as_retail` | `Boolean` | No | SME managed on pooled retail basis (75% RW per CRR Art. 123) |

### Entity Type: The Single Source of Truth

The `entity_type` field is the **authoritative source** for determining both SA and IRB exposure classes. Each entity type maps to specific exposure classes for each approach. This design ensures consistent classification across the calculation pipeline.

**Valid `entity_type` values:**

| Entity Type | SA Exposure Class | IRB Exposure Class | Regulatory Reference |
|-------------|-------------------|--------------------|-----------------------|
| **Sovereign Class** |
| `sovereign` | CENTRAL_GOVT_CENTRAL_BANK | CENTRAL_GOVT_CENTRAL_BANK | CRR Art. 112(a) |
| `central_bank` | CENTRAL_GOVT_CENTRAL_BANK | CENTRAL_GOVT_CENTRAL_BANK | CRR Art. 112(a) |
| **RGLA Class** (Regional Governments/Local Authorities) |
| `rgla_sovereign` | RGLA | CENTRAL_GOVT_CENTRAL_BANK | CRR Art. 115 - has taxing powers/govt guarantee |
| `rgla_institution` | RGLA | INSTITUTION | CRR Art. 115 - no sovereign equivalence |
| **PSE Class** (Public Sector Entities) |
| `pse_sovereign` | PSE | CENTRAL_GOVT_CENTRAL_BANK | CRR Art. 116 - govt guaranteed |
| `pse_institution` | PSE | INSTITUTION | CRR Art. 116 - commercial PSE |
| **MDB/International Org Class** |
| `mdb` | MDB | CENTRAL_GOVT_CENTRAL_BANK | CRR Art. 117 - 0% RW if on eligible list |
| `international_org` | MDB | CENTRAL_GOVT_CENTRAL_BANK | CRR Art. 118 |
| **Institution Class** |
| `institution` | INSTITUTION | INSTITUTION | CRR Art. 112(d) |
| `bank` | INSTITUTION | INSTITUTION | CRR Art. 112(d) |
| `ccp` | INSTITUTION | INSTITUTION | CRR Art. 300-311 (CCP treatment) |
| `financial_institution` | INSTITUTION | INSTITUTION | CRR Art. 112(d) |
| **Corporate Class** |
| `corporate` | CORPORATE | CORPORATE | CRR Art. 112(g) |
| `company` | CORPORATE | CORPORATE | CRR Art. 112(g) |
| **Retail Class** |
| `individual` | RETAIL_OTHER | RETAIL_OTHER | CRR Art. 112(h) |
| `retail` | RETAIL_OTHER | RETAIL_OTHER | CRR Art. 112(h) |
| **Specialised Lending Class** |
| `specialised_lending` | SPECIALISED_LENDING | SPECIALISED_LENDING | CRR Art. 147(8) |

### Why SA and IRB Classes Can Differ

For certain entity types, the regulatory treatment differs between SA and IRB approaches:

- **RGLA/PSE with sovereign treatment**: Under SA, these use dedicated RGLA/PSE risk weight tables. Under IRB, those with government guarantees or taxing powers use the central govt/central bank IRB formula.
- **RGLA/PSE with institution treatment**: Under SA, these use RGLA/PSE tables. Under IRB, commercial PSEs without sovereign backing use the institution IRB formula.
- **MDB/International Orgs**: Under SA, these typically receive 0% RW from the MDB table. Under IRB, they use the central govt/central bank formula.

### Additional Classification Flags

| Column | Purpose | When Used |
|--------|---------|-----------|
| `is_regulated` | Determines if FI scalar (1.25x correlation) applies | Unregulated financial sector entities get FI scalar under IRB (CRR Art. 153(2)) |
| `is_managed_as_retail` | SME managed on pooled retail basis | Can use 75% RW under SA (CRR Art. 123) |

### Financial Sector Entity (FSE) Determination

The following entity types are classified as Financial Sector Entities for FI scalar purposes:

- `institution`
- `bank`
- `ccp`
- `financial_institution`
- `pse_institution` (PSE treated as institution)
- `rgla_institution` (RGLA treated as institution)

**FI Scalar applies when (CRR Art. 153(2)):**
1. Large FSE: `total_assets >= EUR 70bn`, OR
2. Unregulated FSE: `is_regulated = False`

**Example:**

```python
import polars as pl

counterparties = pl.DataFrame({
    "counterparty_reference": ["CORP_001", "CORP_002", "SOV_001", "BANK_001", "PSE_001"],
    "counterparty_name": ["Acme Corp Ltd", "Beta Industries PLC", "UK Treasury", "Major Bank PLC", "Local Council"],
    "entity_type": ["corporate", "corporate", "sovereign", "bank", "pse_sovereign"],
    "country_code": ["GB", "GB", "GB", "GB", "GB"],
    "annual_revenue": [25_000_000.0, 500_000_000.0, None, None, None],
    "total_assets": [30_000_000.0, 600_000_000.0, None, 80_000_000_000.0, 500_000_000.0],
    "default_status": [False, False, False, False, False],
    "sector_code": ["62.01", "28.11", None, "64.19", None],
    "is_regulated": [False, False, True, True, True],
    "is_managed_as_retail": [False, False, False, False, False],
})
```

### Classification Algorithm Summary

The classifier (`engine/classifier.py`) processes counterparties through these steps:

1. **Entity Type Mapping**: Maps `entity_type` to both SA and IRB exposure classes
2. **SME Classification**: Checks if `annual_revenue < EUR 50m` for corporates
3. **Retail Threshold**: Aggregates exposures by lending group against EUR 1m threshold
4. **Default Identification**: Checks `default_status` for defaulted treatment
5. **FI Scalar Determination**: Identifies large/unregulated FSEs for 1.25x correlation
6. **Approach Assignment**: Assigns SA/F-IRB/A-IRB/Slotting based on IRB permissions

See [Classification](../features/classification.md) for the complete classification algorithm.

---

## Facility Schema

**Purpose:** Defines committed credit facilities (parent nodes in exposure hierarchy). Facilities represent credit limits; actual drawings are captured in the Loan schema.

**File:** `exposures/facilities.parquet`

| Column | Type | Required | Description |
|--------|------|----------|-------------|
| `facility_reference` | `String` | Yes | Unique identifier for the facility |
| `product_type` | `String` | Yes | Product classification |
| `book_code` | `String` | Yes | Portfolio/book classification |
| `counterparty_reference` | `String` | Yes | Link to counterparty |
| `value_date` | `Date` | Yes | Facility start date |
| `maturity_date` | `Date` | Yes | Final maturity date |
| `currency` | `String` | Yes | ISO 4217 currency code |
| `limit` | `Float64` | Yes | Committed facility limit |
| `committed` | `Boolean` | Yes | Whether facility is committed |
| `lgd` | `Float64` | No | Internal LGD estimate (A-IRB) |
| `beel` | `Float64` | No | Best estimate expected loss |
| `is_revolving` | `Boolean` | Yes | Revolving vs term facility |
| `seniority` | `String` | Yes | `senior` or `subordinated` (affects F-IRB LGD) |
| `risk_type` | `String` | Yes | Off-balance sheet risk category (see below) |
| `ccf_modelled` | `Float64` | No | A-IRB modelled CCF (0.0-1.5) |
| `is_short_term_trade_lc` | `Boolean` | No | Short-term trade LC for goods movement (Art. 166(9)) |

**Valid `product_type` values:**

| Value | Description |
|-------|-------------|
| `rcf` | Revolving credit facility |
| `term_loan` | Term loan facility |
| `mortgage` | Mortgage facility |
| `overdraft` | Overdraft facility |
| `credit_card` | Credit card facility |
| `trade_finance` | Trade finance facility |
| `guarantee` | Guarantee facility |
| `project_finance` | Project finance |

**Valid `seniority` values:**

| Value | F-IRB LGD | Description |
|-------|-----------|-------------|
| `senior` | 45% | Senior unsecured claims |
| `subordinated` | 75% | Subordinated claims |

**Valid `risk_type` values (CRR Art. 111 CCF Categories):**

| Code | Full Value | SA CCF | F-IRB CCF | Description |
|------|------------|--------|-----------|-------------|
| `FR` | `full_risk` | 100% | 100% | Direct credit substitutes, guarantees, acceptances |
| `MR` | `medium_risk` | 50% | 75% | NIFs, RUFs, standby LCs, committed undrawn |
| `MLR` | `medium_low_risk` | 20% | 75% | Documentary credits, trade finance |
| `LR` | `low_risk` | 0% | 0% | Unconditionally cancellable commitments |

**Note:** Under F-IRB (CRR Art. 166(8)), MR and MLR both become 75% CCF.

**F-IRB Exception (Art. 166(9)):** Short-term letters of credit arising from the movement of goods retain 20% CCF under F-IRB. To flag these exposures, set `is_short_term_trade_lc = True` for MLR risk type items.

| Column | Type | Required | Description |
|--------|------|----------|-------------|
| `is_short_term_trade_lc` | `Boolean` | No | True for short-term trade LCs for goods movement (Art. 166(9) - retains 20% CCF under F-IRB) |

**A-IRB Modelled CCF:** For A-IRB exposures, provide the bank's own modelled CCF estimate (0.0 to 1.5) in `ccf_modelled`. Retail IRB CCFs can exceed 100% due to additional drawdown behaviour. When populated and approach is A-IRB, this value takes precedence over the risk_type lookup.

**Example:**

```python
from datetime import date
import polars as pl

facilities = pl.DataFrame({
    "facility_reference": ["FAC_001", "FAC_002"],
    "product_type": ["rcf", "term_loan"],
    "book_code": ["CORP_LENDING", "CORP_LENDING"],
    "counterparty_reference": ["CORP_001", "CORP_002"],
    "value_date": [date(2024, 1, 15), date(2023, 6, 1)],
    "maturity_date": [date(2029, 1, 15), date(2028, 6, 1)],
    "currency": ["GBP", "GBP"],
    "limit": [10_000_000.0, 5_000_000.0],
    "committed": [True, True],
    "lgd": [None, None],  # Supervisory LGD used for F-IRB
    "beel": [None, None],
    "is_revolving": [True, False],
    "seniority": ["senior", "senior"],
    "risk_type": ["MR", "MR"],  # Medium risk - committed undrawn
    "ccf_modelled": [None, None],  # No modelled CCF (use regulatory)
})
```

---

## Loan Schema

**Purpose:** Defines drawn loan exposures (leaf nodes in exposure hierarchy). Loans represent actual credit usage under facilities.

**File:** `exposures/loans.parquet`

| Column | Type | Required | Description |
|--------|------|----------|-------------|
| `loan_reference` | `String` | Yes | Unique identifier for the loan |
| `product_type` | `String` | Yes | Product classification |
| `book_code` | `String` | Yes | Portfolio/book classification |
| `counterparty_reference` | `String` | Yes | Link to counterparty |
| `value_date` | `Date` | Yes | Loan origination date |
| `maturity_date` | `Date` | Yes | Loan maturity date |
| `currency` | `String` | Yes | ISO 4217 currency code |
| `drawn_amount` | `Float64` | Yes | Outstanding principal balance |
| `lgd` | `Float64` | No | Internal LGD estimate (A-IRB) |
| `beel` | `Float64` | No | Best estimate expected loss |
| `seniority` | `String` | Yes | `senior` or `subordinated` |
| `risk_type` | `String` | Yes | Off-balance sheet risk category (see Facility schema) |
| `ccf_modelled` | `Float64` | No | A-IRB modelled CCF (0.0-1.5) |

**Note:** For drawn loans, `risk_type` is typically `FR` (full_risk) since the amount is already drawn and CCF doesn't apply. However, the field is required for schema consistency across all exposure types.

**Example:**

```python
from datetime import date
import polars as pl

loans = pl.DataFrame({
    "loan_reference": ["LOAN_001", "LOAN_002", "LOAN_003"],
    "product_type": ["rcf_drawing", "term_loan", "term_loan"],
    "book_code": ["CORP_LENDING", "CORP_LENDING", "CORP_LENDING"],
    "counterparty_reference": ["CORP_001", "CORP_001", "CORP_002"],
    "value_date": [date(2024, 3, 1), date(2024, 4, 15), date(2023, 6, 1)],
    "maturity_date": [date(2029, 1, 15), date(2029, 1, 15), date(2028, 6, 1)],
    "currency": ["GBP", "GBP", "GBP"],
    "drawn_amount": [2_000_000.0, 1_500_000.0, 5_000_000.0],
    "lgd": [None, None, None],
    "beel": [None, None, None],
    "seniority": ["senior", "senior", "senior"],
    "risk_type": ["FR", "FR", "FR"],  # Full risk for drawn loans
    "ccf_modelled": [None, None, None],  # N/A for drawn amounts
})
```

---

## Contingent Schema

**Purpose:** Defines off-balance sheet commitments that require Credit Conversion Factor (CCF) application.

**File:** `exposures/contingents.parquet`

| Column | Type | Required | Description |
|--------|------|----------|-------------|
| `contingent_reference` | `String` | Yes | Unique identifier |
| `contract_type` | `String` | Yes | Type of contingent contract |
| `product_type` | `String` | Yes | Product classification |
| `book_code` | `String` | Yes | Portfolio/book classification |
| `counterparty_reference` | `String` | Yes | Link to counterparty |
| `value_date` | `Date` | Yes | Contract start date |
| `maturity_date` | `Date` | Yes | Contract expiry date |
| `currency` | `String` | Yes | ISO 4217 currency code |
| `nominal_amount` | `Float64` | Yes | Notional/nominal amount |
| `lgd` | `Float64` | No | Internal LGD estimate (A-IRB) |
| `beel` | `Float64` | No | Best estimate expected loss |
| `ccf_category` | `String` | Yes | Category for CCF lookup (legacy, see `risk_type`) |
| `seniority` | `String` | Yes | `senior` or `subordinated` |
| `risk_type` | `String` | Yes | Off-balance sheet risk category (see Facility schema) |
| `ccf_modelled` | `Float64` | No | A-IRB modelled CCF (0.0-1.5) |
| `is_short_term_trade_lc` | `Boolean` | No | Short-term trade LC for goods movement (Art. 166(9)) |

**Valid `ccf_category` values (legacy):**

| Category | SA CCF | Description |
|----------|--------|-------------|
| `full_risk` | 100% | Direct credit substitutes |
| `medium_risk` | 50% | Transaction-related contingencies |
| `medium_low_risk` | 20% | Short-term self-liquidating trade |
| `low_risk` | 0%/10% | Unconditionally cancellable |

**Note:** The `risk_type` column is the primary source for CCF determination. The `ccf_category` column is retained for backwards compatibility but `risk_type` takes precedence when both are present.

**Example:**

```python
from datetime import date
import polars as pl

contingents = pl.DataFrame({
    "contingent_reference": ["CONT_001", "CONT_002", "CONT_003"],
    "contract_type": ["standby_lc", "performance_guarantee", "documentary_lc"],
    "product_type": ["trade_finance", "guarantee", "import_lc"],
    "book_code": ["TRADE", "GUARANTEE", "TRADE"],
    "counterparty_reference": ["CORP_001", "CORP_002", "CORP_003"],
    "value_date": [date(2024, 1, 1), date(2024, 2, 1), date(2024, 3, 1)],
    "maturity_date": [date(2025, 1, 1), date(2025, 2, 1), date(2024, 6, 1)],
    "currency": ["GBP", "GBP", "GBP"],
    "nominal_amount": [500_000.0, 1_000_000.0, 250_000.0],
    "lgd": [None, None, None],
    "beel": [None, None, None],
    "ccf_category": ["full_risk", "medium_risk", "medium_low_risk"],
    "seniority": ["senior", "senior", "senior"],
    "risk_type": ["FR", "MR", "MLR"],  # FR=100%, MR=50%/75%, MLR=20%/75%
    "ccf_modelled": [None, None, None],  # No modelled CCF
    "is_short_term_trade_lc": [False, False, True],  # Third is Art. 166(9) exception
})
```

---

## Collateral Schema

**Purpose:** Defines collateral/security items used for Credit Risk Mitigation (CRM). Collateral can be linked at counterparty, facility, or loan level.

**File:** `collateral/collateral.parquet`

| Column | Type | Required | Description |
|--------|------|----------|-------------|
| `collateral_reference` | `String` | Yes | Unique identifier |
| `collateral_type` | `String` | Yes | Type of collateral (see valid values) |
| `currency` | `String` | Yes | ISO 4217 currency code |
| `maturity_date` | `Date` | No | Collateral maturity (if applicable) |
| `market_value` | `Float64` | Yes | Current market value |
| `nominal_value` | `Float64` | No | Nominal/face value |
| `beneficiary_type` | `String` | Yes | Level of allocation |
| `beneficiary_reference` | `String` | Yes | Reference to counterparty/facility/loan |
| `issuer_cqs` | `Int8` | No | CQS of issuer (for securities) |
| `issuer_type` | `String` | No | Issuer type (for haircut lookup) |
| `residual_maturity_years` | `Float64` | No | Residual maturity in years |
| `is_eligible_financial_collateral` | `Boolean` | No | Meets SA eligibility (CRR Art 197) |
| `is_eligible_irb_collateral` | `Boolean` | No | Meets IRB eligibility (CRR Art 199) |
| `valuation_date` | `Date` | No | Date of last valuation |
| `valuation_type` | `String` | No | `market`, `indexed`, `independent` |
| `property_type` | `String` | No | `residential` or `commercial` (RE only) |
| `property_ltv` | `Float64` | No | Loan-to-value ratio (RE only) |
| `is_income_producing` | `Boolean` | No | Material income dependence (CRE) |
| `is_adc` | `Boolean` | No | Acquisition/Development/Construction |
| `is_presold` | `Boolean` | No | ADC pre-sold to qualifying buyer |

**Valid `collateral_type` values:**

| Value | Description |
|-------|-------------|
| `cash` | Cash collateral (0% haircut) |
| `gold` | Gold collateral (15% haircut) |
| `bond` | Bond securities — haircut depends on `issuer_type`, `issuer_cqs`, and `residual_maturity_years` |
| `equity` | Equity securities |
| `real_estate` | Real estate — use `property_type` for residential/commercial classification |
| `receivables` | Trade receivables |
| `other_physical` | Other physical collateral |

**Valid `beneficiary_type` values:**

| Value | Description |
|-------|-------------|
| `counterparty` | Allocated at counterparty level (expands to all exposures) |
| `facility` | Allocated at facility level (expands to facility + child loans) |
| `loan` | Allocated directly to specific loan |
| `contingent` | Allocated directly to contingent |

**Example:**

```python
from datetime import date
import polars as pl

collateral = pl.DataFrame({
    "collateral_reference": ["COLL_001", "COLL_002"],
    "collateral_type": ["cash", "real_estate"],
    "currency": ["GBP", "GBP"],
    "maturity_date": [None, None],
    "market_value": [1_000_000.0, 500_000.0],
    "nominal_value": [1_000_000.0, None],
    "beneficiary_type": ["counterparty", "loan"],
    "beneficiary_reference": ["CORP_001", "LOAN_003"],
    "issuer_cqs": [None, None],
    "issuer_type": [None, None],
    "residual_maturity_years": [None, None],
    "is_eligible_financial_collateral": [True, False],
    "is_eligible_irb_collateral": [True, True],
    "valuation_date": [date(2024, 12, 31), date(2024, 11, 15)],
    "valuation_type": ["market", "independent"],
    "property_type": [None, "residential"],
    "property_ltv": [None, 0.65],
    "is_income_producing": [None, False],
    "is_adc": [None, False],
    "is_presold": [None, None],
})
```

---

## Guarantee Schema

**Purpose:** Defines guarantee protection for Credit Risk Mitigation using the substitution approach.

**File:** `guarantee/guarantee.parquet`

| Column | Type | Required | Description |
|--------|------|----------|-------------|
| `guarantee_reference` | `String` | Yes | Unique identifier |
| `guarantee_type` | `String` | Yes | Type of guarantee |
| `guarantor` | `String` | Yes | Guarantor counterparty reference |
| `currency` | `String` | Yes | ISO 4217 currency code |
| `maturity_date` | `Date` | No | Guarantee expiry date |
| `amount_covered` | `Float64` | Yes | Amount covered by guarantee |
| `percentage_covered` | `Float64` | No | Percentage of exposure covered |
| `beneficiary_type` | `String` | Yes | Level of allocation |
| `beneficiary_reference` | `String` | Yes | Reference to counterparty/facility/loan |

**Valid `guarantee_type` values:**

| Value | Description |
|-------|-------------|
| `guarantee` | Standard guarantee |
| `credit_derivative` | Credit derivative protection |
| `counter_guarantee` | Counter-guarantee |

**Example:**

```python
from datetime import date
import polars as pl

guarantees = pl.DataFrame({
    "guarantee_reference": ["GUAR_001"],
    "guarantee_type": ["guarantee"],
    "guarantor": ["SOV_001"],  # UK Treasury guaranteeing
    "currency": ["GBP"],
    "maturity_date": [date(2030, 12, 31)],
    "amount_covered": [2_000_000.0],
    "percentage_covered": [1.0],
    "beneficiary_type": ["counterparty"],
    "beneficiary_reference": ["CORP_001"],
})
```

---

## Provision Schema

**Purpose:** Defines IFRS 9 provisions/impairments for EAD reduction and IRB expected loss comparison.

**File:** `provision/provision.parquet`

| Column | Type | Required | Description |
|--------|------|----------|-------------|
| `provision_reference` | `String` | Yes | Unique identifier |
| `provision_type` | `String` | Yes | `SCRA` (specific) or `GCRA` (general) |
| `ifrs9_stage` | `Int8` | No | IFRS 9 stage (1, 2, or 3) |
| `currency` | `String` | Yes | ISO 4217 currency code |
| `amount` | `Float64` | Yes | Provision amount |
| `as_of_date` | `Date` | Yes | Provision as-of date |
| `beneficiary_type` | `String` | Yes | Level of allocation |
| `beneficiary_reference` | `String` | Yes | Reference to counterparty/facility/loan |

**Valid `provision_type` values:**

| Value | Description | Usage |
|-------|-------------|-------|
| `SCRA` | Specific Credit Risk Adjustment | Reduces exposure value; affects defaulted RW |
| `GCRA` | General Credit Risk Adjustment | Reduces exposure value |

**Valid `ifrs9_stage` values:**

| Stage | Description | ECL Type |
|-------|-------------|----------|
| `1` | Performing | 12-month ECL |
| `2` | Performing, significant increase in credit risk | Lifetime ECL |
| `3` | Non-performing/credit-impaired | Lifetime ECL |

**Example:**

```python
from datetime import date
import polars as pl

provisions = pl.DataFrame({
    "provision_reference": ["PROV_001", "PROV_002"],
    "provision_type": ["SCRA", "GCRA"],
    "ifrs9_stage": [1, 2],
    "currency": ["GBP", "GBP"],
    "amount": [50_000.0, 100_000.0],
    "as_of_date": [date(2024, 12, 31), date(2024, 12, 31)],
    "beneficiary_type": ["loan", "counterparty"],
    "beneficiary_reference": ["LOAN_001", "CORP_002"],
})
```

---

## Rating Schema

**Purpose:** Defines internal and external credit ratings for risk weight determination.

**File:** `ratings/ratings.parquet`

| Column | Type | Required | Description |
|--------|------|----------|-------------|
| `rating_reference` | `String` | Yes | Unique identifier |
| `counterparty_reference` | `String` | Yes | Link to counterparty |
| `rating_type` | `String` | Yes | `internal` or `external` |
| `rating_agency` | `String` | Yes | Rating source |
| `rating_value` | `String` | Yes | Rating value (e.g., `AAA`, `Aa1`) |
| `cqs` | `Int8` | Yes | Credit Quality Step (1-6) |
| `pd` | `Float64` | No | Probability of Default (internal ratings) |
| `rating_date` | `Date` | Yes | Rating as-of date |
| `is_solicited` | `Boolean` | No | Whether rating was solicited |

**Valid `rating_agency` values:**

| Value | Description |
|-------|-------------|
| `internal` | Internal rating system |
| `SP` | Standard & Poor's |
| `MOODYS` | Moody's |
| `FITCH` | Fitch Ratings |
| `DBRS` | DBRS Morningstar |

**CQS Mapping:**

| CQS | S&P/Fitch | Moody's | Sovereign RW | Institution RW | Corporate RW |
|-----|-----------|---------|--------------|----------------|--------------|
| 1 | AAA to AA- | Aaa to Aa3 | 0% | 20% | 20% |
| 2 | A+ to A- | A1 to A3 | 20% | 30%* | 50% |
| 3 | BBB+ to BBB- | Baa1 to Baa3 | 50% | 50% | 100% |
| 4 | BB+ to BB- | Ba1 to Ba3 | 100% | 100% | 100% |
| 5 | B+ to B- | B1 to B3 | 100% | 100% | 150% |
| 6 | CCC+ and below | Caa1 and below | 150% | 150% | 150% |

*UK deviation: CQS 2 institutions get 30% RW (not 50%)

**Example:**

```python
from datetime import date
import polars as pl

ratings = pl.DataFrame({
    "rating_reference": ["RAT_001", "RAT_002"],
    "counterparty_reference": ["CORP_001", "SOV_001"],
    "rating_type": ["external", "external"],
    "rating_agency": ["SP", "SP"],
    "rating_value": ["BBB+", "AA"],
    "cqs": [3, 1],
    "pd": [None, None],
    "rating_date": [date(2024, 6, 15), date(2024, 1, 1)],
    "is_solicited": [True, True],
})
```

---

## FX Rates Schema

**Purpose:** Defines FX (foreign exchange) rates for converting exposure amounts from their original currencies to a reporting currency. This enables consistent RWA calculations across multi-currency portfolios.

**File:** `fx_rates/fx_rates.parquet`

| Column | Type | Required | Description |
|--------|------|----------|-------------|
| `currency_from` | `String` | Yes | Source currency code (ISO 4217) |
| `currency_to` | `String` | Yes | Target currency code (ISO 4217) |
| `rate` | `Float64` | Yes | Conversion multiplier: `target_amount = source_amount * rate` |

**Usage:**
- Rates should be provided for all currency pairs needed (source → target)
- Include identity rates (e.g., GBP→GBP = 1.0) for the target currency
- The target currency should match `CalculationConfig.base_currency`

**Converted Fields:**
- Exposures: `drawn_amount`, `undrawn_amount`, `nominal_amount`
- Collateral: `market_value`, `nominal_value`
- Guarantees: `amount_covered`
- Provisions: `amount`

**Audit Trail:**
After conversion, the following columns are added:
- `original_currency` - Currency before conversion
- `original_amount` - Amount before conversion (drawn + nominal)
- `fx_rate_applied` - Rate used (null if no conversion needed)

**Example:**

```python
from datetime import date
import polars as pl

fx_rates = pl.DataFrame({
    "currency_from": ["GBP", "USD", "EUR", "JPY", "CHF"],
    "currency_to": ["GBP", "GBP", "GBP", "GBP", "GBP"],
    "rate": [1.0, 0.79, 0.88, 0.0053, 0.89],
})
```

**Behaviour:**
- **Missing rates:** Exposures in currencies without rates retain original values; `fx_rate_applied` is null
- **FX disabled:** Set `apply_fx_conversion=False` in `CalculationConfig` to skip conversion
- **No FX file:** If `fx_rates.parquet` is not provided, no conversion occurs

---

## Specialised Lending Schema

**Purpose:** Defines specialised lending exposures for slotting approach treatment (CRE33).

| Column | Type | Required | Description |
|--------|------|----------|-------------|
| `exposure_reference` | `String` | Yes | Links to facility/loan reference |
| `sl_type` | `String` | Yes | Type of specialised lending |
| `slotting_category` | `String` | Yes | Slotting category |
| `remaining_maturity_years` | `Float64` | Yes | Remaining maturity in years |
| `is_hvcre` | `Boolean` | No | High-volatility commercial real estate |

**Valid `sl_type` values:**

| Value | Description |
|-------|-------------|
| `project_finance` | Project finance (PF) |
| `object_finance` | Object finance (OF) |
| `commodities_finance` | Commodities finance (CF) |
| `ipre` | Income-producing real estate |

**Valid `slotting_category` values:**

| Category | RW (>=2.5yr) | RW (<2.5yr) | Description |
|----------|--------------|-------------|-------------|
| `strong` | 70% | 50% | Excellent risk profile |
| `good` | 90% | 70% | Good risk profile |
| `satisfactory` | 115% | 115% | Acceptable risk profile |
| `weak` | 250% | 250% | Higher risk profile |
| `default` | 0% | 0% | In default (provisions apply) |

---

## Equity Exposure Schema

**Purpose:** Defines equity holdings (SA only under Basel 3.1, IRB approaches withdrawn).

| Column | Type | Required | Description |
|--------|------|----------|-------------|
| `exposure_reference` | `String` | Yes | Unique identifier |
| `counterparty_reference` | `String` | Yes | Link to counterparty |
| `equity_type` | `String` | Yes | Type of equity exposure |
| `currency` | `String` | Yes | ISO 4217 currency code |
| `carrying_value` | `Float64` | Yes | Balance sheet value |
| `fair_value` | `Float64` | No | Mark-to-market value |
| `is_speculative` | `Boolean` | No | Speculative unlisted equity |
| `is_exchange_traded` | `Boolean` | No | Listed on recognised exchange |
| `is_government_supported` | `Boolean` | No | Government-supported programme |
| `is_significant_investment` | `Boolean` | No | >10% of CET1 |

**Valid `equity_type` values:**

| Value | Risk Weight | Description |
|-------|-------------|-------------|
| `listed` | 100% | Exchange-traded equities |
| `unlisted` | 250% | Unlisted equities |
| `private_equity` | 250% | Private equity investments |
| `speculative` | 400% | Speculative unlisted |
| `ciu` | Look-through | Collective investment undertakings |

---

## Facility Mapping Schema

**Purpose:** Defines parent-child relationships between facilities, loans, and contingents.

**File:** `exposures/facility_mapping.parquet`

| Column | Type | Required | Description |
|--------|------|----------|-------------|
| `parent_facility_reference` | `String` | Yes | Parent facility reference |
| `child_reference` | `String` | Yes | Child facility/loan/contingent reference |
| `child_type` | `String` | Yes | `facility`, `loan`, or `contingent` |

**Example:**

```python
import polars as pl

facility_mapping = pl.DataFrame({
    "parent_facility_reference": ["FAC_001", "FAC_001", "FAC_001"],
    "child_reference": ["LOAN_001", "LOAN_002", "FAC_001A"],
    "child_type": ["loan", "loan", "facility"],
})
```

---

## Org Mapping Schema

**Purpose:** Defines organisation hierarchy for rating and turnover inheritance.

**File:** `mapping/org_mapping.parquet`

| Column | Type | Required | Description |
|--------|------|----------|-------------|
| `parent_counterparty_reference` | `String` | Yes | Parent counterparty reference |
| `child_counterparty_reference` | `String` | Yes | Child counterparty reference |

**Example:**

```python
import polars as pl

org_mapping = pl.DataFrame({
    "parent_counterparty_reference": ["CORP_PARENT", "CORP_PARENT"],
    "child_counterparty_reference": ["CORP_001", "CORP_002"],
})
```

---

## Lending Mapping Schema

**Purpose:** Defines lending groups for retail threshold aggregation.

**File:** `mapping/lending_mapping.parquet`

| Column | Type | Required | Description |
|--------|------|----------|-------------|
| `parent_counterparty_reference` | `String` | Yes | Lending group lead reference |
| `child_counterparty_reference` | `String` | Yes | Member counterparty reference |

Exposures are aggregated to the group level for retail eligibility (threshold: EUR 1m / GBP 880k).

---

## Data Preparation Checklist

Before running the calculator, verify your data meets these requirements:

- [ ] All required files present in expected locations
- [ ] Column names match schema exactly (case-sensitive)
- [ ] Data types match expected types
- [ ] All required columns have non-null values
- [ ] Reference columns have valid foreign key relationships
- [ ] Dates are in `YYYY-MM-DD` format
- [ ] Currency codes are valid ISO 4217
- [ ] Country codes are valid ISO 3166-1 alpha-2
- [ ] Numeric amounts are non-negative where expected
- [ ] PD values are in range [0, 1]
- [ ] LGD values are in range [0, 1.25]

See [Data Validation Guide](data-validation.md) for validation functions and troubleshooting.

---

## Next Steps

- [Data Validation Guide](data-validation.md) - Validation rules and error handling
- [Intermediate Schemas](intermediate-schemas.md) - Pipeline intermediate data
- [Output Schemas](output-schemas.md) - Calculation results
