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

- Facility undrawn amount = max(facility_limit - sum(drawn_amounts), 0)
- Supports multiple exposure types under a single facility
- Pro-rata allocation of facility-level attributes

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
