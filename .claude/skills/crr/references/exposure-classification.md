# CRR Exposure Classification

Quick-reference for entity type to exposure class mapping and hierarchy rules.

**Regulatory Reference:** CRR Articles 112, 147

---

## Entity Type to Exposure Class Mapping

| Entity Type(s) | Exposure Class |
|----------------|---------------|
| `sovereign`, `central_bank` | CENTRAL_GOVT_CENTRAL_BANK |
| `rgla_sovereign`, `rgla_institution` | RGLA |
| `pse_sovereign`, `pse_institution` | PSE |
| `mdb`, `international_org` | MDB |
| `institution`, `bank`, `ccp`, `financial_institution` | INSTITUTION |
| `corporate`, `company` | CORPORATE |
| `individual`, `retail` | RETAIL_OTHER (if qualifying) |
| `specialised_lending` | SPECIALISED_LENDING |
| `equity` | EQUITY |

## SME Detection

Corporate counterparties reclassified as CORPORATE_SME when group turnover < EUR 50m.

## Retail Qualification

| Threshold | CRR | Basel 3.1 |
|-----------|-----|-----------|
| Aggregate exposure limit | EUR 1m (~GBP 873k) | GBP 880k |
| QRRE individual limit | EUR 100k (~GBP 87k) | GBP 100k |

If retail thresholds are breached, exposure reclassified as CORPORATE.

## Counterparty Hierarchy

- Child counterparties inherit ratings from parent when they lack their own
- Traversed upward until a rated entity is found
- Internal and external ratings resolved independently
- External ratings are **not** inherited — each counterparty's own ECAI
  assessments are resolved in place per **CRR Art. 138**: per-agency dedup to
  most recent, then 1 → use it, 2 → higher RW (worse), ≥ 3 → higher of the
  two lowest RWs (second-best)

## Lending Group Aggregation

- Members defined via `lending_mappings`
- Parent automatically included as a member
- Duplicate membership resolved (keep first)
- Residential property exposures excluded from retail aggregation (Art. 123(c))

## Approach Assignment

```
Exposure -> SA / IRB / Slotting / Equity
```

Based on IRB permissions + internal rating availability. Counterparties with only
external ratings (no internal PD) fall to SA even with IRB permissions.

---

> **Full detail:** `docs/specifications/common/hierarchy-classification.md`
