# Hierarchy & Classification Specification

Counterparty hierarchy resolution, rating inheritance, and exposure class determination.

---

## Counterparty Hierarchy

### Organisation Mappings

The calculator resolves parent-child relationships between counterparties using `org_mappings`:

- Child counterparties inherit ratings from their parent when they lack their own
- The hierarchy is traversed upward until a rated entity is found

### Lending Group Aggregation

Lending groups aggregate exposure across related counterparties for threshold calculations (e.g., SME turnover, retail exposure limits).

- Members are defined via `lending_mappings`
- The parent counterparty is automatically included as a member
- Duplicate membership is resolved (a counterparty appearing in multiple groups keeps only the first assignment)
- Residential property exposures are excluded from retail aggregation per CRR Art. 123(c)

### Facility-to-Exposure Mapping

The `facility_mappings` table links facilities to their underlying exposures (loans and contingents):

- Facility undrawn amount = `max(facility_limit - sum(drawn_amounts), 0)`
- Supports multiple exposure types under a single facility
- Pro-rata allocation of facility-level attributes

### Multi-Level Facility Hierarchies

Facilities can form their own hierarchies (e.g., a master facility with sub-facilities beneath it). The resolver handles this via **facility root lookup** — an iterative traversal that mirrors the counterparty hierarchy pattern:

- **Facility-to-facility edges** are identified from `facility_mappings` where `child_type = "facility"`
- The hierarchy is traversed upward (up to 10 levels) to find the **root facility** for each sub-facility
- Output columns: `child_facility_reference`, `root_facility_reference`, `facility_hierarchy_depth`

#### Undrawn Amount Aggregation

For multi-level facility hierarchies, drawn amounts from loans under sub-facilities are aggregated up to the root facility:

```
Root Facility (limit = 1,000,000)
├── Sub-Facility A
│   ├── Loan 1 (drawn = 200,000)
│   └── Loan 2 (drawn = 100,000)
└── Sub-Facility B
    └── Loan 3 (drawn = 150,000)

Root undrawn = 1,000,000 - (200,000 + 100,000 + 150,000) = 550,000
```

Key rules:

- **Root/standalone facilities** produce undrawn exposure records
- **Sub-facilities are excluded** from producing their own undrawn records (avoids double-counting)
- Negative drawn amounts are clamped to zero before aggregation (negative balances do not increase headroom)
- Only facilities with `undrawn_amount > 0` generate exposure records

#### Type Column Handling

The `facility_mappings` table may use different column names for the child type discriminator:

| Column Present | Behaviour |
|---------------|-----------|
| `child_type` | Used to filter loan vs facility children (preferred) |
| `node_type` | Fallback — same filtering logic |
| Neither | No facility hierarchy traversal; all mappings treated as loan mappings |

## Exposure Classification

### Entity Type to Exposure Class

Counterparty entity type determines the base SA exposure class:

| Entity Type | Exposure Class |
|-------------|---------------|
| CENTRAL_GOVERNMENT | CENTRAL_GOVT_CENTRAL_BANK |
| REGIONAL_GOVERNMENT | CENTRAL_GOVT_CENTRAL_BANK |
| PUBLIC_SECTOR_ENTITY | CENTRAL_GOVT_CENTRAL_BANK |
| MULTILATERAL_DEVELOPMENT_BANK | CENTRAL_GOVT_CENTRAL_BANK |
| INTERNATIONAL_ORGANISATION | CENTRAL_GOVT_CENTRAL_BANK |
| CREDIT_INSTITUTION | INSTITUTION |
| INVESTMENT_FIRM | INSTITUTION |
| CORPORATE | CORPORATE |
| INDIVIDUAL | Retail (if qualifying) |

### SME Detection

Corporate counterparties are reclassified as CORPORATE_SME when:

- Group turnover < EUR 50m (GBP converted to EUR at configured rate)

### Retail Qualification

Individual counterparties qualify for retail treatment when:

- **CRR:** Aggregate exposure < EUR 1m (approx. GBP 880k at default rate)
- **Basel 3.1:** Aggregate exposure < GBP 880k
- **QRRE limit:** Individual exposure ≤ EUR 100k / GBP 100k

If retail thresholds are breached, the exposure is reclassified as CORPORATE.

### Defaulted Exposures

Exposures flagged with a default status are identified and tracked throughout the calculation. Defaulted status affects risk weighting (e.g., 150% SA risk weight for defaulted unsecured).

## Approach Assignment

### Dual-Approach Split

Based on IRB permissions in the configuration, exposures are routed to:

1. **SA** - Standardised Approach
2. **IRB** - Foundation IRB or Advanced IRB
3. **Slotting** - Specialised lending categories
4. **Equity** - Equity exposures (pass-through, no CRM applied)

### FX Conversion

All monetary values are converted to the base currency (GBP) using provided FX rates before calculation.
