# Input Schemas

This page documents the schemas for input data files.

## Counterparty Schema

**File:** `counterparties.parquet`

| Column | Type | Required | Description |
|--------|------|----------|-------------|
| `counterparty_id` | `Utf8` | Yes | Unique identifier |
| `counterparty_name` | `Utf8` | Yes | Legal name |
| `counterparty_type` | `Utf8` | Yes | SOVEREIGN/INSTITUTION/CORPORATE/INDIVIDUAL |
| `country_code` | `Utf8` | Yes | ISO 3166-1 alpha-2 code |
| `annual_turnover` | `Float64` | No | Annual turnover in EUR |
| `total_assets` | `Float64` | No | Total assets in EUR |
| `is_sme` | `Boolean` | No | Explicit SME flag |
| `parent_counterparty_id` | `Utf8` | No | Parent for hierarchy |
| `sector_code` | `Utf8` | No | Industry sector |
| `is_financial_institution` | `Boolean` | No | Financial institution flag |
| `is_public_sector` | `Boolean` | No | Public sector entity flag |

**Valid `counterparty_type` values:**
- `SOVEREIGN` - Governments, central banks
- `INSTITUTION` - Banks, investment firms
- `CORPORATE` - Non-financial companies
- `INDIVIDUAL` - Natural persons
- `PSE` - Public sector entities
- `MDB` - Multilateral development banks

## Facility Schema

**File:** `facilities.parquet`

| Column | Type | Required | Description |
|--------|------|----------|-------------|
| `facility_id` | `Utf8` | Yes | Unique identifier |
| `counterparty_id` | `Utf8` | Yes | Link to counterparty |
| `facility_type` | `Utf8` | Yes | RCF/TERM/MORTGAGE/OVERDRAFT/etc. |
| `committed_amount` | `Float64` | Yes | Total commitment |
| `drawn_amount` | `Float64` | Yes | Current utilization |
| `currency` | `Utf8` | Yes | ISO 4217 currency code |
| `start_date` | `Date` | Yes | Facility start date |
| `maturity_date` | `Date` | Yes | Final maturity date |
| `is_unconditionally_cancellable` | `Boolean` | Yes | For CCF determination |
| `is_committed` | `Boolean` | Yes | Committed vs uncommitted |
| `interest_rate` | `Float64` | No | Interest rate |
| `is_secured` | `Boolean` | No | Secured facility flag |
| `security_type` | `Utf8` | No | Type of security |

**Valid `facility_type` values:**
- `RCF` - Revolving credit facility
- `TERM` - Term loan
- `MORTGAGE` - Mortgage loan
- `OVERDRAFT` - Overdraft facility
- `CREDIT_CARD` - Credit card
- `TRADE_FINANCE` - Trade finance facility
- `GUARANTEE` - Guarantee facility
- `PROJECT_FINANCE` - Project finance

## Loan Schema

**File:** `loans.parquet`

| Column | Type | Required | Description |
|--------|------|----------|-------------|
| `loan_id` | `Utf8` | Yes | Unique identifier |
| `facility_id` | `Utf8` | Yes | Link to facility |
| `principal_amount` | `Float64` | Yes | Outstanding principal |
| `currency` | `Utf8` | Yes | ISO 4217 currency code |
| `origination_date` | `Date` | Yes | Loan origination date |
| `maturity_date` | `Date` | Yes | Loan maturity date |
| `is_defaulted` | `Boolean` | Yes | Default indicator |
| `days_past_due` | `Int32` | Yes | Days past due count |
| `interest_rate` | `Float64` | No | Interest rate |
| `ltv` | `Float64` | No | Loan-to-value ratio |

## Contingent Schema

**File:** `contingents.parquet`

| Column | Type | Required | Description |
|--------|------|----------|-------------|
| `contingent_id` | `Utf8` | Yes | Unique identifier |
| `counterparty_id` | `Utf8` | Yes | Link to counterparty |
| `contingent_type` | `Utf8` | Yes | Type of contingent |
| `notional_amount` | `Float64` | Yes | Notional amount |
| `currency` | `Utf8` | Yes | ISO 4217 currency code |
| `maturity_date` | `Date` | Yes | Expiry date |

**Valid `contingent_type` values:**
- `DOCUMENTARY_CREDIT` - Trade documentary credit
- `STANDBY_LC` - Standby letter of credit
- `GUARANTEE_ISSUED` - Guarantee issued
- `ACCEPTANCE` - Acceptance
- `NIF` - Note issuance facility
- `COMMITMENT` - Undrawn commitment

## Collateral Schema

**File:** `collateral.parquet`

| Column | Type | Required | Description |
|--------|------|----------|-------------|
| `collateral_id` | `Utf8` | Yes | Unique identifier |
| `counterparty_id` | `Utf8` | No* | Counterparty-level allocation |
| `facility_id` | `Utf8` | No* | Facility-level allocation |
| `loan_id` | `Utf8` | No* | Loan-level allocation |
| `collateral_type` | `Utf8` | Yes | Type of collateral |
| `value` | `Float64` | Yes | Current market value |
| `currency` | `Utf8` | Yes | ISO 4217 currency code |
| `valuation_date` | `Date` | Yes | Date of valuation |
| `issuer_cqs` | `Int32` | No | CQS of issuer (for bonds) |
| `residual_maturity_years` | `Float64` | No | Residual maturity |

*At least one of `counterparty_id`, `facility_id`, or `loan_id` must be provided.

**Valid `collateral_type` values:**
- `CASH` - Cash collateral
- `GOVERNMENT_BOND` - Government/sovereign bonds
- `CORPORATE_BOND` - Corporate bonds
- `COVERED_BOND` - Covered bonds
- `EQUITY_MAIN_INDEX` - Main index equities
- `EQUITY_OTHER` - Other listed equities
- `RESIDENTIAL_REAL_ESTATE` - Residential property
- `COMMERCIAL_REAL_ESTATE` - Commercial property
- `RECEIVABLES` - Trade receivables
- `OTHER_PHYSICAL` - Other physical collateral
- `GOLD` - Gold collateral

## Guarantee Schema

**File:** `guarantees.parquet`

| Column | Type | Required | Description |
|--------|------|----------|-------------|
| `guarantee_id` | `Utf8` | Yes | Unique identifier |
| `counterparty_id` | `Utf8` | Yes | Protected counterparty |
| `guarantor_id` | `Utf8` | Yes | Guarantor counterparty ID |
| `guaranteed_amount` | `Float64` | Yes | Amount guaranteed |
| `currency` | `Utf8` | Yes | ISO 4217 currency code |
| `maturity_date` | `Date` | Yes | Guarantee expiry date |
| `guarantor_type` | `Utf8` | Yes | Type of guarantor |
| `guarantor_cqs` | `Int32` | No | CQS of guarantor |
| `is_unconditional` | `Boolean` | Yes | Unconditional guarantee |
| `is_irrevocable` | `Boolean` | Yes | Irrevocable guarantee |

**Valid `guarantor_type` values:**
- `SOVEREIGN` - Government guarantor
- `INSTITUTION` - Bank guarantor
- `CORPORATE` - Corporate guarantor
- `PARENT` - Parent company guarantor

## Provision Schema

**File:** `provisions.parquet`

| Column | Type | Required | Description |
|--------|------|----------|-------------|
| `provision_id` | `Utf8` | Yes | Unique identifier |
| `counterparty_id` | `Utf8` | No* | Counterparty-level |
| `facility_id` | `Utf8` | No* | Facility-level |
| `loan_id` | `Utf8` | No* | Loan-level |
| `provision_type` | `Utf8` | Yes | SCRA or GCRA |
| `amount` | `Float64` | Yes | Provision amount |
| `currency` | `Utf8` | Yes | ISO 4217 currency code |
| `ifrs_stage` | `Utf8` | No | IFRS 9 stage |

*At least one of `counterparty_id`, `facility_id`, or `loan_id` must be provided.

**Valid `provision_type` values:**
- `SCRA` - Specific Credit Risk Adjustment
- `GCRA` - General Credit Risk Adjustment

**Valid `ifrs_stage` values:**
- `STAGE_1` - Performing, 12-month ECL
- `STAGE_2` - Performing, lifetime ECL
- `STAGE_3` - Non-performing, lifetime ECL

## Rating Schema

**File:** `ratings.parquet`

| Column | Type | Required | Description |
|--------|------|----------|-------------|
| `rating_id` | `Utf8` | Yes | Unique identifier |
| `counterparty_id` | `Utf8` | Yes | Link to counterparty |
| `rating_agency` | `Utf8` | Yes | Rating agency |
| `rating` | `Utf8` | Yes | Rating value |
| `rating_date` | `Date` | Yes | Rating as-of date |
| `rating_type` | `Utf8` | Yes | Long-term or short-term |
| `pd` | `Float64` | No | Associated PD (internal) |
| `lgd` | `Float64` | No | Associated LGD (A-IRB) |

**Valid `rating_agency` values:**
- `SP` - Standard & Poor's
- `MOODYS` - Moody's
- `FITCH` - Fitch Ratings
- `INTERNAL` - Internal rating

## Organization Mapping Schema

**File:** `org_mapping.parquet`

| Column | Type | Required | Description |
|--------|------|----------|-------------|
| `child_id` | `Utf8` | Yes | Child counterparty ID |
| `parent_id` | `Utf8` | Yes | Parent counterparty ID |
| `relationship_type` | `Utf8` | Yes | Type of relationship |
| `ownership_percentage` | `Float64` | No | Ownership percentage |

**Valid `relationship_type` values:**
- `SUBSIDIARY` - Parent-subsidiary
- `BRANCH` - Branch relationship
- `ASSOCIATED` - Associated company

## Lending Mapping Schema

**File:** `lending_mapping.parquet`

| Column | Type | Required | Description |
|--------|------|----------|-------------|
| `member_id` | `Utf8` | Yes | Member counterparty ID |
| `group_id` | `Utf8` | Yes | Lending group ID |
| `is_primary` | `Boolean` | Yes | Primary borrower flag |

## Example Data

### Counterparty Example

```python
import polars as pl

counterparties = pl.DataFrame({
    "counterparty_id": ["C001", "C002", "C003"],
    "counterparty_name": ["Acme Corp", "UK Treasury", "John Smith"],
    "counterparty_type": ["CORPORATE", "SOVEREIGN", "INDIVIDUAL"],
    "country_code": ["GB", "GB", "GB"],
    "annual_turnover": [25_000_000.0, None, None],
    "is_sme": [True, None, None],
})
```

### Facility Example

```python
facilities = pl.DataFrame({
    "facility_id": ["F001", "F002"],
    "counterparty_id": ["C001", "C003"],
    "facility_type": ["RCF", "MORTGAGE"],
    "committed_amount": [5_000_000.0, 250_000.0],
    "drawn_amount": [2_000_000.0, 250_000.0],
    "currency": ["GBP", "GBP"],
    "start_date": [date(2024, 1, 1), date(2023, 6, 1)],
    "maturity_date": [date(2029, 1, 1), date(2053, 6, 1)],
    "is_unconditionally_cancellable": [False, False],
    "is_committed": [True, True],
})
```

## Next Steps

- [Intermediate Schemas](intermediate-schemas.md)
- [Output Schemas](output-schemas.md)
- [Regulatory Tables](regulatory-tables.md)
