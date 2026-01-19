# Intermediate Schemas

This page documents the schemas for intermediate data structures used during calculation.

## Resolved Hierarchy Schema

After hierarchy resolution, exposures include resolved parent information.

| Column | Type | Description |
|--------|------|-------------|
| `counterparty_id` | `Utf8` | Counterparty identifier |
| `ultimate_parent_id` | `Utf8` | Ultimate parent in hierarchy |
| `parent_chain` | `List[Utf8]` | List of parent IDs |
| `hierarchy_level` | `Int32` | Depth in hierarchy |
| `inherited_rating` | `Utf8` | Rating (own or inherited) |
| `inherited_cqs` | `Int32` | CQS (own or inherited) |
| `inherited_pd` | `Float64` | PD (own or inherited) |
| `group_total_exposure` | `Float64` | Total exposure to group |
| `lending_group_id` | `Utf8` | Retail lending group |
| `lending_group_exposure` | `Float64` | Lending group total |

## Classified Exposure Schema

After classification, each exposure has regulatory attributes.

| Column | Type | Description |
|--------|------|-------------|
| `exposure_id` | `Utf8` | Unique exposure identifier |
| `counterparty_id` | `Utf8` | Counterparty identifier |
| `facility_id` | `Utf8` | Facility identifier |
| `loan_id` | `Utf8` | Loan identifier (if applicable) |
| `exposure_class` | `Utf8` | Regulatory exposure class |
| `approach_type` | `Utf8` | SA/FIRB/AIRB/SLOTTING |
| `is_defaulted` | `Boolean` | Default indicator |
| `gross_exposure` | `Float64` | Gross carrying amount |
| `undrawn_amount` | `Float64` | Undrawn commitment |
| `ccf` | `Float64` | Credit conversion factor |
| `ead` | `Float64` | Exposure at default |
| `cqs` | `Int32` | Credit quality step |
| `pd` | `Float64` | Probability of default |
| `lgd` | `Float64` | Loss given default |
| `effective_maturity` | `Float64` | Effective maturity (years) |
| `turnover` | `Float64` | Counterparty turnover |
| `is_sme` | `Boolean` | SME indicator |
| `is_infrastructure` | `Boolean` | Infrastructure indicator |

**Valid `exposure_class` values:**
- `SOVEREIGN`
- `INSTITUTION`
- `CORPORATE`
- `CORPORATE_SME`
- `RETAIL_MORTGAGE`
- `RETAIL_QRRE`
- `RETAIL_OTHER`
- `SPECIALISED_LENDING`
- `EQUITY`
- `DEFAULTED`
- `PSE`
- `MDB`
- `RGLA`
- `OTHER`

**Valid `approach_type` values:**
- `SA` - Standardised Approach
- `FIRB` - Foundation IRB
- `AIRB` - Advanced IRB
- `SLOTTING` - Slotting Approach

## CRM Adjusted Schema

After CRM processing, exposures include mitigation adjustments.

| Column | Type | Description |
|--------|------|-------------|
| `exposure_id` | `Utf8` | Exposure identifier |
| ... | ... | (all classified exposure columns) |
| `provision_amount` | `Float64` | Applied provision |
| `provision_type` | `Utf8` | SCRA or GCRA |
| `collateral_value` | `Float64` | Total collateral value |
| `collateral_type` | `Utf8` | Primary collateral type |
| `collateral_haircut` | `Float64` | Applied haircut |
| `currency_mismatch_haircut` | `Float64` | FX mismatch haircut |
| `net_collateral_value` | `Float64` | Collateral after haircuts |
| `guaranteed_amount` | `Float64` | Guaranteed portion |
| `guarantor_id` | `Utf8` | Guarantor identifier |
| `guarantor_type` | `Utf8` | Guarantor type |
| `guarantor_cqs` | `Int32` | Guarantor CQS |
| `guarantor_rw` | `Float64` | Guarantor risk weight |
| `maturity_mismatch_factor` | `Float64` | Maturity mismatch adj |
| `net_ead` | `Float64` | EAD after CRM |
| `net_ead_unsecured` | `Float64` | Unsecured portion |
| `net_ead_guaranteed` | `Float64` | Guaranteed portion |

## Specialised Lending Schema

For slotting approach exposures.

| Column | Type | Description |
|--------|------|-------------|
| `exposure_id` | `Utf8` | Exposure identifier |
| ... | ... | (all CRM adjusted columns) |
| `lending_type` | `Utf8` | Type of specialised lending |
| `slotting_category` | `Utf8` | Strong/Good/Satisfactory/Weak |
| `is_pre_operational` | `Boolean` | Pre-operational phase |
| `is_hvcre` | `Boolean` | High volatility CRE |

**Valid `lending_type` values:**
- `PROJECT_FINANCE`
- `OBJECT_FINANCE`
- `COMMODITIES_FINANCE`
- `IPRE` - Income-producing real estate
- `HVCRE` - High volatility CRE

**Valid `slotting_category` values:**
- `STRONG`
- `GOOD`
- `SATISFACTORY`
- `WEAK`
- `DEFAULT`

## Transformation Examples

### Hierarchy Resolution

```python
# Input
counterparties = pl.DataFrame({
    "counterparty_id": ["C001", "C002"],
    "parent_counterparty_id": [None, "C001"],
    "rating": [None, "A"],
})

# After resolution
resolved = pl.DataFrame({
    "counterparty_id": ["C001", "C002"],
    "ultimate_parent_id": ["C001", "C001"],
    "hierarchy_level": [0, 1],
    "inherited_rating": ["A", "A"],  # C001 inherits from C002
})
```

### Classification

```python
# Input
exposure = {
    "counterparty_type": "CORPORATE",
    "turnover": 30_000_000,  # EUR
    "total_exposure": 5_000_000,
}

# After classification
classified = {
    "exposure_class": "CORPORATE_SME",  # turnover < EUR 50m
    "approach_type": "SA",
    "is_sme": True,
}
```

### CRM Application

```python
# Input
exposure = {"ead": 10_000_000}
collateral = {"value": 8_000_000, "type": "GOVERNMENT_BOND", "maturity": 3}

# After CRM
crm_adjusted = {
    "collateral_value": 8_000_000,
    "collateral_haircut": 0.02,  # 2% for 1-5yr govt bond
    "net_collateral_value": 7_840_000,
    "net_ead": 2_160_000,  # 10m - 7.84m
}
```

## Next Steps

- [Output Schemas](output-schemas.md)
- [Regulatory Tables](regulatory-tables.md)
- [Pipeline Architecture](../architecture/pipeline.md)
