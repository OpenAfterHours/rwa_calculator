# Hierarchy & Classification Specification

Counterparty hierarchy resolution, rating inheritance, and exposure class determination.

---

## Counterparty Hierarchy

### Organisation Mappings

The calculator resolves parent-child relationships between counterparties using `org_mappings`:

- Child counterparties inherit ratings from their parent when they lack their own
- The hierarchy is traversed upward until a rated entity is found

### Multi-Rating Resolution (CRR Art. 138)

When a counterparty has more than one external rating from nominated ECAIs, the
resolver applies CRR Art. 138 rather than picking the most recent:

1. **Per-agency dedup** — multiple assessments from the same agency are first
   reduced to the most recent (one assessment per agency).
2. **Art. 138 selection** across the remaining distinct-agency assessments:
    - 1 assessment → use it.
    - 2 assessments → use the **higher risk weight** (worse of the two).
    - ≥ 3 assessments → take the two assessments generating the two lowest
      risk weights, then use the **higher** of those two (i.e. the
      "second-best" rating).

Resolution is performed on CQS rather than RW because the CQS → RW mapping is
monotone non-decreasing within every SA exposure class, so ranking by CQS
ascending gives the same outcome as ranking by RW. External ratings are **not**
inherited from the parent — only the counterparty's own assessments participate
in Art. 138 resolution.

!!! info "Basel 3.1 additions — Art. 138(1)(g) and Art. 139(6)"
    Basel 3.1 extends Art. 138 with a new sub-point **(g)** and adds a new
    Art. 139(6) "higher-of" rule for institution exposures whose ECAI ratings
    incorporate **implicit government support**. Neither exists in CRR (CRR Art. 138
    has only (a)–(f); CRR Art. 139 has only paragraphs (1)–(4)). The new provisions
    apply **only where the obligor is an institution** and only on the ECRA (rated)
    path — they do not change the per-agency dedup or second-best selection mechanics
    above for corporate, sovereign, or retail obligors. See
    [B31 SA Risk Weights — Art. 138(1)(g), Art. 139(6)](../basel31/sa-risk-weights.md#ecai-assessment-implicit-government-support-art-1381g-art-1396)
    for the full treatment, including the government-owned / government-sponsored
    exemption and the distinction from Art. 121(6).

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

For multi-level facility hierarchies, drawn amounts from loans under sub-facilities are aggregated up to the root facility. The root undrawn equals the parent's headroom net of every drawn loan/contingent across the descendant tree:

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
- Only facilities with `undrawn_amount > 0` and `committed = True` generate exposure records

#### Multi-Option Facility (MOF) Waterfall Allocation

A **Multi-Option Facility** is any facility with at least one `child_type='facility'` mapping. Each sub-facility carries its own `risk_type` (and therefore its own SA CCF), so the parent's undrawn headroom is split across sub-facility CCF buckets — not collapsed onto the worst-case CCF as in earlier versions of the engine.

**Allocation rule** (per MOF parent):

1. Compute per-sub headroom: `sub_headroom = max(0, sub_limit − sub_drawn)`, where `sub_drawn` sums loans and contingents directly mapped to that sub (no roll-up).
2. Compute parent headroom: `parent_headroom = max(0, parent_limit − total_drawn − total_contingent)` rolled up across the whole descendant tree.
3. Sort committed sub-facilities by descending SA CCF, with deterministic tie-break on `risk_type` then `facility_reference`.
4. Walk subs in order. Allocate `min(sub_headroom_i, max(0, parent_headroom − cum_{i-1}))` to each sub, where `cum_{i-1}` is the running sum of higher-CCF allocations.
5. Emit one `facility_undrawn` row per sub with `allocation > 0`. Each row carries the **sub's** `risk_type` and `counterparty_reference`; provenance is captured in `mof_risk_type_source`.
6. If `parent_headroom > sum(allocations)`, emit one **residual** row at the parent's own `risk_type` and `counterparty_reference` for the leftover headroom.

**Worked example** — sub-limits exceed parent limit (waterfall caps):

```
FAC_01    limit £100m,  parent's risk_type = MR
├── FAC_SUB_01  limit £60m, risk_type = MR  (50% CCF)
└── FAC_SUB_02  limit £60m, risk_type = MLR (20% CCF)
```

| sub | sub_limit | sub_drawn | sub_headroom | CCF | allocation | EAD |
|---|---|---|---|---|---|---|
| FAC_SUB_01 | 60m | 0 | 60m | 50% | 60m | 30m |
| FAC_SUB_02 | 60m | 0 | 60m | 20% | 40m (capped) | 8m |
| residual | — | — | — | — | 0 | — |
| **total** | | | | | **100m** | **38m** |

**Worked example** — drawn loans nets per sub, residual emerges:

```
FAC_01    limit £100m,  parent's risk_type = FR (100% CCF)
├── FAC_SUB_01  limit £50m, MR (50% CCF), Loan_A drawn £20m
└── FAC_SUB_02  limit £30m, MLR (20% CCF)

per-sub: sub_01 headroom = 30m, sub_02 headroom = 30m
parent headroom = 100m − 20m = 80m
```

| sub | CCF | sub_headroom | allocation | EAD |
|---|---|---|---|---|
| FAC_SUB_01 | 50% | 30m | 30m | 15m |
| FAC_SUB_02 | 20% | 30m | 30m | 6m |
| residual (FR) | 100% | — | 80m − 60m = 20m | 20m |
| **total** | | | **80m** | **41m** |

**Output schema**:

- `exposure_reference = "{parent_ref}_UNDRAWN_{sub_ref}"` for sub waterfall rows; `"{parent_ref}_UNDRAWN_RESIDUAL"` for the parent residual row.
- `source_facility_reference = parent_ref` on every row, so facility-level collateral allocation and downstream rollups still group by the MOF parent.
- `mof_risk_type_source = sub_ref` on sub rows; `null` on the residual row.

**Edge cases**:

- **Uncommitted sub** (`committed=False`): skipped entirely from the waterfall — no row, no headroom consumption. The bank can refuse to lend, so the sub carries no commitment EAD.
- **Uncommitted parent** (`committed=False`): no rows emitted at all (existing behaviour preserved). Loans/contingents already mapped under the parent flow as their own exposure rows unaffected.
- **Sub with zero headroom** (fully drawn): drops out of the waterfall — emits no row.
- **Sub-limits sum below parent limit**: residual at parent's own `risk_type` covers the gap.
- **Standalone facility (no facility-typed children)**: single undrawn row with parent's own `risk_type` (non-MOF path unchanged).

#### Type Column Handling

The engine's contract is a single discriminator column `child_type`, guaranteed
to exist by the loader edge seal — the resolver itself carries no presence
guards. The loader handles the three accepted input shapes exactly once at
load:

| Input Shape | Treatment (at the loader) |
|-------------|---------------------------|
| `child_type` present | Pass through unchanged. **Producers MUST emit this form.** |
| `node_type` present, `child_type` absent | Renamed to `child_type` at load (legacy alias in `engine/loader.py` `_INPUT_COLUMN_ALIASES`). Do not introduce new `node_type` producers. |
| Neither column present | `child_type` injected as typed nulls by the seal. The downstream filter chain treats null as "no children of any type" — single-level mappings only, no facility hierarchy traversal, no loan or contingent aggregation against the parent. |

A file carrying both `child_type` and `node_type` is structurally ambiguous:
the loader's alias rename collides at schema resolution and the load wrappers
surface it (required table → `DataLoadError`; optional table → DQ007).

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

| Priority | Exposure Class | Art. 112(1) Ref | Table A2 row |
|----------|---------------|-----------------|--------------|
| 1 (highest) | Securitisation positions | (m) | Row 1 |
| 2 | CIUs | (o) | Row 2 |
| 3 | Subordinated debt / equity / own funds | (p) | Row 3 |
| 4 | Items associated with particularly high risk | (k) | Row 4 |
| 5 | Exposures in default | (j) | Row 5 |
| 6 | Covered bonds (eligible) | (l) | Row 6 |
| 7 | Real estate (RESI / CRE / ADC) | (i) | Row 7 |
| 8 | International organisations | (e) | Row 8 |
| 9 | MDBs | (d) | Row 9 |
| 10 | Institutions | (f) | Row 10 |
| 11 | Central governments / central banks | (a) | Row 11 |
| 12 | Regional governments / local authorities | (b) | Row 12 |
| 13 | Public sector entities | (c) | Row 13 |
| 14 | Retail | (h) | Row 14 |
| 15 | Corporates (including specialised lending per Art. 122A) | (g) | Row 15 |
| 16 (lowest) | Other items | (q) | Row 16 |

!!! note "Art. 112(1) letter mapping (verified 17 Apr 2026)"
    The PRA PS1/26 Art. 112(1) letters differ from earlier drafts of this spec:
    covered bonds are letter **(l)** and securitisation positions are letter **(m)**
    (not (m) and (n) as previously shown). Point **(n)** is left blank in the onshored
    text. High-risk is (k) and default is (j). Verified against ps126app1.pdf p.33
    (Art. 112(1) enumeration) and p.33–34 (Art. 112(2) Table A2 priority ordering).

!!! note "Specialised Lending is a Corporate Sub-Type"
    Under SA, specialised lending is classified within the corporate class (Art. 112(1)(g)) with distinct risk weights via Art. 122A-122B. There is no separate Art. 112(1)(ga) — the "(ga)" reference does not exist in the regulation. SL exposures are assigned to the corporate SA class and then sub-classified for risk weight purposes.

**Calculator coverage**: The calculator currently implements classes for: central govt/CB, RGLA, PSE, MDB, institution, corporate, specialised lending, retail, equity, real estate, ADC, and default. Securitisation, CIU (beyond 1,250% fallback per Art. 132(2) / Art. 132c), and covered bonds are tracked as future enhancements.

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

#### QRRE assignment gates (CRR Art. 154(4)(a)-(b) / PS1/26 Art. 147(5A)(a)-(b))

A revolving regulatory-retail exposure is admitted to the **RETAIL_QRRE** sub-class
(`classify_exposure_subtypes`) only when, in addition to the (c) aggregate-nominal
limit above, it satisfies all of:

| Gate | Condition | Engine signal | Null / direction of error |
|---|---|---|---|
| (a) individuals | exposure is to a natural person | `natural_person_expr()` — `is_natural_person` flag OR `individual` / `natural_person` / `retail` entity type | null/non-natural → **not** an individual → not QRRE (conservative) |
| (b) unsecured | facility is not collateralised | `~is_secured` (`FACILITY_SCHEMA.is_secured`, facility-coupled to drawn + undrawn rows) | null → **unsecured** (backward-compatible; matches absent-collateral handling elsewhere) |
| (b) cancellable | to the extent undrawn, unconditionally cancellable | `undrawn_amount == 0` OR `risk_type` ∈ {LR, low_risk} (the CCF unconditionally-cancellable bucket) | null/non-LR `risk_type` on an undrawn row → **not** cancellable → not QRRE (mirrors the CCF null convention, no divergence) |

Both regimes apply the same conditions (CRR Art. 154(4) is identical; only the (c)
limit *value* differs, from the pack), so the gates are **not** regime-Featured. A row
that fails any gate is left in **RETAIL_OTHER** (never mortgage, never expelled from
retail); this is the conservative direction because QRRE's fixed 0.04 correlation is
below the retail-other correlation at the low PDs typical of performing revolving
retail (the two cross at PD ≈ 7.3%), so QRRE would understate RWA. A gate-driven
demotion raises a single **CLS010** classification warning per run. The Art. 147(5A)
**wage-account derogation** (a wage-account-linked collateralised facility is treated as
unsecured) is applied via input semantics — set `is_secured=False` for such a facility.
Conditions (5A)(d) low loss-rate volatility and (5A)(e) consistency with the
sub-portfolio's risk characteristics are supervisory, portfolio-level attestations, not
per-exposure inputs, and are out of scope for row-level classification.

If the **SA regulatory-retail** thresholds are breached, the exposure loses its SA
regulatory-retail (75%) treatment and its SA `exposure_class` is reclassified to
CORPORATE.

!!! warning "SA regulatory retail (Art. 123/123A) vs IRB retail class (Art. 147(5)) — the monetary cap is SME-limb-only in IRB"
    The aggregate-owed cap above (`qualifies_as_retail`) implements the **SA**
    regulatory-retail test (CRR Art. 123 / PS1/26 Art. 123A), which caps natural
    persons for the 75% treatment and — under Basel 3.1 — adds the Art. 123A(1)(b)(ii)
    0.2% granularity limb. The **IRB** retail *exposure class* (CRR Art. 147(5)(a) /
    PS1/26 Art. 147(5)(a)) is a **different** rule: it admits **(i)** exposures to
    natural persons with **no monetary cap** and no granularity limb, or **(ii)**
    exposures to an SME **provided** the total amount owed (excluding
    residential-property-secured exposures) does not exceed **EUR 1,000,000 (CRR) /
    GBP 880,000 (PS1/26)**. The cap and granularity limb condition the **SME limb
    only**.

    Consequently a natural person owing more than the cap is expelled from SA
    regulatory retail (`exposure_class` → CORPORATE) but **stays in the IRB retail
    class**: `sync_irb_exposure_class` restores such a row's `exposure_class_irb`
    to RETAIL_OTHER (subject to the Art. 147(5)(c) management-basis condition —
    `is_managed_as_retail` not explicitly False), and `_align_irb_exposure_class`
    propagates it to `exposure_class` for the IRB-routed leg so the retail A-IRB
    formula applies. The natural-person signal is the `is_natural_person` flag OR
    an entity type in `NATURAL_PERSON_ENTITY_TYPES` (`individual` / `natural_person`
    / `retail`); an unknown obligor is treated as NOT a natural person, so the cap
    keeps binding (conservative). The SME limb is unchanged — an SME above the cap
    stays corporate.

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

Under Basel 3.1, corporates with consolidated annual revenue exceeding **EUR 500 million (GBP 440 million)** are classified as **large corporates** and, together with financial corporates, form the Art. 147(2)(c)(ii) subclass restricted to **F-IRB only** (cannot use A-IRB, per Art. 147A(1)(e)). This threshold is distinct from the SME firm-size adjustment threshold (EUR 50m / GBP 44m).

**Group-consolidation basis (Art. 147(4C)(b)(ii)).** The revenue is measured "at the highest level of consolidation which is performed and at which audited financial statements are available" — the *group's* revenue, not the individual counterparty's. The classifier therefore rolls each corporate's own `annual_revenue` up its resolved `ultimate_parent_reference` chain into `cp_group_annual_revenue` before the test (`attributes.with_group_annual_revenue`): the signal is the **maximum** of the counterparty's own turnover and its ultimate parent's own turnover. A parent's own `annual_revenue` is, by convention, its consolidated audited-accounts figure (which subsumes its subsidiaries), so the ultimate parent — the top of the group — carries the highest-consolidation figure. A small subsidiary of a > GBP 440m group is therefore correctly F-IRB-only even when its own turnover is below the threshold. The `max` (rather than a source-preference coalesce) is the conservative direction for a test that *forces* F-IRB: neither a small subsidiary figure nor a data-anomalous small parent figure can let a large obligor escape.

This is deliberately distinct from the entity-level `cp_annual_revenue`, which continues to drive the Art. 4(1)(128D) SME size test and the Art. 501 SME supporting factor — those read the counterparty's *own* turnover, not the group's.

**Null composition.** `max_horizontal` ignores nulls, so a null own turnover under a revenue-bearing parent yields the parent figure; a standalone corporate (null `ultimate_parent_reference`) yields its own; both-null yields null, at which point the existing conservative default applies (a corporate whose group revenue is null and whose `total_assets` does not confirm SME size is treated as large and **CLS008** is emitted). A subsidiary with null own revenue under a large parent is thus resolved by the roll-up and no longer trips CLS008.

**Warning.** When the roll-up itself drives the restriction — the counterparty's own turnover is at/below GBP 440m but its group turnover exceeds it — a **CLS011** classification warning records that F-IRB was forced by the group rather than the entity, for audit transparency (mirroring the CLS010 pattern). CLS008 and CLS011 are mutually exclusive.

**Deferral (3-year averaging).** Art. 147(4C)(b)(ii) prescribes "the average annual amount over the last three years". The counterparty schema carries a single point-in-time `annual_revenue`, so the most-recent-figure convention is used; multi-year revenue inputs are a documented future enhancement.

**CRR.** CRR has no financial-/large-corporates subclass — the whole restriction (and the roll-up) is gated on the `approach_restrictions_b31_applicable` feature and is a no-op under CRR, where A-IRB remains available regardless of revenue.

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
| Sovereign (incl. quasi-sovereigns: RGLA, PSE, MDB, Int'l Org with 0% RW) | **SA only** | Art. 147A(1)(a) → Art. 147(2)(a) |
| Institution | **F-IRB only** (no A-IRB) | Art. 147A(1)(b) → Art. 147(2)(b) |
| IPRE | **SA or Slotting only** (no F-IRB/A-IRB) | Art. 147A(1)(c) → Art. 147(2)(c)(i) |
| HVCRE | **SA or Slotting only** (no F-IRB/A-IRB) | Art. 147A(1)(c) → Art. 147(2)(c)(i) |
| **Large corporate (revenue > GBP 440m) AND Financial sector entity (all FSEs)** | **F-IRB only** (no A-IRB) — both share Art. 147(2)(c)(ii) | **Art. 147A(1)(e)** |
| Corporate (other general) | **F-IRB** (default); A-IRB only with explicit Art. 143(2A)/(2B) permission | Art. 147A(1)(f) → Art. 147(2)(c)(iii) |
| Retail — mortgage | A-IRB (if approved) — **unchanged from CRR Art. 151(7)** | Art. 147A(1)(g) → Art. 147(2)(d) |
| Retail — QRRE | A-IRB (if approved) — **unchanged from CRR Art. 151(7)** | Art. 147A(1)(g) |
| Retail — other | A-IRB (if approved) — **unchanged from CRR Art. 151(7)** | Art. 147A(1)(g) |
| Equity | **SA only** (IRB equity removed; Art. 155 left blank) | Art. 147A(1)(h) → Art. 147(2)(e) |
| Specialised lending — OF / PF / CF | SA, F-IRB, A-IRB or Slotting subject to permission | Art. 147A(1)(d) → Art. 147(2)(c)(i) |

!!! note "Implementation Status — Implemented (P1.4 Complete)"
    Art. 147A restrictions are enforced via `IRBPermissions.full_irb_b31()`, which encodes the mandatory approach assignments for sovereign/institution/IPRE/HVCRE/FSE/large corporate/equity sub-classes. The classifier enforces IPRE and HVCRE slotting routing, and blocks FSE and large-corporate exposures from A-IRB (F-IRB only). Equity is restricted to SA. Sovereign sub-classes (RGLA, PSE, MDB, international org with 0% RW) are forced to SA.

!!! info "Retail Rows Are Carry-Forward from CRR Art. 151(7)"
    The three retail rows (mortgage, QRRE, other) in the Art. 147A table above restate
    an existing CRR obligation in the Basel 3.1 structured form. CRR Art. 151(7) already
    required firms applying IRB to retail to "provide own estimates of LGDs and conversion
    factors" (i.e. A-IRB); CRR Art. 151(8) explicitly restricted F-IRB to exposure classes
    (a)–(c), omitting retail (d). Accordingly, Art. 147A(1)(g) is a **carry-forward**, not
    a new Basel 3.1 restriction. See the detailed note in
    [`../basel31/model-permissions.md#art-147a-approach-restrictions`](../basel31/model-permissions.md#art-147a-approach-restrictions)
    and the CRR/B31 comparison matrix in
    [`../../framework-comparison/key-differences.md#irb-approach-restrictions`](../../framework-comparison/key-differences.md#irb-approach-restrictions).

### Art. 112 Table A2 Priority Ordering

When an exposure qualifies for multiple SA exposure classes, the highest-priority class takes precedence. See the priority table in the [Exposure Classification](#exposure-classification) section above. The classifier should apply this ordering systematically rather than relying on entity type alone.

### Dual-Approach Split

Based on IRB permissions in the configuration, exposures are routed to:

1. **SA** - Standardised Approach
2. **IRB** - Foundation IRB or Advanced IRB
3. **Slotting** - Specialised lending categories
4. **Equity** - Equity exposures (pass-through, no CRM applied)

## Real estate classification derivation

The Basel 3.1 SA real-estate framework (Art. 124 to Art. 124L) relies on a number
of classification flags — `is_adc`, `is_materially_dependent`, `is_mixed_use`,
`exposure_subclass` for corporate granularity — that the current pipeline
consumes as **pre-tagged** inputs from the caller. None of the derivations below
are performed by the classifier today; each subsection records the regulatory
expectation for full compliance.

### ADC classification trigger (PS1/26 App 1, Art. 124K)

**Verbatim PDF definition (PS1/26 App 1, p.3, Glossary entry):**

> "*ADC exposure* means an exposure to a corporate or special purpose entity
> financing any land acquisition for development and construction purposes, or
> financing development and construction of any residential real estate or
> commercial real estate."

**Verbatim PDF quote (PS1/26 App 1, p.58, Art. 124K):**

> "Subject to paragraph 2, an institution shall assign a risk weight of 150%
> to an ADC exposure. An institution may assign a risk weight of 100% to an
> ADC exposure financing any land acquisition for the development and
> construction of residential real estate, or financing the development and
> construction of residential real estate if: (a) the exposure is subject to
> prudent underwriting standards …; and (b) at least one of the following
> conditions is met: (i) legally binding pre-sale or pre-lease contracts …
> amount to a significant portion of total contracts; or (ii) the borrower
> has substantial equity at risk."

**Expected derivation.** ADC classification should be derived from the
conjunction of:

- `product_type ∈ {construction_loan, development_finance}` **OR**
  `acquisition_financing == True` **OR** the exposure funds ADC activity as
  defined in the Glossary;
- `counterparty_entity_type ∈ {corporate, spv, special_purpose_entity}`
  (natural-person ADC lending is out of scope of Art. 124K by definition); and
- the property purpose is development/construction of RRE or CRE (not a
  completed income-producing or owner-occupied building).

**Current implementation.** The classifier consumes `is_adc` as a pre-set
boolean on the exposure schema. The 100% concessionary branch of
Art. 124K(2) (pre-sale/equity-at-risk) also depends on caller-supplied flags.

!!! warning "Not yet implemented — automatic ADC derivation"
    See **IMPLEMENTATION_PLAN.md P1.140** (ADC classification derivation). The
    Art. 124K(2) residential-only restriction on the 100% concessionary branch
    has been fixed (P1.129, v0.1.186); automatic derivation of the
    pre-sale / equity-at-risk triggers themselves remains part of P1.140.

### Art. 124(4) mixed-use splitting

**Verbatim PDF quote (PS1/26 App 1, p.50, Art. 124(4)):**

> "An institution shall split a mixed real estate exposure into a residential
> real estate exposure and a commercial real estate exposure according to the
> ratio of the values of the residential real estate and the commercial real
> estate that the exposure is secured by. An institution shall assign the
> relevant risk weights set out in Article 124J to each part of the exposure
> …"

**Expected derivation.** When an exposure's collateral comprises both RRE and
CRE portions, the exposure must be split pro-rata by property value. The RRE
portion is risk-weighted under Art. 124F–124I (as RRE), and the CRE portion
under Art. 124J (as CRE) — each with its own RRE/CRE-specific LTV and
materially-dependent logic. A single blended risk weight is not permitted.

**Current implementation.** Real-estate exposures are classified as either RRE
or CRE on the basis of a single `is_residential_real_estate` flag. Mixed-use
splitting is not performed.

!!! warning "Not yet implemented — Art. 124(4) mixed-use splitting"
    See **IMPLEMENTATION_PLAN.md P1.141** (mixed-use pro-rata splitting). This
    requires new input fields: residential portion value, commercial portion
    value (or a ratio), and the ability to emit two classified rows per input
    exposure.

### Art. 124E three-property limit for "materially dependent"

**Verbatim PDF quote (PS1/26 App 1, p.54, Art. 124E(1)–(2)):**

> "A residential real estate exposure is materially dependent on the
> cash-flows generated by the property unless it is: (a) to one or more
> natural persons and the exposure is secured by a single property that is
> the obligor's primary residence; (b) to one or more natural persons that
> individually meet the three property limit in accordance with paragraph 2;
> …
>
> A natural person meets the three property limit referred to in point (b)
> of paragraph 1 if they have no more than three qualifying properties. A
> qualifying property is a property that is residential real estate, is not
> the primary residence of the natural person and that is either: (a)
> security for a residential real estate exposure to the natural person …;
> or (b) security for a residential real estate exposure to an entity which
> is created specifically to finance and/or operate immovable property,
> where the natural person acts as a guarantor …"

**Expected derivation.** Natural-person obligors with four or more
simultaneous buy-to-let / investment RRE exposures (i.e. breaching the three
qualifying-property limit in paragraph 2) should automatically flip from
Art. 124F (non-materially-dependent RRE — lower risk weights via Art. 124L
counterparty RWs) to Art. 124G (materially-dependent RRE — higher
property-LTV-based weights). The three-property count must be computed across
**all** lenders' RRE exposures to the obligor (per the "regardless of which
lender has the residential real estate exposure" qualifier), but in practice
a single-firm calculator can only count exposures it sees.

**Current implementation.** The classifier consumes `is_materially_dependent`
as a caller-supplied flag on the exposure schema. No automatic counting of
qualifying properties is performed.

!!! warning "Not yet implemented — Art. 124E three-property auto-derivation"
    See **IMPLEMENTATION_PLAN.md P1.142** (Art. 124E three-property limit
    auto-classification). The cross-lender property count requires an
    external data source and is tracked as a v2.0 / Tier-7 item (see
    `IMPLEMENTATION_PLAN.md` §"Tier 7 — Future / v2.0").

!!! info "Reassessment obligations (Art. 124E(5) and (7))"
    Art. 124E(5) requires institutions to **reassess** material dependency of a
    residential RE exposure whenever a new residential-RE-secured loan is issued to the
    obligor (including replacement loans). Discretionary updates at other times are
    permitted only if new information is applied consistently portfolio-wide —
    Art. 124E(5) explicitly prohibits selective reassessment aimed at reducing own-funds
    requirements. Art. 124E(7) requires **commercial RE** reassessment at least annually.

    The mandatory residential trigger is **obligor-level**: a new RRE loan to the same
    borrower at a different address re-opens the paragraph-2 three-property count for
    every existing RRE exposure to that borrower. See the
    [B31 SA spec reassessment subsection](../basel31/sa-risk-weights.md#reassessment-triggers-residential-re-art-124e5)
    for verbatim PS1/26 wording.

### Art. 147A(1)(e)/(f) subclass reporting for corporates

**Verbatim PDF quote (PS1/26 App 1, p.92, Art. 147A(1)(e)–(f)):**

> "(e) for point (c)(ii) of Article 147(2) (financial corporates and large
> corporates): (i) the Standardised Approach for exposures where permission
> has been granted under Article 148 or Article 150; (ii) the Foundation
> IRB Approach for all other exposures within that exposure subclass;
>
> (f) for point (c)(iii) of Article 147(2) (other general corporates):
> (i) the Standardised Approach for exposures where permission has been
> granted under Article 148 or Article 150; (ii) the Advanced IRB Approach
> for exposures where permission has been granted under Article 143(2A) or
> (2B) to use the Advanced IRB Approach; (iii) the Foundation IRB Approach
> for all other exposures within that exposure subclass …"

**Expected derivation.** Corporate exposures subject to Art. 147A should
carry three distinct `exposure_subclass` values corresponding to the
Art. 147(2)(c)(ii)/(iii) split:

| Sub-class | Trigger | Approach gate (Art. 147A) |
|-----------|---------|---------------------------|
| Large corporate | consolidated annual revenue > GBP 440m (EUR 500m) | Art. 147A(1)(e) — F-IRB only |
| Financial sector entity (FSE) | `cp_is_financial_sector_entity == True` | Art. 147A(1)(e) — F-IRB only |
| Other general corporate | Corporate not meeting the above | Art. 147A(1)(f) — F-IRB default; A-IRB with Art. 143(2A)/(2B) permission |

Even though large corporate and FSE share the same approach restriction
(F-IRB only), they should be reported separately because COREP templates
split these sub-classes on distinct rows and PRA Pillar 3 disclosures
(Annex XX / XXII) use sub-class-level granularity. Likewise, "other general
corporates" differs in that A-IRB remains available with the Art. 143(2A)/(2B)
permission.

**Current implementation.** The classifier enforces the approach restrictions
(F-IRB block on large corporates and FSEs) but does not emit a distinct
`exposure_subclass` value for each of (d), (e) and (f). All three flow
through as a generic `CORPORATE` class with approach-level distinction only.

!!! warning "Not yet implemented — Art. 147A subclass reporting"
    See **IMPLEMENTATION_PLAN.md P2.28** (CR9 row taxonomy — AIRB RE 4-way and
    FIRB financial / large corporate sub-rows) and the related P2.25 CR5 gap.
    The sub-class distinction has **no impact on risk-weight or RWA**; it is
    purely a reporting granularity gap.

### FX Conversion

All monetary values are converted to the base currency (GBP) using provided FX rates before calculation.

## Key Scenarios

!!! note "Test Coverage"
    Hierarchy and classification are validated through unit tests (`test_hierarchy.py`, `test_classifier.py`) and integration tests (`test_loader_to_hierarchy.py`, `test_hierarchy_to_classifier.py`), not dedicated acceptance test scenarios. The scenario IDs below document the key behaviours for traceability.

### Hierarchy Resolution (HIER)

| Scenario ID | Description |
|-------------|-------------|
| HIER-1 | Rating inheritance — child counterparty inherits CQS from rated parent |
| HIER-2 | Multi-level hierarchy — rating traversed upward through two or more parent levels |
| HIER-3 | Lending group aggregation — turnover/exposure summed across group members |
| HIER-4 | Facility hierarchy — sub-facility undrawn amount aggregated to root facility |
| HIER-5 | Duplicate membership — counterparty in multiple lending groups keeps first assignment |
| HIER-6 | Negative drawn amount clamping — negative balances do not increase undrawn headroom |
| HIER-7 | Multi-rating resolution — CRR Art. 138 applied when ≥ 2 external ratings present |

### Exposure Classification (CLASS)

| Scenario ID | Description |
|-------------|-------------|
| CLASS-1 | Entity-type to exposure class mapping (e.g., `sovereign` → CENTRAL_GOVT_CENTRAL_BANK) |
| CLASS-2 | SME detection — corporate reclassified as CORPORATE_SME when turnover < threshold |
| CLASS-3 | Retail qualification — individual reclassified as RETAIL when aggregate exposure < threshold |
| CLASS-4 | Retail breach — exposure exceeding threshold reclassified as CORPORATE |
| CLASS-5 | Art. 112 priority ordering — higher-priority class takes precedence (e.g., equity > corporate) |
| CLASS-6 | Art. 147A approach restriction — FSE forced to F-IRB, sovereign forced to SA (Basel 3.1) |
| CLASS-7 | Large corporate restriction — revenue > GBP 440m forced to F-IRB (Basel 3.1, Art. 147A(1)(e)) |
| CLASS-8 | Defaulted exposure identification — default status flag propagated through classification |
