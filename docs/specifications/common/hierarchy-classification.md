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

- Facility undrawn amount = `max(facility_limit - sum(drawn_amounts) - sum(contingent_nominals), 0)`
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

| Entity Type(s) | Exposure Class |
|----------------|---------------|
| `sovereign`, `central_bank` | CENTRAL_GOVT_CENTRAL_BANK |
| `rgla_sovereign`, `rgla_institution` | RGLA |
| `pse_sovereign`, `pse_institution` | PSE |
| `mdb` | MDB |
| `international_org` | INTERNATIONAL_ORGANISATION |
| `institution`, `bank`, `ccp`, `financial_institution` | INSTITUTION |
| `corporate`, `company` | CORPORATE |
| `individual`, `retail` | RETAIL_OTHER (if qualifying) |
| `specialised_lending` | SPECIALISED_LENDING |
| `equity` | EQUITY |

### Basel 3.1 Exposure Class Priority (Art. 112)

PRA PS1/26 Art. 112 Table A2 defines 16 exposure classes with a strict priority ordering. When an exposure could belong to multiple classes, the highest-priority class takes precedence:

| Priority | Exposure Class | Art. 112 Ref |
|----------|---------------|--------------|
| 1 (highest) | Securitisation positions | (n) |
| 2 | CIUs | (o) |
| 3 | Subordinated debt / equity / own funds | (p) |
| 4 | Items associated with particularly high risk | (l) |
| 5 | Exposures in default | (k) |
| 6 | Covered bonds | (m) |
| 7 | Real estate (RESI / CRE / ADC) | (i) |
| 8 | International organisations | (e) |
| 9 | MDBs | (d) |
| 10 | Institutions | (f) |
| 11 | Central governments / central banks | (a) |
| 12 | Regional governments / local authorities | (b) |
| 13 | Public sector entities | (c) |
| 14 | Retail | (h) |
| 15 | Corporates (including specialised lending per Art. 122A) | (g) |
| 16 (lowest) | Other items | (q) |

!!! note "Specialised Lending is a Corporate Sub-Type"
    Under SA, specialised lending is classified within the corporate class (Art. 112(1)(g)) with distinct risk weights via Art. 122A-122B. There is no separate Art. 112(1)(ga) — the "(ga)" reference does not exist in the regulation. SL exposures are assigned to the corporate SA class and then sub-classified for risk weight purposes.

**Calculator coverage**: The calculator currently implements classes for: central govt/CB, RGLA, PSE, MDB, institution, corporate, specialised lending, retail, equity, real estate, ADC, and default. Securitisation, CIU (beyond 250% fallback), and covered bonds are tracked as future enhancements.

!!! info "High-Risk Items (Art. 128)"
    Art. 128 was omitted from UK CRR by SI 2021/1078 (effective 1 Jan 2022) and is
    only active under Basel 3.1 (PRA PS1/26, from 1 Jan 2027). The calculator has
    a HIGH_RISK exposure class wired in the classifier and SA calculator for both
    framework paths, but the CRR path application has no current UK legal basis
    (see D3.12). Under B31, Art. 128(2) is left blank — no specific categories are
    named; institutions assess risk per Art. 128(3) criteria.

### SME Detection

Corporate counterparties are reclassified as CORPORATE_SME when:

- **CRR:** Group turnover < EUR 50m (GBP converted to EUR at configured rate)
- **Basel 3.1:** Group turnover < **GBP 44m** (direct GBP threshold per PRA PS1/26, calculated on highest consolidated accounts of the group; no FX conversion needed)

### Retail Qualification

Individual counterparties qualify for retail treatment when:

- **CRR:** Aggregate exposure < EUR 1m (GBP ~873k at default EUR/GBP rate of 0.8732)
- **Basel 3.1:** Aggregate exposure < GBP 880k
- **QRRE limit (IRB Art. 147(5A)(c)):** Largest aggregate nominal exposure to any single individual in the QRRE sub-portfolio ≤ EUR 100k (CRR) / **GBP 90,000** (Basel 3.1). This is a **portfolio-level** constraint, not a per-facility check.

If retail thresholds are breached, the exposure is reclassified as CORPORATE.

### Basel 3.1 Retail Qualifying Criteria (Art. 123A)

Under Basel 3.1, Art. 123A has a two-path structure:

- **Art. 123A(1)(a) — SME retail**: Exposures to SMEs automatically qualify as regulatory retail without further conditions.
- **Art. 123A(1)(b) — Natural person retail**: Three conditions must **all** be met:

1. **Product type** (Art. 123A(1)(b)(i)): The exposure takes the form of revolving credits/lines of credit (credit cards, overdrafts), personal term loans/leases (instalment loans, auto loans, student loans), or small business facilities. Must not be a derivative, bond, or equity instrument. Mortgages are excluded (separate class).
2. **Granularity** (Art. 123A(1)(b)(ii)): Total exposure to the obligor (or connected group) does not exceed **GBP 880,000**. No single exposure represents more than 0.2% of the retail portfolio.
3. **Pool management** (Art. 123A(1)(b)(iii)): The exposure is part of a **significant number of similarly managed exposures** with similar characteristics. This is a qualitative/attestation requirement, not a calculated check.

!!! note "Implementation Status"
    - **Condition 1 (product type)**: Not enforced — the calculator relies on input data for product type classification. A dedicated `product_type` field would be needed to validate this condition programmatically.
    - **Condition 2 (granularity threshold)**: Implemented — aggregate exposure threshold (GBP 880,000) is enforced via lending group aggregation.
    - **Condition 3 (pool management)**: Implemented under Basel 3.1 — non-SME entities must have `is_managed_as_retail=True` to qualify. This field defaults to `True` for backward compatibility. SME entities auto-qualify per Art. 123A(1)(a) and are not subject to this condition.
    - **SME auto-qualification (Art. 123A(1)(a))**: Explicitly implemented — SME counterparties bypass the three conditions under (b) and qualify for retail treatment directly.

!!! note "No Art. 123A(d)"
    There is no Art. 123A(d) — the article has only two paths (a) and (b), with three sub-conditions under (b). Previous documentation incorrectly described four criteria.

### Large Corporate Revenue Threshold (Basel 3.1)

Under Basel 3.1, corporates with consolidated annual revenue exceeding **EUR 500 million (GBP 440 million)** are classified as **large corporates** and are restricted to **F-IRB only** (cannot use A-IRB). This threshold is distinct from the SME firm-size adjustment threshold (EUR 50m / GBP 44m).

### FSE Classification Requirements

**Financial sector entity (FSE)** classification is required under Basel 3.1 for:

- Applying the correct F-IRB LGD (45% for FSE vs 40% for non-FSE, per Art. 161(1))
- Applying the FI scalar (1.25x correlation multiplier)
- Determining approach restrictions under Art. 147A(1)(e) (**all** FSEs → F-IRB only, not just large FSEs)

The `cp_is_financial_sector_entity` flag is sourced from the counterparty schema and propagated through the classifier. It is used for the Art. 147A(1)(e) F-IRB-only block and for applying the 45% FSE LGD floor.

### Defaulted Exposures

Exposures flagged with a default status are identified and tracked throughout the calculation. Defaulted status affects risk weighting (e.g., 150% SA risk weight for defaulted unsecured).

## Approach Assignment

### Basel 3.1 Approach Restrictions (Art. 147A)

Under Basel 3.1, PRA PS1/26 Art. 147A mandates specific approaches by exposure sub-class. These are **not optional** — firms cannot choose an alternative even if they have model approval:

| Exposure Sub-Class | Mandatory Approach | Reference |
|-------------------|-------------------|-----------|
| Sovereign (incl. quasi-sovereigns: RGLA, PSE, MDB, Int'l Org with 0% RW) | **SA only** | Art. 147A(1)(a), Art. 147(3) |
| Institution | **F-IRB only** (no A-IRB) | Art. 147A(1)(b) |
| IPRE | **Slotting only** | Art. 147A(1)(c) |
| HVCRE | **Slotting only** | Art. 147A(1)(c) |
| Large corporate (revenue > GBP 440m) | **F-IRB only** (no A-IRB) | Art. 147A(1)(d) |
| Financial sector entity (all FSEs) | **F-IRB only** (no A-IRB) | Art. 147A(1)(e) |
| Equity | **SA only** (IRB equity removed) | Art. 147A(1)(f) |
| Corporate (other) | **F-IRB** (default); A-IRB only with explicit Art. 143(2A)/(2B) permission | Art. 147A(1)(f) |
| Retail — mortgage | A-IRB (if approved) | Art. 147A(3) |
| Retail — QRRE | A-IRB (if approved) | Art. 147A(3) |
| Retail — other | A-IRB (if approved) | Art. 147A(3) |
| Specialised lending (OF/PF/CF) | **Slotting** (default); F-IRB or A-IRB with explicit permission | Art. 147A(1)(d) |

!!! note "Implementation Status — Implemented (P1.4 Complete)"
    Art. 147A restrictions are enforced via `IRBPermissions.full_irb_b31()`, which encodes the mandatory approach assignments for sovereign/institution/IPRE/HVCRE/FSE/large corporate/equity sub-classes. The classifier enforces IPRE and HVCRE slotting routing, and blocks FSE and large-corporate exposures from A-IRB (F-IRB only). Equity is restricted to SA. Sovereign sub-classes (RGLA, PSE, MDB, international org with 0% RW) are forced to SA.

### Art. 112 Table A2 Priority Ordering

When an exposure qualifies for multiple SA exposure classes, the highest-priority class takes precedence. See the priority table in the [Exposure Classification](#exposure-classification) section above. The classifier should apply this ordering systematically rather than relying on entity type alone.

### Dual-Approach Split

Based on IRB permissions in the configuration, exposures are routed to:

1. **SA** - Standardised Approach
2. **IRB** - Foundation IRB or Advanced IRB
3. **Slotting** - Specialised lending categories
4. **Equity** - Equity exposures (pass-through, no CRM applied)

### FX Conversion

All monetary values are converted to the base currency (GBP) using provided FX rates before calculation.
