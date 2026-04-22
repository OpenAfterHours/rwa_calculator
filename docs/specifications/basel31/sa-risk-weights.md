# SA Risk Weights Specification

Basel 3.1 Standardised Approach risk weight changes: ECRA/SCRA for institutions,
corporate sub-categories, real estate loan-splitting, SA specialised lending,
currency mismatch multiplier, and SME corporate class.

**Regulatory Reference:** PRA PS1/26 Art. 112–134, CRE20
**Test Group:** B31-A

---

## Requirements Status

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-1.1 | Sovereign risk weights (unchanged from CRR, flat 100% unrated) | P0 | Done |
| FR-1.2 | Institution ECRA risk weights (Art. 120, Table 3) | P0 | Done |
| FR-1.3 | Institution SCRA risk weights (Art. 121, grades A–C) | P0 | Done |
| FR-1.3a | SCRA sovereign floor for foreign-currency exposures (Art. 121(6)) with self-liquidating trade < 1yr carve-out | P1 | Done |
| FR-1.4 | Corporate CQS-based risk weights with PRA CQS 5 = 150% | P0 | Done |
| FR-1.5 | Corporate sub-categories: IG 65%, non-IG unrated 135%, SME 85% | P0 | Done |
| FR-1.6 | Retail 75%, salary/pension 35% (Art. 123(4), carried from CRR2) | P0 | Done |
| FR-1.6a | QRRE transactor 45% gated by 12-month full-repayment history (Art. 123(3)(a), PRA Glossary) | P0 | Done (input-driven — upstream assessment) |
| FR-1.7 | Residential RE loan-splitting (Art. 124F–124G) | P0 | Done |
| FR-1.8 | Commercial RE loan-splitting and income-producing (Art. 124H–124I) | P0 | Done |
| FR-1.9 | SA Specialised Lending (Art. 122A–122B) | P0 | Done |
| FR-1.10 | Currency mismatch multiplier 1.5× (Art. 123B) | P0 | Done |
| FR-1.11 | Defaulted provision-coverage split (Art. 127) | P0 | Done |
| FR-1.12 | Real estate qualifying criteria routing (Art. 124A, 124J) | P0 | Done |
| FR-1.13 | ADC exposures 150% / qualifying residential 100% (Art. 124K) | P0 | Done |
| FR-1.17 | Regulatory LTV definition and prior charges stacking (Art. 124C) | P1 | Done |
| FR-1.14 | Covered bond rated risk weights (Art. 129(4), Table 7) — PRA values = CRR values | P0 | Done (spec correct; code bug P1.113) |
| FR-1.15 | Covered bond unrated derivation (Art. 129(5)) — expanded 7-entry table for SCRA | P0 | Done |
| FR-1.16 | Non-UK unrated PSE/RGLA: sovereign CQS-derived weights, not flat 100% | P1 | Code bug P1.112 |
| FR-1.18 | Material dependency classification for RE exposures (Art. 124E) | P1 | Done (input-driven) |
| FR-1.19 | Due diligence obligation risk-weight override (Art. 110A) | P1 | Done (input-driven; SA004 warning, `due_diligence_override_rw` floor) |
| FR-1.20 | ECRA trade-finance ≤ 6m extension of Table 4 (Art. 120(2A)) | P1 | Done (input-driven via `is_short_term_trade_lc`) |
| FR-1.21 | Real estate framework routing (Art. 124(1)–(3)) and mixed RE proportional split (Art. 124(4)) | P1 | Partial — single-property routing done; mixed-property split requires per-component property values (input-schema gap, see D3.59) |
| FR-1.22 | RE valuation requirements — qualifying valuation, >10% market decline and GBP 2.6m / 5% own funds revaluation triggers, self-build floor, pre-2027 transitional (Art. 124D(1)–(11)) | P1 | Input-driven — calculator consumes `property_value` as already Art. 124D-compliant; valuation governance is firm-side (no Art. 124D-specific input fields for valuation source, revaluation date, or self-build flag) |
| FR-1.23 | Output-floor S-TREA election for unrated corporates by IRB firms — 100% vs IG/non-IG split with PRA notification obligation (Art. 122(7)–(8)) | P2 | Input-driven — the S-TREA leg of the output floor reuses the firm's Art. 122(5)/(6) branch selection from its regular SA application; notification to PRA on adoption or cessation is a firm governance step upstream of the calculator |
| FR-1.24 | Implicit government support higher-of rule for rated institution exposures (Art. 138(1)(g), Art. 139(6)) | P2 | Not implemented — input-schema gap (no distinction between issue-specific and general issuer ratings; no flag for implicit-support assumption). Firms must pre-adjust `external_cqs` offline or use the Art. 110A `due_diligence_override_rw` pathway. See D3.60. |
| FR-1.25 | Real estate underwriting-standards policy obligation — affordability assessment at origination (Art. 124B) | P2 | Firm-governance only — no calculator input or validation; compliance evidenced through underwriting-policy documentation and supervisory review |

---

## Due Diligence Obligation (Art. 110A)

Article 110A is a new **framework-wide obligation** applying to every exposure within the Standardised Approach (subject to five named exemptions). It has no CRR equivalent. The obligation sits above the exposure-class tables below: a firm cannot rely on the standard risk weight unless it has performed due diligence consistent with Art. 110A(2).

### Regulatory text (PRA PS1/26 Art. 110A, ps126app1.pdf pp. 29–30)

!!! quote "Art. 110A — Due Diligence"
    1. This Article applies to an institution subject to the Standardised Approach to credit risk set out in this Part.
    2. An institution shall perform due diligence to ensure that it has an adequate understanding of the risk profile, creditworthiness and characteristics of exposures to individual obligors and at a portfolio level.
    3. The sophistication of the due diligence undertaken by the institution in accordance with paragraph 2 shall be appropriate to the nature, scale and complexity of the institution's activities.
    4. As part of its obligations under paragraph 2, an institution shall:
        - (a) take reasonable and adequate steps to assess the operating and financial condition of each obligor;
        - (b) ensure that it has in place effective internal policies, processes, systems and controls to ensure that the appropriate risk-weighted exposure amounts are assigned to an obligor;
        - (c) perform the due diligence prior to incurring an exposure to an obligor and at least annually thereafter;
        - (d) to the extent reasonably practicable, perform the due diligence at the level of each individual exposure; and
        - (e) if applicable, take into account the extent to which membership of a corporate group affects an obligor's risk profile and credit worthiness.
    5. The obligations in paragraph 2 do not apply in respect of exposures in scope of:
        - (a) points (a) to (c) of Article 112(1);
        - (b) Article 117(2); and
        - (c) Article 118(1).

### Scope and exemptions

| Art. 110A(5) reference | Exempt obligor class | Rationale |
|------------------------|----------------------|-----------|
| Art. 112(1)(a) | Central governments and central banks | Sovereign counterparties — DD would not change the 0% / sovereign-CQS risk weight |
| Art. 112(1)(b) | Regional governments and local authorities (RGLA) | Sovereign-derived or treated-as-sovereign treatment |
| Art. 112(1)(c) | Public sector entities (PSE) | Sovereign-derived or treated-as-sovereign treatment |
| Art. 117(2) | Named 0% risk weight multilateral development banks (MDBs) | Named list; DD does not change the 0% treatment |
| Art. 118(1) | International organisations (EU, IMF, BIS, EFSF, ESM) | 0% risk weight by enumeration |

All other obligor classes — **institutions, corporates, retail, real estate, equity, CIUs, and Art. 117(1) non-named MDBs (Table 2B)** — are within the DD obligation.

### Minimum DD standard (Art. 110A(4))

- **Assess condition of every obligor** (Art. 110A(4)(a)). The requirement is "reasonable and adequate steps" — the sophistication scales with the institution's activities (Art. 110A(3)).
- **Policy, process, system, and control framework** for assigning risk weights (Art. 110A(4)(b)). This is the hook for the **risk-weight uplift**: if internal assessment shows the ECAI/class-based RW understates risk, the firm must assign a higher RW.
- **Timing**: initial DD before the exposure is incurred; re-performed at least annually thereafter (Art. 110A(4)(c)).
- **Granularity**: per-exposure where reasonably practicable (Art. 110A(4)(d)); portfolio-level otherwise.
- **Group structure**: membership of a corporate group must be factored into the assessment (Art. 110A(4)(e)) — relevant to connected-client and intra-group support analysis.

### Distinction from class-specific CQS step-up overrides

Art. 110A is the **umbrella obligation**. Three narrower, class-specific CQS step-up rules apply to *rated* exposures where ECAI assessment is the default RW source:

| Provision | Obligor class | Trigger | Effect |
|-----------|---------------|---------|--------|
| Art. 120(4) | Rated institutions | DD reveals risk higher than ECAI implies | One CQS step higher (e.g. CQS 2 → CQS 3 weight) |
| Art. 122(4) | Rated corporates | Same | One CQS step higher |
| Art. 129(4A) | Covered bonds | Same | One CQS step higher than the derivation (Art. 129(4)/(5)) result |

Art. 110A is broader: it applies to **every non-exempt SA exposure**, rated or unrated, and permits an arbitrary uplift (not limited to one CQS step) where the firm's internal assessment indicates the calculated RW understates risk.

### Implementation

Two optional input fields on the facility schema support Art. 110A:

| Field | Type | Nullable | Description |
|-------|------|----------|-------------|
| `due_diligence_performed` | Boolean | Yes (default `False`) | Firm attestation that DD per Art. 110A(2) has been performed for this exposure |
| `due_diligence_override_rw` | Float64 | Yes | Firm-determined uplifted risk weight (decimal — e.g. `1.50` for 150%) where DD reveals higher risk than the calculated RW |

**Override behaviour:**

- Apply as the **final** risk-weight modification — after CQS lookup, CRM substitution (life-insurance / guarantee / FCSM), and currency-mismatch multiplier (Art. 123B).
- **Directional floor:** `RW_final = max(RW_calculated, RW_override)`. The override can only increase the RW; a lower override has no effect.
- Null override values are silently ignored.

**Sequencing in the SA calculator:**

1. Standard CQS/class-based risk weight determination (Art. 112–134).
2. CRM substitution — FCSM, life insurance, guarantee (Art. 197–236).
3. Currency-mismatch multiplier — 1.5×, 150% cap (Art. 123B).
4. **Due diligence override (Art. 110A)** — `max(calculated, override)` applied here.
5. RWA calculation — `RWA = EAD × RW_final`.

**Validation:**

- Under Basel 3.1, when the `due_diligence_performed` column is absent from the facilities frame, the calculator emits a data-quality warning with code `SA004` (`ERROR_DUE_DILIGENCE_NOT_PERFORMED`, severity `WARNING`, `regulatory_reference="PRA PS1/26 Art. 110A"`). The calculation continues — the warning does not block execution.
- Under CRR, no warning is emitted (no CRR equivalent to Art. 110A).

**Audit:**

- When the override column is present, an output column `due_diligence_override_applied` (Boolean) flags exposures whose RW was raised by the override. Use this to reconcile against internal DD records and to populate SA RW-uplift disclosures.

!!! warning "Firm responsibility — not an engine determination"
    The calculator does not attempt to determine whether DD is *adequate* under Art. 110A(2)–(4). It only:
    (1) warns when DD status is not provided, and (2) applies any firm-supplied uplifted risk weight as a floor. The firm remains responsible for the policies, processes, and annual review obligations under Art. 110A(4)(b)/(c). Values supplied via `due_diligence_override_rw` should be traceable to the firm's DD process documentation.

### CRR comparison

CRR has no Art. 110A equivalent. SA firms under CRR rely on generic risk-management obligations in Art. 79 CRD IV (not a CRR provision) and the IRB-specific Art. 186 requirements. There is no SA-specific DD gate. The calculator therefore does not apply the SA004 warning under CRR, and the `due_diligence_override_rw` column is ignored on the CRR path.

---

## Sovereign Risk Weights (Art. 114)

Largely unchanged from CRR. The key Basel 3.1 clarification is the treatment of unrated sovereigns.

**Table 1 — Sovereign Risk Weights (Art. 114)**

| CQS | Risk Weight |
|-----|-------------|
| CQS 1 | 0% |
| CQS 2 | 20% |
| CQS 3 | 50% |
| CQS 4 | 100% |
| CQS 5 | 100% |
| CQS 6 | 150% |
| Unrated | 100% |

!!! note "No OECD Bifurcation"
    PRA PS1/26 Art. 114(1) assigns a flat **100%** to unrated sovereigns. There is no OECD
    bifurcation (0% OECD / 100% non-OECD) — that was a Basel I/II legacy not carried forward
    into CRR or Basel 3.1. Domestic currency exemption (Art. 114(4)) is a separate provision
    allowing 0% for GBP-denominated UK government exposures.

---

## PSE and RGLA Risk Weights (Art. 115–116)

PSE (Public Sector Entities) and RGLA (Regional Governments and Local Authorities)
risk weights are largely unchanged from CRR. The key Basel 3.1 clarification concerns
non-UK unrated exposures.

!!! warning "Non-UK Unrated PSE/RGLA — Sovereign-Derived, Not Flat 100%"
    Unrated non-UK PSE and RGLA exposures should use **sovereign CQS-derived weights**
    (Art. 115(1)(a) Table 1A for RGLA, Art. 116(1) Table 2 for PSE), not a flat 100%.
    The sovereign CQS maps to the following risk weights:

    **RGLA sovereign-derived (Art. 115(1)(a), Table 1A):**

    | Sovereign CQS | RGLA Risk Weight |
    |---------------|-----------------|
    | CQS 1 | 20% |
    | CQS 2 | 50% |
    | CQS 3 | 100% |
    | CQS 4 | 100% |
    | CQS 5 | 100% |
    | CQS 6 | 150% |
    | Unrated sovereign | 100% |

    **PSE sovereign-derived (Art. 116(1), Table 2):**

    | Sovereign CQS | PSE Risk Weight |
    |---------------|----------------|
    | CQS 1 | 20% |
    | CQS 2 | 50% |
    | CQS 3 | 100% |
    | CQS 4 | 100% |
    | CQS 5 | 100% |
    | CQS 6 | 150% |
    | Unrated sovereign | 100% |

    UK PSEs and RGLAs are entitled to preferential treatment per Art. 115(5) /
    Art. 116(3) (20% for sterling-denominated short-term). See the CRR spec for
    full table details: [CRR SA Risk Weights — RGLA/PSE](../crr/sa-risk-weights.md).

!!! warning "Code Issue — P1.112"
    The calculator currently defaults non-UK unrated PSE/RGLA to a flat **100%**
    instead of performing the sovereign CQS lookup. This overstates capital for
    non-UK PSE/RGLA backed by well-rated (CQS 1–2) sovereigns (e.g., Germany: 20%
    vs incorrectly assigned 100%). See P1.112 in IMPLEMENTATION_PLAN.md.

### Art. 116(4) — Competent-Authority Equivalence Not Retained

PRA PS1/26 Art. 116(4) is marked `[Note: Provision left blank]` (ps126app1.pdf p.38), and the PS1/26 rule is stated to correspond only to CRR Art. 116(1)–(3). The CRR Art. 116(4) route — permitting, in **exceptional circumstances**, a PSE exposure to be treated as an exposure to the central government, regional government or local authority where an **appropriate guarantee** exists and the competent authorities determine there is no difference in risk — has **no Basel 3.1 successor**.

From 1 January 2027, any guarantee-based RGLA/sovereign substitution for a PSE must be routed through the general CRM guarantee substitution regime (PS1/26 Art. 235, Chapter 4) rather than through an Art. 116-specific carve-out. See the [CRR PSE spec — Sub-treatment 3](../crr/sa-risk-weights.md#sub-treatment-3-competent-authority-equivalence-art-1164) for the CRR-side text.

### Art. 116(5) — Third-Country PSE Equivalence Preserved by Cross-Reference

PRA PS1/26 Art. 116(5) itself is marked `[Note: Provision not in PRA Rulebook]`, but PS1/26 Art. 116(3A) explicitly cross-refers to "Article 116(5) of CRR" to redirect the "UK public sector entities" references in paragraphs 1 and 2 to third-country PSEs when CRR Art. 116(5) applies. The Art. 112 class-mapping table (ps126app1.pdf p.34) likewise lists "Article 116 or Article 116(5) of CRR" as the basis for PSE class assignment. The CRR Art. 116(5) third-country equivalence gate (Treasury equivalence determination; otherwise flat 100%) therefore remains operative under Basel 3.1.

!!! warning "Art. 116(4)/(5) Not Implemented"
    Neither the CRR Art. 116(4) guarantee-backed equivalence nor the CRR Art. 116(5) / PS1/26 Art. 116(3A) third-country equivalence is implemented in the SA calculator. PSE exposures are routed solely through Art. 116(1)/(2) Tables 2/2A and the Art. 116(3) short-term preferential. Firms relying on guarantee-backed substitution or third-country equivalence must apply the determination upstream of the engine.

---

## MDB Exposures (Art. 117)

### Named MDBs at 0% (Art. 117(2))

The 16 named MDBs receiving a **0% risk weight** are unchanged from CRR — see
[CRR SA Risk Weights — Named MDBs](../crr/sa-risk-weights.md#named-mdbs-at-0-art-1172)
for the full list.

### Rated Non-Named MDBs — Table 2B (Art. 117(1)(a))

PRA PS1/26 Art. 117(1) replaces the CRR "treated as institution" approach with a **dedicated
MDB risk weight table (Table 2B)**. Non-named MDBs with an ECAI rating use Table 2B:

| CQS | Risk Weight |
|-----|-------------|
| 1   | 20%         |
| 2   | 30%         |
| 3   | 50%         |
| 4   | 100%        |
| 5   | 100%        |
| 6   | 150%        |

### Unrated Non-Named MDBs (Art. 117(1)(b))

Unrated non-named MDBs receive a risk weight of **50%**.

### Key Change from CRR

| Aspect | CRR (Art. 117(1)) | Basel 3.1 (Art. 117(1)) |
|--------|-------------------|------------------------|
| Treatment | "Same as institutions" (use Art. 120/121 tables) | Dedicated Table 2B |
| CQS 2 | 50% (institution Table 3) | **30%** (Table 2B) |
| Unrated | Institution-dependent (Art. 121 sovereign-derived) | **50%** (fixed) |
| Short-term preferential | Excluded (Art. 117(1)) | N/A (Table 2B is CQS-only) |

!!! info "Four Named Non-0% MDBs"
    Art. 117(1) names four MDBs that use Table 2B (not on the 0% list): Inter-American
    Investment Corporation, Black Sea Trade and Development Bank, Central American Bank
    for Economic Integration, and CAF — Development Bank of Latin America.

---

## Institution Risk Weights — ECRA (Art. 120)

The External Credit Risk Assessment (ECRA) approach uses the institution's own ECAI rating.

**Table 3 — Institution ECRA Risk Weights (Art. 120(1))**

| CQS | Risk Weight | Change from CRR |
|-----|-------------|-----------------|
| CQS 1 | 20% | Unchanged |
| CQS 2 | **30%** | CRR = 50% |
| CQS 3 | 50% | Unchanged |
| CQS 4 | 100% | Unchanged |
| CQS 5 | 100% | Unchanged |
| CQS 6 | 150% | Unchanged |

!!! warning "CQS 2 Change from CRR"
    The CRR CQS 2 rate for institutions is **50%** (Art. 120 Table 3, confirmed from UK onshored
    CRR PDF p.119). Basel 3.1 reduces this to **30%** (PRA PS1/26 Art. 120 Table 3, p.40).
    This 20pp reduction for well-rated (A-range) institutions is a deliberate Basel 3.1 change,
    not a pre-existing UK CRR deviation. See D3.17 for the code bug where CRR uses 30%.

### ECRA Short-Term (Art. 120(2), Table 4)

For exposures with an original maturity ≤ 3 months:

| CQS | Short-Term RW |
|-----|--------------|
| CQS 1 | 20% |
| CQS 2 | 20% |
| CQS 3 | 20% |
| CQS 4 | 50% |
| CQS 5 | 50% |
| CQS 6 | 150% |

Art. 120(2) keys on **original** maturity (not residual), mirroring CRR Art. 119(2).
The opening clause "Subject to paragraph 3" cross-refers to the Art. 120(3) interaction
rules below — when a specific short-term ECAI assessment exists, Table 4A (Art. 120(2B))
may override Table 4 for that exposure.

### ECRA Short-Term Trade Finance Exception (Art. 120(2A), Table 4)

Basel 3.1 extends the Table 4 short-term preferential window from 3 months to **6 months**
for rated institution exposures whose tenor is driven by the underlying flow of goods,
mirroring the SCRA carve-out at [Art. 121(4)](#scra-short-term-trade-finance-exception-art-1214).
The exception preserves the BCBS CRE20.20 capital treatment of cross-border documentary
credits and similar short-dated trade instruments that would otherwise miss the 3-month
window and fall back to the Table 3 long-term weights.

!!! quote "Art. 120(2A) — verbatim (PRA PS1/26 p. 40)"
    "Subject to paragraph 3, exposures to institutions for which a credit assessment by a
    nominated ECAI is available where the **original maturity of the exposure was six
    months or less and the exposure arose from the movement of goods** shall be assigned
    a risk weight in accordance with the credit quality step in Table 4 which corresponds
    to the relevant credit assessment of the ECAI as mapped in Commission Implementing
    Regulation (EU) 2016/1799 of 7 October 2016."

**Trigger.** Both limbs must be satisfied:

- **(a)** The exposure is to an institution with a long-term ECAI credit assessment
    (the ECRA path — unrated institutions use SCRA under Art. 121 and pick up the
    analogous Art. 121(4) exception).
- **(b)** The exposure has **original maturity ≤ 6 months** *and* **arose from the
    movement of goods**. Both sub-conditions must hold — a 6-month working-capital
    facility unrelated to goods movement does not qualify; it reverts to Table 3.

**Effect.** Table 4 weights apply (CQS 1–3 = 20%, CQS 4–5 = 50%, CQS 6 = 150%), even
though the exposure's tenor exceeds the general Art. 120(2) ≤ 3 months threshold. For a
rated CQS 4 trade-goods exposure with 5-month original maturity, Table 4 gives 50% vs
Table 3's 100% — a 50pp (halving) capital saving for genuine trade finance.

**Worked example.** A 5-month USD-denominated documentary credit financing cross-border
shipment of goods from a CQS 3-rated foreign bank to a UK buyer:

- Rated institution on the ECRA path → Art. 120 applies.
- Original maturity 5 months > 3 months → Art. 120(2) (Table 4) would not apply directly.
- Original maturity ≤ 6 months **and** arose from the movement of goods → Art. 120(2A)
    extends Table 4 eligibility.
- CQS 3 Table 4 weight = **20%** (vs Table 3 CQS 3 = 50%).
- 30pp RW reduction preserved relative to a non-trade-finance 5-month exposure.

!!! info "Distinction from Art. 121(4) SCRA trade-finance exception"
    Art. 120(2A) (ECRA) and [Art. 121(4)](#scra-short-term-trade-finance-exception-art-1214)
    (SCRA) are the **rated** and **unrated** counterparts of the same 6-month trade-goods
    carve-out. Both use a 6-month original-maturity threshold and the same "arose from
    the movement of goods" scope test; they differ only in the underlying risk-weight
    table (Table 4 CQS bands for Art. 120(2A) versus Table 5A SCRA grades for Art. 121(4)).

    | Feature | Art. 120(2A) — ECRA | Art. 121(4) — SCRA |
    |---------|---------------------|--------------------|
    | Counterparty | Rated institution | Unrated institution |
    | Source table | Table 4 (short-term ECRA) | Table 5A (short-term SCRA) |
    | Max tenor | Original maturity ≤ 6m | Original maturity ≤ 6m |
    | Scope test | Arose from movement of goods | Arose from movement of goods |
    | Replaces | Art. 120(2) ≤ 3m window | Art. 121(3) ≤ 3m window |

!!! note "Interaction with Art. 120(2B) Table 4A"
    The opening "Subject to paragraph 3" in Art. 120(2A) means the Art. 120(3) interaction
    rules between Table 4 and Table 4A apply just as they do for the Art. 120(2) 3-month
    window. Where the institution also has a specific short-term ECAI assessment:

    - **(a)** No short-term ECAI → Art. 120(2A) applies as described above.
    - **(b)** Short-term ECAI yields a more favourable or identical RW → Table 4A (short-term
        ECAI) applies for that specific exposure; other trade-goods short-term exposures
        to the same obligor keep Table 4 under Art. 120(2A).
    - **(c)** Short-term ECAI yields a less favourable RW → the general preferential
        treatment of (2)/(2A) is withdrawn; all unrated short-term claims against that
        obligor take the specific short-term assessment's RW.

    Art. 120(2A) does **not** short-circuit the due-diligence step-up at
    [Art. 120(4)](#rated-institution-due-diligence-cqs-step-up-art-1204). A firm whose DD
    reveals higher risk than the CQS implies must still step up within the same short-term
    table — a Table 4 CQS 3 (20%) trade-finance exposure stepped up one CQS moves to the
    CQS 4 band (50%) within Table 4.

!!! warning "CRR has no direct analogue"
    CRR Art. 120(2) provides only a single short-term preferential window keyed to
    **residual** maturity ≤ 3 months (no original-maturity variant, no 6-month trade-goods
    extension). A 5-month trade-goods exposure to a rated CRR institution reverts to the
    Table 3 long-term weight regardless of its trade-finance character. Basel 3.1
    Art. 120(2A) closes this gap by aligning the UK framework with BCBS CRE20.20.

**Implementation.** The SA calculator routes Art. 120(2A) through the same ECRA
short-term branch as Art. 120(2), gated on the `is_short_term_trade_lc` input field
(already used by the Art. 121(4)/121(6) SCRA branches). When
`is_short_term_trade_lc = True` *and* `original_maturity_years ≤ 0.5`, a rated
institution exposure receives Table 4 weights even if the standard ≤ 0.25 window has
been missed. The logic sits in the B31 ECRA maturity branch in
`src/rwa_calc/engine/sa/namespace.py`:

```python
# ECRA short-term rated institutions — Art. 120(2) Table 4 extended by Art. 120(2A).
chain.when(
    is_institution
    & is_rated
    & (
        (original_mty <= 0.25)                                        # Art. 120(2) — ≤ 3m
        | (pl.col("is_short_term_trade_lc").fill_null(False)          # Art. 120(2A) — ≤ 6m
           & (original_mty <= 0.5))                                   #   trade-goods gate
    )
)
```

Required input fields:

| Field | Type | Purpose |
|-------|------|---------|
| `is_short_term_trade_lc` | Bool | Flags self-liquidating trade arising from movement of goods |
| `original_maturity_years` | Float | Original (not residual) maturity in years |
| `cqs` | Int | ECAI credit quality step for Table 3/4 lookup |

!!! warning "Firm responsibility — upstream classification"
    The calculator relies on the firm's upstream classification of
    `is_short_term_trade_lc = True` for genuine self-liquidating trade finance arising
    from goods movement. The engine does not re-verify trade-finance eligibility; mis-flagged
    non-trade short-term exposures will incorrectly pick up Table 4 weights. Evidence of
    eligibility (underlying invoice, shipping documents, trade-finance classification) should
    be retained by the firm in line with Art. 110A(4)(d) per-exposure documentation.

### ECRA Short-Term ECAI (Art. 120(2B), Table 4A)

New in Basel 3.1 — for exposures with a specific short-term ECAI assessment:

| Short-Term CQS | Risk Weight |
|----------------|-------------|
| CQS 1 | 20% |
| CQS 2 | 50% |
| CQS 3 | 100% |
| CQS 4 | 150% |
| CQS 5 | 150% |

!!! note "Table 4A Schema Gap"
    The `has_short_term_ecai` schema field is not yet implemented. The calculator
    currently falls back to Table 4 (general short-term preferential) for all short-term
    institution exposures. See D3.8.

### Rated Institution Due Diligence CQS Step-Up (Art. 120(4))

Basel 3.1 introduces a class-specific CQS step-up rule for **rated** institution exposures
that sits alongside the [framework-wide Art. 110A due diligence obligation](#due-diligence-obligation-art-110a)
discussed earlier in this specification. The rule is textually parallel to
[Art. 122(4) for rated corporates](#rated-corporate-due-diligence-cqs-step-up-art-1224)
and [Art. 129(4A) for covered bonds](#covered-bond-due-diligence-cqs-step-up-art-1294a).

!!! quote "Art. 120(4) — verbatim (PRA PS1/26 p. 41)"
    "An institution shall conduct due diligence to ensure that the external credit
    assessments appropriately and prudently reflect the risk of the exposure to which
    the institution is exposed. If the due diligence analysis reflects higher risk
    characteristics than that implied by the credit quality step of the exposure, the
    institution shall assign a risk weight associated with a credit quality step that
    is at least one step higher than the risk weight determined by the external credit
    assessment."

**Trigger.** Applies whenever a rated institution exposure uses Art. 120(1) Table 3 (or
the short-term Art. 120(2B) Table 4A once implemented — see
[ECRA Short-Term ECAI (Art. 120(2B), Table 4A)](#ecra-short-term-ecai-art-1202b-table-4a))
for its risk weight and the firm's internal due diligence reveals risk characteristics
higher than the ECAI-implied credit quality step.

**Effect.** The firm must assign the risk weight of the **next CQS step higher**. Worked
examples against Table 3:

| ECAI CQS | ECAI RW | Step-up CQS | Step-up RW | Uplift |
|----------|---------|-------------|------------|--------|
| CQS 1 | 20% | CQS 2 | 30% | +10 pp |
| CQS 2 | 30% | CQS 3 | 50% | +20 pp |
| CQS 3 | 50% | CQS 4 | 100% | +50 pp |
| CQS 4 | 100% | CQS 5 | 100% | 0 (already at CQS-4/5 plateau) |
| CQS 5 | 100% | CQS 6 | 150% | +50 pp |
| CQS 6 | 150% | — | 150% | 0 (already at cap) |

Art. 120(4) is **not** a discretionary floor — it is a mandatory override where the DD
finding is triggered. The CQS 4 → CQS 5 row yields no uplift because Table 3 assigns
both bands the same 100% weight; the mandatory step-up still applies in name but the
resulting RW is unchanged until CQS 6 (150%) is reached.

!!! note "Short-term applicability"
    When the starting weight is drawn from Art. 120(2) Table 4 (general short-term
    preferential) or Art. 120(2B) Table 4A (short-term ECAI assessment), the one-step
    uplift is applied within the same table rather than reverting to long-term Table 3
    weights. For example, a Table 4 CQS 2 exposure (20%) stepped up under Art. 120(4)
    moves to the Table 4 CQS 3 band (still 20%) and then, if DD points further, to the
    CQS 4 band (50%). The step-up operates on the credit quality step itself, not on
    the maturity overlay.

**Distinction from Art. 110A.** Art. 120(4) is a narrower, rated-exposure-only rule with
a fixed one-step uplift; [Art. 110A](#due-diligence-obligation-art-110a) applies to every
non-exempt SA exposure (rated or unrated) and permits an unbounded uplift. The two rules
can interact: a firm's DD finding may be satisfied either by a one-step CQS uplift under
Art. 120(4) or by a larger uplift channelled through the Art. 110A
`due_diligence_override_rw` path. Where both would apply, the final RW is
`max(RW_Art_120_4, RW_Art_110A_override, RW_ECAI)`.

**Distinction from SCRA (Art. 121).** Art. 120(4) applies to **rated** institutions only.
Unrated institution exposures are routed to the SCRA grade table at
[Institution Risk Weights — SCRA (Art. 121)](#institution-risk-weights-scra-art-121)
and do not use the ECAI-based step-up at all. A rated institution whose DD reveals
higher-than-implied risk is stepped up one CQS band under Art. 120(4); it is **not**
reclassified into SCRA.

**Parallel provisions.** Art. 120(4) is textually near-identical to two other
class-specific step-up rules in PS1/26:

| Provision | Obligor class | RW reference |
|-----------|---------------|--------------|
| **Art. 120(4)** | **Rated institutions** | **Art. 120(1) Table 3** |
| Art. 122(4) | Rated corporates | Art. 122(1) Table 6 |
| Art. 129(4A) | Covered bonds | Art. 129(4) Table 7 / Art. 129(5) unrated derivation |

All three share the same trigger ("DD reveals higher risk than implied by the CQS") and
the same consequence ("at least one CQS step higher"). CRR has no equivalent provision
for any of the three classes — the rules are Basel 3.1-only. For rated institutions
specifically, the CRR ECAI-based approach in Art. 120 Table 3 is applied without any
direct DD step-up mechanism; firms relied solely on Art. 79 CRD (sound credit-granting)
and ICAAP-level overlays.

**Implementation status.** The calculator does not yet implement a dedicated Art. 120(4)
branch. Firms currently carry Art. 120(4) findings through the Art. 110A pathway: set
`due_diligence_override_rw` on the facility to the next-CQS-band weight drawn from
Table 3 (or Table 4 / Table 4A for short-term exposures), and the SA calculator will
apply it as a directional floor (see
[Implementation](#implementation) earlier in this specification). This is functionally
equivalent and captured in the output via the `due_diligence_override_applied` audit
column.

!!! warning "Firm responsibility — not an engine determination"
    The engine does not evaluate whether a DD finding is material enough to trigger
    Art. 120(4). The firm determines when the step-up applies; the calculator only
    applies the resulting RW as a floor. Evidence that the step-up has been considered
    should be traceable to the firm's DD process documentation.

---

## Institution Risk Weights — SCRA (Art. 121)

The Standardised Credit Risk Assessment (SCRA) approach applies when ECAI ratings are not available.
This replaces the CRR sovereign-derived approach (CRR Art. 121, Table 5).

| Grade | Risk Weight | Short-Term (≤3m) | Criteria |
|-------|-------------|------------------|----------|
| Grade A enhanced | **30%** | 20% | CET1 ≥ 14%, leverage ratio ≥ 5% (Art. 121(5)) |
| Grade A | **40%** | 20% | Adequate capacity to meet financial commitments robust to the cycle; meets published minimum requirements **and buffers** (Art. 121(1)(a)) |
| Grade B | **75%** | 50% | Substantial credit risk but meets published minimum requirements (**excluding buffers**) (Art. 121(1)(b)) |
| Grade C | **150%** | 150% | Material default risk; does not meet Grade B requirements, or adverse audit / going-concern opinion in last 12 months (Art. 121(1)(c)) |

!!! info "Grade A vs Grade A Enhanced"
    Grade A enhanced (30%, Art. 121(5)) requires **quantitative** thresholds: CET1 ≥ 14% and
    leverage ratio ≥ 5%. Grade A (40%) requires only **qualitative** compliance: the institution
    meets all minimum requirements and capital buffers. This distinction is new in Basel 3.1
    (CRE20.19).

### SCRA Disclosure Barring Rules (Art. 121(1)(a), (1)(b))

Art. 121(1) ties each SCRA grade to the **public disclosure** of the institution's
minimum financial regulatory requirements. The disclosure tests are asymmetric between
Grade A and Grade B and form a two-step barring ladder rather than a single
"undisclosed → Grade C" rule. A single piece of missing disclosure can bar Grade A
without forcing Grade C, producing a Grade B outcome that the simpler "undisclosed →
Grade C" characterisation would miss.

| Disclosure state                                                         | Consequence                                                  | Article        |
|--------------------------------------------------------------------------|--------------------------------------------------------------|----------------|
| Minimum requirements **and** buffers publicly disclosed                  | Grade A available (subject to qualitative adequacy in (1)(a)) | Art. 121(1)(a) |
| Minimum requirements disclosed; **buffers not disclosed**                | **May not be classified as Grade A** → Grade B at best       | Art. 121(1)(a) |
| Minimum requirements **not disclosed**                                   | **Shall be classified as Grade C**                           | Art. 121(1)(b) |

!!! quote "Art. 121(1)(a) — Grade A disclosure barring (ps126app1.pdf p. 42)"
    If such minimum financial regulatory requirements **and buffers** (other than
    institution-specific minimum requirements or buffers) are not publicly disclosed
    or otherwise made available by the counterparty institution, the counterparty
    institution **may not be classified as Grade A**.

!!! quote "Art. 121(1)(b) — Grade C forced classification (ps126app1.pdf p. 42)"
    If such minimum financial regulatory requirements are not publicly disclosed or
    otherwise made available by the counterparty institution, the counterparty
    institution **shall be classified as Grade C**.

**Institution-specific carve-out.** Both tests exclude "institution-specific"
minimum requirements or buffers imposed through **supervisory actions and not made
public** — a confidential Pillar 2A add-on kept private by the home supervisor does
not itself trigger either barring rule. The disclosure test applies only to the
**publicly applicable** prudential framework. For CRR firms, Art. 121(1A) defines
that baseline as the Required Level of Own Funds (CRR Part Art. 92), the additional
own funds required by regulation 34(1) of the Capital Requirements Regulations, the
minimum leverage ratio requirement (Leverage Ratio — Capital Requirements and Buffers
Part 3.1), the combined buffer (Capital Buffers Part 1.1), the countercyclical
leverage ratio buffer, and the additional leverage ratio buffer.

**Third-country counterparties (Art. 121(1B)).** For counterparties outside the UK,
the disclosure test extends to any **local-equivalent or additional** regulatory
requirements and buffers, so long as they are published and required to be met by
CET1, Tier 1, or other own funds. A US G-SIB whose home supervisor requires a
jurisdiction-specific SCB is assessed on the disclosure of that SCB alongside the
baseline Basel minima. This is distinct from the Art. 119(3) third-country
equivalence gate that governs whether the institution treatment is available at all.

!!! warning "Near-final → final correction (PS9/24 → PS1/26)"
    The near-final rules drafted the (1)(a) barring rule as "shall not be classified
    as **Grade B or lower**" — a Grade B *floor*. Final PS1/26 inverted the direction
    to "may not be classified as **Grade A**" — a Grade A *ceiling*. The two
    formulations sound similar but produce opposite outcomes for an institution that
    discloses requirements but withholds buffers: near-final would have forced
    Grade A; final forces Grade B at best. Firms reconciling implementation against
    PS9/24 drafts must pick up this change.

**Implementation status.** The calculator consumes `scra_grade` as a pre-determined
input (`A` / `A_ENHANCED` / `B` / `C`). Both barring rules are therefore **firm-side
governance responsibilities** — the firm must evaluate disclosure (requirements
*and* buffers for Grade A; requirements alone for Grade B) before passing the grade
to the calculator. No dedicated input field flags the disclosure test outcome; no
audit column surfaces the (1)(a) ceiling or (1)(b) forced-to-C path.

### SCRA Short-Term Trade Finance Exception (Art. 121(4))

Self-liquidating trade-related exposures arising from the movement of goods with an
original maturity ≤ 6 months may receive the short-term risk weight applicable to
Table 5A (Grade A/A enhanced: 20%, Grade B: 50%, Grade C: 150%) even if the exposure
is not otherwise eligible for short-term preferential treatment. This exception ensures
trade finance exposures are not penalised by the full-term SCRA weights.

### SCRA Sovereign Floor for Foreign-Currency Exposures (Art. 121(6))

Notwithstanding Art. 121 paragraphs (2) to (5), the risk weight assigned to an unrated
institution exposure **may not be lower** than the risk weight applicable to the central
government of the jurisdiction where the institution is incorporated (per Art. 114(1)
and (2)) when **both** of the following conditions are met:

- **(a) Foreign currency.** The exposure is denominated in a currency other than the
    local currency of the institution's jurisdiction of incorporation. For exposures
    booked through a branch of the institution in a foreign jurisdiction, the test
    is against the local currency of the jurisdiction in which the branch operates.
- **(b) Not short-term self-liquidating trade.** The exposure is **not** a self-liquidating,
    trade-related contingent item arising from the movement of goods with an original
    maturity of less than one year.

When both conditions hold, the SCRA grade weight (Grade A: 40%, Grade A enhanced: 30%,
Grade B: 75%, Grade C: 150%) is overridden by `max(SCRA_grade_RW, sovereign_RW)`. The
floor binds whenever the institution's home sovereign carries a higher risk weight than
the SCRA grade derives — for example, an unrated Grade A institution (40%) of a
sovereign at CQS 4 (100%) is floored at 100%.

**Worked example.** A USD-denominated 2-year loan to an unrated Brazilian bank
(Brazil sovereign CQS 4 → 100%) classified as SCRA Grade A (40%):

- Condition (a): exposure currency USD ≠ Brazil's local currency BRL → **met**.
- Condition (b): not a trade-related contingent item, original maturity > 1 year → **met**.
- Floor applies: `RW = max(40%, 100%) = 100%`.

A 6-month USD-denominated documentary credit financing the movement of goods to the
same bank would fail condition (b) and retain the SCRA Grade A 40% weight (or the
Art. 121(4) Table 5A 20% weight if it qualifies for the trade-finance preferential
treatment).

!!! info "Distinct from Art. 121(4) Trade Finance Exception"
    Art. 121(4) and Art. 121(6) both reference trade finance, but they operate
    independently:

    - **Art. 121(4)** is a *preferential* RW for self-liquidating trade ≤ **6 months**
        (Table 5A weights, e.g. Grade A: 20%).
    - **Art. 121(6)** is a *floor* for foreign-currency exposures, with a *carve-out*
        for self-liquidating trade < **1 year**. The carve-out disapplies the floor;
        it does not assign a preferential weight.

    A 9-month foreign-currency self-liquidating trade exposure is below the (6) floor
    (carved out) but above the (4) trade-finance threshold (>6 months) — it receives
    the standard SCRA grade weight (e.g. Grade A: 40%), neither floored to sovereign
    nor reduced to Table 5A.

!!! note "Cross-Reference: Art. 121(6) vs Currency Mismatch Multiplier (Art. 123B)"
    The Art. 121(6) sovereign floor applies to unrated **institution** exposures.
    The Art. 123B currency mismatch multiplier (1.5×, 150% cap) is a distinct
    mechanism applying to **retail and residential mortgage** exposures where the
    obligor's income currency differs from the loan currency. Both mechanisms
    address foreign-currency risk but at different points in the framework.

**Implementation.** The floor is applied in `_apply_sovereign_floor_for_institutions()`
within `engine/sa/calculator.py`. Required input fields:

| Field | Type | Purpose |
|-------|------|---------|
| `currency` | String | Loan currency (ISO code) |
| `cp_local_currency` | String | Counterparty's home jurisdiction currency |
| `cp_sovereign_cqs` | Int | Sovereign CQS for floor RW lookup (Art. 114(1)/(2)) |
| `is_short_term_trade_lc` | Bool | Marks self-liquidating trade ≤ 1 year for (b) carve-out |
| `original_maturity_years` | Float | Maturity check for the (b) carve-out (< 1 year) |

When `cp_local_currency` is unavailable, the calculator falls back to a domestic-currency
heuristic; upstream enrichment is recommended for accurate floor application.

---

## ECAI Assessment — Implicit Government Support (Art. 138(1)(g), Art. 139(6))

Basel 3.1 introduces two new anti-arbitrage provisions governing how institution ECAI
ratings that incorporate assumptions of implicit government support may be used to
determine risk weights for institution exposures. Art. 138(1)(g) is a general
prohibition on the nominated-ECAI side; Art. 139(6) is the residual "higher-of" rule
that applies where the prohibition binds and an issue-specific rating is nonetheless
available.

Both provisions apply **only to exposures where the obligor is an institution** (Art.
139(6)(a)). They do not alter the risk weighting of exposures to sovereigns,
corporates, retail obligors, or other SA classes, and they do not change the single-
or multi-rating resolution mechanics in
[hierarchy-classification — Multi-Rating Resolution](../common/hierarchy-classification.md#multi-rating-resolution-crr-art-138)
beyond the institution-obligor carve-out documented here.

### Regulatory text (PRA PS1/26, ps126app1.pdf pp. 70–72)

!!! quote "Art. 138(1)(g) — Implicit government support prohibition"
    An institution shall not use a credit assessment that incorporates assumptions of
    implicit government support for the purposes of assigning a risk weight to an
    exposure to an institution, unless the respective credit assessment applies to an
    institution owned by or set up and sponsored by central governments, regional
    governments or local authorities.

!!! quote "Art. 139(6) — Higher-of rule for institution exposures"
    An institution, when determining the risk weight of an exposure to an issue where:

    (a) the obligor is an institution; and

    (b) there is no issue-specific credit assessment available from a nominated ECAI
    that does not incorporate assumptions of implicit government support in accordance
    with the requirements of point (g) of Article 138(1),

    shall use the higher of the following risk weights:

    (i) the risk weight that would be assigned to the exposure in accordance with
    paragraphs 2 to 2B and 4, and Article 138;

    (ii) if an issue-specific credit assessment is available from a nominated ECAI,
    the risk weight that would be assigned to the exposure if the institution used an
    issue-specific credit assessment, disregarding point (g) of Article 138(1).

### Trigger

Art. 139(6) fires only when **all three** of the following conditions hold
simultaneously:

| Condition | Requirement |
|-----------|-------------|
| Obligor class | Obligor is an institution (Art. 139(6)(a)). Sovereign, corporate, retail, and RE exposures are out of scope. |
| No "clean" issue-specific rating | The portfolio lacks an issue-specific ECAI assessment that explicitly excludes implicit government support (Art. 139(6)(b)). |
| Art. 138(1)(g) exemption does not apply | The institution is **not** owned by, or set up and sponsored by, central governments, regional governments, or local authorities. If it is, the implicit-support-based assessment may be used directly without the higher-of comparison. |

### Effect

When the trigger is met, the firm computes **two** candidate risk weights and applies
the **higher**:

| Candidate | Source | Art. 138(1)(g) treatment |
|-----------|--------|--------------------------|
| (i) Baseline | Art. 139(2)–(2B), 139(4), and Art. 138 — i.e. the general ECAI rules applied to the issuer-level or reference-issue assessment that complies with Art. 138(1)(g) (implicit support excluded). | Implicit-support assessments suppressed; only "clean" ratings enter the selection. |
| (ii) Issue-specific override | Art. 138 applied to the issue-specific rating **disregarding Art. 138(1)(g)** — i.e. the implicit-support assessment is allowed back in. Only computable if an issue-specific rating exists for this specific exposure. | Implicit support permitted, producing the unadjusted rated weight. |

Effective rule: `RW = max(RW_baseline, RW_issue_specific_with_support)`. If no
issue-specific rating exists, (ii) is undefined and the baseline (i) applies without
comparison.

### Worked example

Consider a 5-year senior-unsecured bond issued by "Bank X" — an institution **not**
owned or sponsored by a government (so the Art. 138(1)(g) exemption does not apply):

- **Bank X's general issuer rating** (from its nominated ECAI) is BBB+ (CQS 3), which
    includes implicit sovereign support in the agency's methodology. Without that
    support, the agency would rate Bank X at BB+ (CQS 5).
- **The specific bond** carries an issue-specific rating of BBB+ (CQS 3), also
    incorporating implicit support.

Application of Art. 139(6):

1. **Candidate (i) — baseline with Art. 138(1)(g) applied.** The BBB+ general rating
     is disallowed because it incorporates implicit support. The firm must step back to
     any remaining "clean" assessment. If none exists, the exposure is treated as
     unrated under Art. 139(2) final sentence ("in all other cases, the exposure shall
     be treated as unrated") — 100% under Art. 121 SCRA defaulting to Grade A/B, or the
     relevant CQS derived from the BB+ clean rating if one is published (→ CQS 5,
     100%).
2. **Candidate (ii) — issue-specific disregarding Art. 138(1)(g).** The BBB+
     issue-specific rating is used as-is → CQS 3 → 50% under Art. 120 Table 3.
3. **Apply the higher:** `RW = max(100%, 50%) = 100%`.

The firm cannot simply lean on the cleaner-looking issue-specific 50% weight — the
higher-of rule forces recognition of the unsupported creditworthiness whenever the
issue-specific rating relies on implicit support.

### Art. 138(1)(g) exemption — government-owned or government-sponsored institutions

Where the rated institution is **owned by or set up and sponsored by central
governments, regional governments, or local authorities**, Art. 138(1)(g) does not
apply and implicit-support ratings may be used directly. Art. 139(6) never engages for
these institutions (there is no "clean" rating requirement to fail). Typical examples:

- State-owned development banks, policy banks, and export-credit agencies
- RGLA-owned local banks
- Municipally-sponsored clearing or settlement institutions

The exemption is a narrow one: **private institutions whose ratings benefit from
market-anticipated sovereign bailout expectations** (the classic "too big to fail"
uplift) are **not** exempt — the government must have an actual ownership or
sponsorship relationship with the institution.

### Distinction from Art. 121(6) SCRA Sovereign Floor

Both provisions impose institution-level floors that reference sovereign or support-
adjusted risk, but they sit in different parts of the framework and address different
facts:

| Aspect | Art. 139(6) — Higher-of | Art. 121(6) — SCRA sovereign floor |
|--------|-------------------------|-------------------------------------|
| Obligor scope | Institutions only | Unrated institutions only (SCRA path) |
| Rated/unrated | **Rated** institutions (ECRA path) | **Unrated** institutions (SCRA path) |
| Mechanic | `max(baseline_clean_RW, issue_specific_with_support_RW)` | `max(SCRA_grade_RW, home_sovereign_RW)` |
| Trigger | Implicit support in ECAI rating + no "clean" issue-specific rating | Foreign-currency exposure + not short-dated self-liquidating trade |
| Anti-arbitrage target | Prevents firms selecting the cleaner issue-specific rating to escape the Art. 138(1)(g) prohibition | Prevents unrated-institution weights falling below the home sovereign's own weight |

The two rules are complementary rather than alternatives: Art. 139(6) governs the
ECRA path when implicit support is embedded in the rating; Art. 121(6) governs the
SCRA path when there is no rating at all.

### Comparison to CRR

| Element | CRR Art. 138 / Art. 139 | Basel 3.1 Art. 138 / Art. 139 |
|---------|--------------------------|--------------------------------|
| Art. 138(1) sub-points | (a)–(f) only | (a)–(g) — new (g) implicit-support prohibition |
| Art. 139 paragraphs | (1), (2), (3), (4) | (1), (2), (2A), (2B), (2C), (3), (4), (5), (6) — new paragraphs (2A)–(2C), (5), (6) |
| Higher-of rule | Not present | New Art. 139(6) |
| Exemption for government-owned/sponsored institutions | Not applicable (no prohibition) | Art. 138(1)(g) tail clause |

The Art. 139(6) higher-of rule is a **new Basel 3.1 provision** with no CRR analogue.
CRR firms do not suppress implicit-support assessments at all; the rating that
comes out of the Art. 138 multi-rating selection is used directly. The corresponding
CRR spec does **not** document an equivalent mechanism because none exists — see
[CRR SA Risk Weights](../crr/sa-risk-weights.md) for CRR-era Art. 120 institution
treatment, which relies on sovereign-derived weights (CRR Art. 121 Table 5) rather
than the ECAI rating directly for many institution exposures.

### Implementation Status

!!! warning "Not Yet Implemented — Input-Schema Gap"
    The calculator does not currently implement Art. 138(1)(g) or Art. 139(6). Two
    schema-level gaps preclude implementation:

    - The facility schema exposes a single `external_cqs` (post Art. 138 resolution)
        with no indicator of whether the rating is **issue-specific** versus
        **general issuer** — a prerequisite for Art. 139(6)(b).
    - No input field flags whether an ECAI assessment **incorporates implicit
        government support** — a prerequisite for the Art. 138(1)(g) suppression step
        and the Art. 139(6) "clean" vs "with-support" comparison.

    As a result, the calculator treats every rated institution exposure as if the
    rating complies with Art. 138(1)(g) — i.e. no higher-of uplift is applied.
    Firms with material rated-institution portfolios whose ratings embed implicit
    support must either (a) pre-adjust the `external_cqs` input offline to reflect
    the Art. 139(6) higher of the two candidate weights, or (b) use the Art. 110A
    `due_diligence_override_rw` pathway to floor the risk weight at the higher-of
    value. See code-side finding **D3.60** in the docs implementation plan.

### Firm responsibility

Determining whether a specific ECAI assessment incorporates implicit government
support is a **firm governance responsibility** (ECAI methodology review under the
institution's use-test framework) and cannot be automated by the calculator. The
Art. 138(1)(g) exemption (government-owned or government-sponsored) likewise requires
firm-level determination of the ownership / sponsorship relationship.

---

## Corporate Risk Weights (Art. 122)

### CQS-Based Table (Art. 122(1), Table 6)

| CQS | Risk Weight |
|-----|-------------|
| CQS 1 | 20% |
| CQS 2 | 50% |
| CQS 3 | 75% |
| CQS 4 | 100% |
| CQS 5 | **150%** |
| CQS 6 | 150% |
| Unrated | 100% |

!!! warning "PRA Deviation — CQS 5 = 150%"
    BCBS CRE20.42 reduced corporate CQS 5 from 150% to 100%. The PRA retained **150%** per
    PRA PS1/26 Art. 122(1) Table 6.

### Corporate Sub-Categories (Art. 122(4)–(11))

New in Basel 3.1 — corporates are divided into sub-categories with differentiated risk weights:

| Sub-Category | Risk Weight | Conditions | Reference |
|-------------|-------------|------------|-----------|
| SME corporate | **85%** | Turnover ≤ GBP 44m (PS1/26 Glossary SME definition, p.9; diverges from BCBS/CRR EUR 50m SF threshold) | Art. 122(11) |
| Investment grade (IG) | **65%** | PRA permission + internal IG assessment (Art. 122(9)–(10)) | Art. 122(6)(a) |
| Non-IG unrated | **135%** | PRA permission + internal assessment determines non-IG | Art. 122(6)(b) |
| General unrated | **100%** | Default without PRA permission (Art. 122(5)) | Art. 122(5) |

!!! warning "PRA Permission Required for IG/Non-IG Differentiation"
    The 65% IG and 135% non-IG rates require **prior PRA permission** (Art. 122(6)).
    Without permission, all unrated corporates receive the default 100% (Art. 122(5)).
    Investment grade is determined by the **institution's own internal assessment**
    (Art. 122(9)–(10)), not by external rating. SME 85% overrides IG/non-IG regardless
    (Art. 122(11)). IRB firms may elect the IG/non-IG split in the S-TREA leg of the
    output floor under Art. 122(8) — see
    [Output-Floor Election for Unrated Corporates (Art. 122(7)–(8))](#output-floor-election-for-unrated-corporates-art-12278).

### Output-Floor Election for Unrated Corporates (Art. 122(7)–(8))

Art. 122(7) and Art. 122(8) govern how **IRB firms** treat unrated corporate exposures
in the *standardised leg* of the output floor (the `S-TREA` term of the
`TREA = max{U-TREA; x × S-TREA + OF-ADJ}` formula in Art. 92(2A)). The election sits
alongside — but is legally distinct from — the Art. 122(5)/(6) branch a firm uses for
its regular SA application, and it carries its own PRA notification obligation.

!!! quote "Art. 122(7) — verbatim (PRA PS1/26 p. 45)"
    "An institution that has been granted permission in accordance with paragraph 6
    shall ensure it continues to have sound, effective and comprehensive strategies,
    processes, systems and risk management practices that enable it to adequately
    identify and manage its sources of credit and counterparty risk."

!!! quote "Art. 122(8) — verbatim (PRA PS1/26 p. 45)"
    "For the purposes of calculating the output floor, an institution with permission
    to use the IRB Approach shall, for exposures to which it applies the IRB Approach
    within the exposure class set out in point (g) of Article 112(1), subject to
    paragraph 11:

    (a) assign a 100% risk weight to all exposures for which a credit assessment by a
    nominated ECAI is not available; or

    (b) assign the risk weights in points (a) or (b) of paragraph 6 to all exposures
    for which a credit assessment by a nominated ECAI is not available. **An
    institution that assigns, or ceases to assign, risk weights in accordance with
    this point (b) shall give notice to the PRA.**"

**Scope.** Art. 122(8) applies only to:

- institutions with **IRB permission** for corporate exposures (Art. 112(1)(g)); and
- the S-TREA computation used in the output floor under Art. 92(2A) — it does **not**
  alter how the same exposures are risk-weighted for U-TREA (IRB) or for SA firms'
  regular SA capital.

The Art. 122(11) SME carve-out still dominates: regardless of (a) or (b), an exposure
to an SME corporate receives the 85% weight. (a)/(b) only governs the unrated
non-SME population.

**The two branches.**

| Branch | S-TREA treatment of unrated non-SME corporates | PRA notification required? |
|--------|-----------------------------------------------|----------------------------|
| Art. 122(8)(a) | Flat **100%** (mirrors the Art. 122(5) default) | No |
| Art. 122(8)(b) | **65%** IG / **135%** non-IG (the Art. 122(6)(a)/(b) split) | **Yes** — on adoption *and* on cessation |

Branch (b) is only available to firms that **already hold the Art. 122(6) permission**
for their regular SA exposures (Art. 122(7) retains their obligation to maintain sound
processes). A firm without Art. 122(6) permission has only branch (a) available for
S-TREA.

!!! warning "Notification obligation — Art. 122(8)(b) final sentence"
    An IRB firm that elects to use the IG/non-IG split in S-TREA **shall give notice
    to the PRA** both when it starts applying the (b) treatment and when it ceases
    applying it. This is additional to the prior-permission requirement that gates
    Art. 122(6) itself. The notification obligation is symmetric — dropping back to
    branch (a) is equally a notifiable event — so the firm must maintain a record of
    every branch switch for the output-floor population.

!!! info "Consistency requirement — 'all exposures'"
    Both (a) and (b) use the phrase "**all** exposures for which a credit assessment
    by a nominated ECAI is not available". The election is portfolio-wide within the
    output-floor corporate population; a firm cannot cherry-pick branch (b) for
    obligors it has assessed as IG while leaving non-IG obligors on branch (a). A
    firm that has obtained Art. 122(6) permission but assesses no obligor as IG still
    applies 135% to every unrated non-SME corporate under branch (b) — not 100%.

**Why the election matters.** The S-TREA leg of the output floor determines the
minimum RWA for floor-binding IRB firms. Branch (a) fixes every unrated non-SME
corporate at 100%, which is conservative relative to the IG-heavy portfolio most IRB
firms hold. Branch (b) lets the firm recognise its internal IG assessment (65%) in
S-TREA, typically reducing the floor impact materially — at the cost of also taking
the 135% penalty on any obligor assessed as non-IG. Firms that expect the floor to
bind should compare the portfolio-weighted 100% against the portfolio-weighted
`w_IG × 65% + w_nonIG × 135%` before making the election.

!!! note "Implementation status"
    The calculator does not expose a separate Art. 122(8) switch. Because the
    engine derives S-TREA by running the SA calculator over the IRB population and
    honouring the firm's Art. 122(5)/(6) branch choice, firms naturally get branch
    (b) treatment in S-TREA if they are already applying the IG/non-IG split to
    their regular SA exposures, and branch (a) otherwise. A firm that wants to
    adopt branch (b) **only** for S-TREA (i.e., continue to use 100% for its
    regular SA unrated corporates while using 65%/135% for the floor) would
    currently need to configure two runs and combine them externally — the
    Art. 122(8) drafting does not require this split but does not prohibit it.
    See the [output floor spec](output-floor.md#unrated-corporate-election-art-1228)
    for the S-TREA linkage and notification governance note.

### Rated Corporate Due Diligence CQS Step-Up (Art. 122(4))

Basel 3.1 introduces a class-specific CQS step-up rule for **rated** corporate exposures
that sits alongside the [framework-wide Art. 110A due diligence obligation](#due-diligence-obligation-art-110a)
discussed earlier in this specification.

!!! quote "Art. 122(4) — verbatim (PRA PS1/26 p. 44)"
    "Where a credit assessment by a nominated ECAI is available, an institution shall
    conduct due diligence to ensure that the external credit assessment appropriately and
    prudently reflects the risk of the exposure. If the due diligence analysis reflects
    higher risk characteristics than that implied by the credit quality step of the
    exposure, the institution shall assign a risk weight associated with a credit quality
    step that is at least one step higher than the risk weight determined by the external
    credit assessment."

**Trigger.** Applies whenever a rated corporate exposure uses Art. 122(1) Table 6 (or the
short-term Art. 122(3) Table 6A once implemented — see [D3.8](#short-term-corporate-ecai-art-1223-table-6a))
for its risk weight and the firm's internal due diligence reveals risk characteristics
higher than the ECAI-implied credit quality step.

**Effect.** The firm must assign the risk weight of the **next CQS step higher**. Worked
examples against Table 6:

| ECAI CQS | ECAI RW | Step-up CQS | Step-up RW | Uplift |
|----------|---------|-------------|------------|--------|
| CQS 1 | 20% | CQS 2 | 50% | +30 pp |
| CQS 2 | 50% | CQS 3 | 75% | +25 pp |
| CQS 3 | 75% | CQS 4 | 100% | +25 pp |
| CQS 4 | 100% | CQS 5 | 150% | +50 pp |
| CQS 5 | 150% | CQS 6 | 150% | 0 (already at cap) |
| CQS 6 | 150% | — | 150% | 0 (already at cap) |

Art. 122(4) is **not** a discretionary floor — it is a mandatory override where the DD
finding is triggered.

**Distinction from Art. 110A.** Art. 122(4) is a narrower, rated-exposure-only rule with a
fixed one-step uplift; Art. 110A applies to every non-exempt SA exposure (rated or unrated)
and permits an unbounded uplift. The two rules can interact: a firm's DD finding may be
satisfied either by a one-step CQS uplift under Art. 122(4) or by a larger uplift channelled
through the Art. 110A `due_diligence_override_rw` path. Where both would apply, the final RW
is `max(RW_Art_122_4, RW_Art_110A_override, RW_ECAI)`.

**Distinction from the unrated corporate IG/non-IG split.** Art. 122(4) applies to **rated**
corporates only. The Art. 122(6)(a)/(b) 65%/135% IG split applies only to **unrated**
corporates and requires separate PRA permission. A rated corporate whose DD reveals
higher-than-implied risk is stepped up one CQS band under Art. 122(4); it does not drop into
the unrated sub-category table.

**Parallel provisions.** Art. 122(4) is textually near-identical to two other class-specific
step-up rules in PS1/26:

| Provision | Obligor class | RW reference |
|-----------|---------------|--------------|
| Art. 120(4) | Rated institutions | Art. 120(1) Table 3 |
| **Art. 122(4)** | **Rated corporates** | **Art. 122(1) Table 6** |
| Art. 129(4A) | Covered bonds | Art. 129(4) Table 7 / Art. 129(5) unrated derivation |

All three share the same trigger ("DD reveals higher risk than implied by the CQS") and the
same consequence ("at least one CQS step higher"). CRR has no equivalent provision for any
of the three classes — the rules are Basel 3.1-only.

**Implementation status.** The calculator does not yet implement a dedicated Art. 122(4)
branch. Firms currently carry Art. 122(4) findings through the Art. 110A pathway: set
`due_diligence_override_rw` on the facility to the next-CQS-band weight, and the SA
calculator will apply it as a directional floor (see [Implementation](#implementation)
above). This is functionally equivalent and captured in the output via the
`due_diligence_override_applied` audit column.

!!! warning "Firm responsibility — not an engine determination"
    The engine does not evaluate whether a DD finding is material enough to trigger
    Art. 122(4). The firm determines when the step-up applies; the calculator only
    applies the resulting RW as a floor. Evidence that the step-up has been considered
    should be traceable to the firm's DD process documentation.

### Short-Term Corporate ECAI (Art. 122(3), Table 6A)

New in Basel 3.1 — for exposures with a specific short-term ECAI assessment:

| Short-Term CQS | Risk Weight |
|----------------|-------------|
| CQS 1 | 20% |
| CQS 2 | 50% |
| CQS 3 | 100% |
| Others | 150% |

CRR has no equivalent short-term corporate ECAI table — all corporate exposures use the
long-term CQS mapping (Art. 122(1), Table 6) regardless of assessment tenor. The Table 6A
structure mirrors institution short-term ECRA (Art. 120(2), Table 4) with the same weight
progression.

!!! warning "Not Yet Implemented — Schema Gap"
    Short-term corporate ECAI (Art. 122(3), Table 6A) is not yet implemented. No
    `has_short_term_ecai` schema field exists for corporate exposures (same gap as
    institution Table 4A — see D3.8). The calculator falls back to long-term Table 6 for
    all corporate exposures. No `B31_CORPORATE_SHORT_TERM_RISK_WEIGHTS` constant exists
    in the codebase.

---

## Retail Risk Weights (Art. 123)

| Category | Risk Weight | Reference |
|----------|-------------|-----------|
| Regulatory retail (non-transactor) | **75%** | Art. 123(3)(b) |
| QRRE transactors | **45%** | Art. 123(3)(a) |
| Payroll / pension loans | **35%** | Art. 123(4) |
| Non-regulatory retail | **100%** | Art. 123(3)(c) |

!!! info "CRR2 Continuity"
    The 35% payroll/pension treatment is **not new** in Basel 3.1. It was introduced by CRR2
    (Regulation (EU) 2019/876) in CRR Art. 123 second subparagraph and carried forward unchanged
    to PRA PS1/26 Art. 123(4). The four qualifying conditions (unconditional salary/pension
    deduction, insurance, payments ≤ 20% of net income, maturity ≤ 10 years) are identical.

The retail threshold is changed from EUR 1m to **GBP 880,000** under PRA PS1/26 Art. 123(1)(b)(ii).

### Transactor Exposure Eligibility (Art. 123(3)(a), PRA Glossary)

The 45% preferential risk weight for regulatory retail exposures under Art. 123(3)(a) is gated
by the **"transactor exposure"** definition in the PRA Glossary (p. 9 of PRA PS1/26 Appendix 1).
An exposure qualifies as a transactor only if it meets one of two behavioural tests over the
**previous 12-month period**:

| Limb | Facility Type | Eligibility Test |
|------|---------------|------------------|
| (1) | Revolving facility (credit cards, charge cards, similar) where the balance due at each scheduled repayment date is determined as the amount drawn at a pre-defined reference date | Obligor has **repaid the balance in full at each scheduled repayment date for the previous 12-month period** (both conditions cumulative) |
| (2) | Overdraft facility | Obligor **has not drawn down over the previous 12-month period** |

Qualifying revolving retail exposures that do not satisfy either limb are classified as
**non-transactor** exposures and receive the 75% weight under Art. 123(3)(b). There is no
partial or pro-rata treatment — the test is binary on the full 12-month window.

!!! warning "12-Month History Requirement — Upstream Assessment Responsibility"
    The 12-month full-repayment (or zero-drawdown) assessment is the **reporting institution's
    responsibility**. The calculator accepts `is_qrre_transactor` as a binary input flag and
    applies the 45% weight when the flag is True — it does **not** validate the underlying
    12-month history. Mis-population of the flag (e.g., marking an account as transactor
    without the 12-month repayment history) will silently over-favour the exposure by 30
    percentage points (45% vs 75%).

    Institutions must have documented procedures to evidence that each flagged transactor
    account meets either limb (1) or limb (2) at the reporting reference date.

!!! info "IRB Consistency — Art. 154(4) Default Rule for New Accounts"
    The same "transactor exposure" definition feeds the IRB QRRE PD-floor split (0.05%
    transactor vs 0.10% non-transactor per Art. 163(1)(c)). Art. 154(4) adds an explicit
    default rule for the IRB path: *"qualifying revolving retail exposures with less than
    12 months of repayment history shall be identified as exposures that are non-transactor
    exposures"*. The same principle applies to the SA 45% weight by virtue of the PRA
    Glossary's "previous 12-month period" requirement — newly originated revolving accounts
    cannot qualify as transactors until a full 12-month history has accrued.

!!! info "CRR Comparison — No SA Transactor Concept"
    CRR SA (Art. 123 as it applied before UK revocation) assigns a flat 75% to regulatory
    retail. The 45% transactor sub-category is **new in Basel 3.1**. The transactor concept
    under CRR is only used for the IRB QRRE PD-floor distinction via Art. 154(4) — not for
    any SA risk weight. See the
    [CRR SA Risk Weights spec](../crr/sa-risk-weights.md#retail-exposures-crr-art-123)
    for the CRR retail treatment.

**Implementation fields:** The transactor flag maps to `is_qrre_transactor` in the
[counterparty schema](../../data-model/input-schemas.md#counterparty-schema). The flag is
evaluated in `engine/sa/calculator.py` (B31 branch) for the 45% weight and in
`engine/irb/formulas.py` for the PD-floor split. No 12-month history field exists in the
schema — the input flag is accepted as-is and the upstream assessment is assumed.

### Currency Mismatch Multiplier (Art. 123B)

New in Basel 3.1. For unhedged retail and residential RE exposures where the borrower's income
currency differs from the lending currency:

```
RW_adjusted = min(RW x 1.5, 150%)
```

The 1.5x multiplier is **capped at 150%** — exposures already at or above 150% RW are not
further increased by this multiplier.

Triggered by setting `cp_borrower_income_currency` in the input data to a currency different
from the exposure currency. Output column: `currency_mismatch_multiplier_applied`.

---

## Real Estate — Framework Scope (Art. 124)

Article 124 is the **top-level scoping article** for the real-estate risk-weight framework. It sits above Art. 124A–124L and determines which sub-article each RE exposure is routed through. Per the Note at the end of Art. 124, this provision consolidates Art. 124(1), 125, and 126 of CRR as it applied immediately before revocation by the Treasury — i.e., the CRR residential and commercial RE risk-weight articles are collapsed into a single scoping rule that delegates to the new Art. 124F–124L tables.

**Regulatory Reference:** PRA PS1/26 Art. 124 (ps126app1.pdf pp. 50–51)

!!! quote "Art. 124 — Real Estate Exposures"
    1. An institution shall apply the risk weights set out in Articles 124F to 124I to regulatory real estate exposures.
    2. An institution shall apply the risk weights set out in Article 124J to other real estate exposures.
    3. An institution shall apply the risk weights set out in Article 124K to ADC exposures.
    4. An institution shall split a mixed real estate exposure into a residential real estate exposure and a commercial real estate exposure according to the ratio of the values of the residential real estate and the commercial real estate that the exposure is secured by. An institution shall assign the relevant risk weights set out in Article 124J to each part of the exposure, unless both the residential real estate exposure and the commercial real estate exposure parts of the exposure are regulatory real estate exposures, in which case an institution shall assign the relevant risk weights in Articles 124F to 124I to each part of the exposure.

    *[Note: This Article corresponds to Articles 124(1), 125 and 126 of CRR as it applied immediately before revocation by the Treasury]*

### Routing Decision Tree (Art. 124(1)–(3))

For a **single-property** RE exposure, Art. 124 paragraphs (1)–(3) route to exactly one risk-weight table:

| Exposure type | Routing | Risk-weight articles |
|---------------|---------|----------------------|
| ADC exposure (acquisition / development / construction, Art. 124K definition) | Art. 124(3) | [Art. 124K](#real-estate-adc-exposures-art-124k) — 150% standard, 100% qualifying residential |
| Regulatory RE (passes [Art. 124A six-criterion gate](#real-estate-qualifying-criteria-art-124a)) | Art. 124(1) | Art. 124F–124I (class-specific loan-splitting or income-producing tables) |
| Other RE (fails Art. 124A gate but not ADC) | Art. 124(2) | [Art. 124J](#consequence-of-failing--other-real-estate-art-124j) — 150% income-dependent, counterparty RW otherwise |

The ADC check in Art. 124(3) is evaluated **before** the Art. 124A qualifying-criteria gate — Art. 124A(1) opens "A real estate exposure is a regulatory real estate exposure if it is **not an ADC exposure** and all the following requirements are met". An ADC exposure therefore never enters the Art. 124F–124J channel regardless of the six criteria.

### Mixed Real Estate Split (Art. 124(4))

A **mixed real estate exposure** is a single exposure secured by both residential immovable property and commercial immovable property (e.g., a mixed-use building with shops on the ground floor and flats above, or a cross-collateralised facility backed by a mix of RESI and CRE). Art. 124(4) requires the exposure to be split into two notional components:

```
V_RESI = value of residential property securing the exposure
V_CRE  = value of commercial  property securing the exposure
V_total = V_RESI + V_CRE

RESI_share = V_RESI / V_total
CRE_share  = V_CRE  / V_total

EAD_RESI = EAD × RESI_share
EAD_CRE  = EAD × CRE_share
```

Each component is then risk-weighted independently using the **regulatory RE qualifying gate applied to that component's property**:

| Qualifying status of each part | Risk-weight article applied to RESI part | Risk-weight article applied to CRE part |
|--------------------------------|------------------------------------------|-----------------------------------------|
| **Both** parts regulatory RE (each meets Art. 124A against its own property) | Art. 124F or 124G (residential) | Art. 124H or 124I (commercial) |
| Either part fails Art. 124A | Art. 124J (residential) | Art. 124J (commercial) |

!!! warning "Default is the punitive branch"
    Art. 124(4) makes **Art. 124J the default** for mixed RE exposures — the preferential Art. 124F–124I tables apply **only if both the residential and the commercial part separately qualify** under Art. 124A. If either part fails any of the six Art. 124A(1) criteria (e.g., commercial part materially depends on borrower performance, or residential part's charge is unenforceable), **both parts** drop to Art. 124J. There is no partial preference where one qualifying part uses 124F–124I while the non-qualifying part uses 124J — the regulation is written as an all-or-nothing gate for the aggregate exposure.

### Worked Example — Mixed-Use Building

A GBP 2,000,000 loan is secured by a mixed-use property valued at GBP 2,500,000, comprising:

- Ground-floor retail unit: GBP 1,000,000 (commercial, owner-occupied by the obligor's business)
- Two residential flats above: GBP 1,500,000 (residential, let to third-party tenants, not materially dependent on rental cash flows — the obligor services the debt from its retail business income)

Property-value shares: RESI 60%, CRE 40%. Both parts separately qualify under Art. 124A (legal certainty met, valuation to Art. 124D, independent value, insurance). The RESI part is not materially dependent on the property's own cash flows (Art. 124E(1) default) → Art. 124F loan-splitting. The CRE part is not materially dependent (own-use test, Art. 124E(6)) → Art. 124H(1) loan-splitting.

LTV on the combined exposure: 2,000,000 / 2,500,000 = 80%. The LTV is computed at the **aggregate** level per Art. 124C, then the secured-portion split is applied separately on each notional component against its own property value.

| Component | Notional EAD | Property value | LTV on component | Risk-weight path |
|-----------|--------------|----------------|------------------|------------------|
| RESI 60% | 1,200,000 | 1,500,000 | 80% | Art. 124F: 20% on first 55% of 1,500,000 = 825,000; residual 375,000 at counterparty RW |
| CRE 40% | 800,000 | 1,000,000 | 80% | Art. 124H(1): 60% on first 55% of 1,000,000 = 550,000; residual 250,000 at counterparty RW |

If either component instead failed Art. 124A (e.g., the retail unit's income became the primary repayment source, breaching Art. 124A(1)(e) independence), **both** components would drop to Art. 124J and receive 150% (if income-dependent) or the non-income-dependent fallback weights.

### Implementation Status

!!! warning "Mixed RE split not yet implemented — input-schema gap"
    The current input schema exposes a single `property_value` and `property_type` per exposure row, with no mechanism to declare that a single exposure is secured by both residential and commercial property. The B31 SA calculator branch therefore routes each row exclusively through either the residential (Art. 124F–124G) or commercial (Art. 124H–124I) chain based on the single `property_type` flag, and the Art. 124(4) proportional split is **not applied**.

    Firms with genuinely mixed-use collateral must pre-split the exposure into two separate input rows at the loader boundary — one with `property_type = "residential"` and its `property_value` = V_RESI, one with `property_type = "commercial"` and its `property_value` = V_CRE — each with `EAD = total_EAD × (V_part / V_total)` and `is_qualifying_re` reflecting that part's own Art. 124A status. This matches the regulation's outcome but places the split-logic obligation on the firm.

    Code-side gap logged as **D3.59** in `DOCS_IMPLEMENTATION_PLAN.md`: input schema needs `residential_property_value` / `commercial_property_value` fields (or a repeated-collateral structure) and a dedicated `is_mixed_re` path in `engine/sa/namespace.py` to apply Art. 124(4) automatically.

### CRR Comparison

CRR Art. 124 (pre-revocation) was a five-paragraph scoping article delegating to Art. 125 (residential) and Art. 126 (commercial). Neither article had an explicit "mixed RE" paragraph — mixed-use collateral was handled under general SA principles via the residential-vs-commercial classification of the predominant security interest. The Basel 3.1 Art. 124(4) mandatory proportional split is **new regulatory drafting**, although the underlying principle (apportion risk by collateral value) was implicit in prior supervisory practice.

See the [CRR Residential Mortgage spec](../crr/sa-risk-weights.md#residential-mortgage-exposures-crr-art-125) and [CRR Commercial RE spec](../crr/sa-risk-weights.md#commercial-real-estate-crr-art-126) for the legacy treatment.

---

## Real Estate — Qualifying Criteria (Art. 124A)

Basel 3.1 introduces a gating requirement for preferential real estate risk weights. An
exposure is a **regulatory real estate exposure** only if it is NOT an ADC exposure
(Art. 124K) and meets **all six** criteria in Art. 124A(1). Exposures failing any criterion
are "other real estate" under Art. 124J with less favourable treatment.

**Regulatory Reference:** PRA PS1/26 Art. 124A (p.51), Art. 124D (pp.52–53)

### The Six Qualifying Criteria (Art. 124A(1))

| Criterion | Requirement | Detail |
|-----------|-------------|--------|
| **(a)** Property condition | Property is not held for development/construction, OR development is complete, OR it is a self-build exposure | Art. 124A(1)(a)(i)–(iii) |
| **(b)** Legal certainty | Charge is enforceable in all relevant jurisdictions AND institution can likely realise collateral value within a reasonable period following default | Art. 124A(1)(b)(i)–(ii) |
| **(c)** Charge conditions | One of the conditions in Art. 124A(2) is met (see below) | Art. 124A(1)(c) |
| **(d)** Valuation | Property valued per Art. 124D requirements (independent, at or below market value) | Art. 124A(1)(d) |
| **(e)** Borrower independence | Property value does NOT materially depend on borrower performance | Art. 124A(1)(e) |
| **(f)** Insurance monitoring | Institution has procedures to monitor adequate property insurance against damage | Art. 124A(1)(f) |

!!! info "Self-build as the development-phase gate (Art. 124A(1)(a)(iii))"
    Sub-point (iii) is the **only** route by which an exposure secured by land that is held for development and construction can qualify as regulatory RE before the build is complete. Without it, every pre-completion mortgage would fail criterion (a) (because (i) requires property *not* held for development and (ii) requires development *complete*) and would fall to Art. 124J (other RE) — residential at counterparty RW, CRE at max(60%, counterparty RW) — until construction finishes. The self-build carve-out preserves the preferential RE risk weight over the life of the loan in return for the stricter valuation floor in Art. 124D(9)/(10). "Self-build exposure" is a defined term in Art. 1.2 (PS1/26 Appendix 1 p. 27) and is limited to residential exposures of ≤ 4 units for the borrower's primary residence — see the [Self-Build Valuation subsection](#self-build-valuation-art-124d9-and-124d10) below for the definition quote and the Art. 124D(9)/(10) valuation formulas.

### Charge Conditions (Art. 124A(2))

Criterion (c) is satisfied if **any** of the following apply:

| Condition | Requirement |
|-----------|-------------|
| **(a)** First charge | Exposure is secured by a first-ranking charge over the property |
| **(b)** All prior charges held | Institution holds all charges ranking ahead of the exposure's charge |
| **(c)** Junior charge alternative | (i) Charge provides legally enforceable claim constituting effective CRM; (ii) each charge-holder can independently initiate sale; (iii) sale must seek fair market value or best price |

### Valuation Requirements (Art. 124D)

Criterion (d) is satisfied only if the property value has been obtained via an Art. 124D "qualifying valuation". The full valuation standard — monitoring obligation, re-valuation triggers (including the GBP 2.6m / 5% own funds threshold), qualified-valuer and statistical-method conditions, the self-build formula, and the transitional rule for pre-2027 exposures — is documented in its own section below:

→ [Real Estate — Valuation Requirements (Art. 124D)](#real-estate-valuation-requirements-art-124d)

### Consequence of Failing — Other Real Estate (Art. 124J)

Exposures that fail any Art. 124A criterion are "other real estate":

| Sub-Type | Risk Weight | Reference |
|----------|-------------|-----------|
| Income-dependent (any property type) | **150%** | Art. 124J(1) |
| Residential, not income-dependent | Counterparty RW per Art. 124L | Art. 124J(2) |
| Commercial, not income-dependent | max(60%, counterparty RW) | Art. 124J(3) |

!!! warning "Input Field: `is_qualifying_re`"
    The calculator uses a single Boolean field `is_qualifying_re` in the input data.
    When `False`, the exposure is routed to Art. 124J treatment **before** the standard
    RE branches. The six Art. 124A(1) criteria must be pre-evaluated by the reporting
    institution — the calculator does not validate individual criteria. If the field is
    omitted, the exposure defaults to qualifying (`True`) for backward compatibility.

---

## Real Estate — Underwriting Standards (Art. 124B)

Article 124B is a one-paragraph **governance precondition** for originating real estate exposures: institutions must operate an underwriting policy that, at a minimum, requires assessment of the borrower's ability to repay. It sits upstream of the calculator and applies to **all** real estate exposures regardless of whether they subsequently qualify under Art. 124A — the affordability-assessment obligation is triggered at origination, not at risk-weighting.

**Regulatory Reference:** PRA PS1/26 Art. 124B (ps126app1.pdf p. 52). Effective 1 January 2027.

!!! quote "Art. 124B — Underwriting Standards for Real Estate Exposures"
    1. An institution shall have an underwriting policy for originating real estate exposures which shall, at a minimum, require the institution to assess the ability of the borrower to repay.

### Scope and Application

- **All real estate exposures in scope** — regulatory RE (Art. 124F–124I), other RE (Art. 124J), and ADC (Art. 124K). There is no exposure-type carve-out; the obligation attaches at the point an institution **originates** a real estate exposure.
- **Governance-level rule, not per-exposure calculation** — Art. 124B requires the *existence of an underwriting policy*, not a per-exposure affordability calculation surfaced through the risk-weight table. Compliance is evidenced by policy documentation, credit-committee approval records, and PRA supervisory review.
- **"Ability to repay" is the minimum standard** — Art. 124B sets a floor ("at a minimum"). Firms are expected to extend the policy to cover other prudential aspects (collateral adequacy, concentration limits, product-specific affordability tests such as interest-rate stress tests for residential mortgages) per PRA supervisory expectations and CRD Art. 79 credit-risk management obligations.

### Relationship to Other Art. 124-Series Provisions

Art. 124B is distinct from the measurement rules of Art. 124–124L. It is the **origination-side governance** counterpart to the **calculation-side** gates and tables:

| Article | Function | Calculator-visible? |
|---------|----------|---------------------|
| Art. 124 | Framework scope and mixed-RE proportional split | Yes — property-type routing |
| Art. 124A | Six-criterion qualifying gate for preferential risk weights | Yes — `is_qualifying_re` input |
| **Art. 124B** | **Origination governance — underwriting-policy obligation** | **No — firm-side** |
| Art. 124C | Regulatory LTV formula (stacked prior charges) | Yes — `property_ltv`, `prior_charge_ltv` inputs |
| Art. 124D | Valuation standard (qualifying valuation, revaluation triggers, self-build floor) | Indirect — `property_value` must already be Art. 124D-compliant |
| Art. 124E | Material-dependency classification for routing between loan-splitting and income-producing tables | Yes — `is_income_producing` / dependency flags |

A breach of Art. 124B does **not** reclassify an exposure under Art. 124J — the article is a standalone governance requirement enforced supervisorily, not a risk-weight trigger. A firm that continues to apply Art. 124F–124I preferential weights while breaching Art. 124B would face PRA enforcement (potentially a Pillar 2A capital add-on under SS31/15 ICAAP), not an automatic downgrade of the affected exposures' risk weights.

### Relationship to Art. 110A Due Diligence

Art. 124B is narrower than the framework-wide due-diligence obligation in [Art. 110A](#due-diligence-obligation-art-110a):

- **Art. 110A** applies to every SA exposure (subject to five exemptions) and requires institution-wide processes to ensure "an adequate understanding of the risk profile, creditworthiness and characteristics of exposures to individual obligors and at a portfolio level" (Art. 110A(2)).
- **Art. 124B** is specific to real-estate origination and zeros in on a single minimum test: the underwriting policy must require the institution to assess **the borrower's ability to repay**.

The two obligations are cumulative. A compliant firm will satisfy Art. 124B through policy documentation and credit-committee evidence, and satisfy Art. 110A through broader risk-governance and annual review processes covering all SA exposures (including RE).

### Implementation Status

!!! warning "Firm-governance responsibility — no calculator enforcement"
    The RWA calculator does **not** carry an "Art. 124B underwriting policy" input field and does **not** validate whether a real estate exposure was originated under an affordability-tested policy. Compliance is the firm's responsibility and sits outside the calculation pipeline. Analogous to Art. 124D valuation-governance, the calculator consumes the output of the origination process (approved facility, property value, LTV, qualifying-RE flag) as already-compliant.

    Firms integrating the calculator must ensure their origination controls satisfy Art. 124B independently — e.g., through an underwriting-policy document that meets the "assess the ability of the borrower to repay" minimum, maintained and reviewed at a frequency consistent with PRA supervisory expectations (SS20/15 Residential Mortgage Risk Weights, SS11/13 Internal Ratings Based approaches).

### CRR Comparison

CRR had **no equivalent single-article underwriting-standards provision**. Legacy CRR Art. 125 (residential) and Art. 126 (commercial) set the risk-weight mechanics but did not carry an explicit affordability-assessment obligation as part of the onshored risk-weight rulebook — borrower-repayment governance was instead delivered through:

- **CRD Art. 79** — credit-risk management, requiring institutions to have sound credit-granting criteria, including a well-defined target market;
- **PRA SS20/15** — Residential Mortgage Risk Weights, which expects firms to apply robust affordability testing at origination;
- **PRA SS11/13** — Internal Ratings Based approaches, which extends affordability-test expectations to IRB RE portfolios.

Art. 124B brings the BCBS CRE20.81 origination-standards principle ("banks must have underwriting policies … that include the assessment of the borrower's ability to repay") directly into the PRA CRR rulebook, harmonising the minimum requirement across SA and IRB portfolios at the measurement-framework level rather than leaving it to supervisory statements.

---

## Real Estate — Valuation Requirements (Art. 124D)

Article 124D defines the valuation standard that every regulatory real estate exposure must meet to satisfy Art. 124A(1)(d). It is the sole article governing **(i)** what counts as a "qualifying valuation", **(ii)** when a fresh valuation must be obtained, **(iii)** the self-build value floor, and **(iv)** the transitional rule for exposures incurred before 1 January 2027. Art. 124D applies **only** to regulatory RE exposures under the Standardised Approach — other RE (Art. 124J) and ADC (Art. 124K) are not subject to these specific mechanics, although firms typically apply equivalent internal governance.

**Regulatory Reference:** PRA PS1/26 Art. 124D (ps126app1.pdf pp. 52–53). Effective 1 January 2027.

!!! quote "Art. 124D(1) — Scope"
    This Article applies for the purpose of applying the Standardised Approach to regulatory real estate exposures only.

### Valuation Standard (Art. 124D(8))

Every valuation relied on under Art. 124D — initial, revaluation, or self-build land value — must meet all four of the following conditions simultaneously. Failing any one disqualifies the valuation from being a "qualifying valuation":

| Art. 124D(8) condition | Requirement |
|------------------------|-------------|
| **(a)** Source | Produced either by a **suitably robust statistical method**, or by an **independent valuer** who possesses the necessary qualifications, ability, and experience. |
| **(b)** No speculative uplift | **Excludes expectations on price increases.** The valuer cannot embed assumed appreciation into the present value. |
| **(c)** Market-value cap | Where a market value can be determined, the valuation **shall not exceed market value**. |
| **(d)** Purchase-price cap | Where the mortgage loan is financing the **purchase** of the property, the valuation **shall not exceed the effective purchase price**. |

Paragraphs (a)–(d) apply jointly to paragraph 3 (qualifying valuation), paragraphs 5–7 (revaluation), and paragraphs 9–11 (self-build and transitional). Conditions (c) and (d) together prevent a valuer from substituting a higher market estimate for a recent arm's-length purchase price, or from using a distressed purchase price to uplift an otherwise weaker market value — in each case the **lower** number governs.

!!! info "Statistical method as alternative to an independent valuer (Art. 124D(8)(a))"
    Art. 124D(8) expresses the statistical-method route as a peer of the independent-valuer route — both are valid sources. PRA expectations for what makes a statistical method "suitably robust" (coverage, backtesting, transparency, challenge process) are not enumerated inside Art. 124D itself and are typically sourced from supervisory guidance and SS / firm model-governance policies. A statistical valuation still must meet conditions (b)–(d) of Art. 124D(8).

### Monitoring Obligation (Art. 124D(2))

!!! quote "Art. 124D(2)"
    An institution shall monitor the market value of the property on a frequent basis. It shall carry out more frequent monitoring where the market is subject to significant changes in conditions.

Paragraph (2) imposes a **continuous, framework-wide** monitoring obligation distinct from the event-driven revaluation triggers in paragraph (5). The obligation sits upstream of the calculator: firms are expected to have a market-monitoring process (e.g., index-based tracking, portfolio-level price-series review) that can detect the >10% decline referred to in Art. 124D(5)(b) *without waiting for a revaluation event*. Frequency is not fixed in the text — "more frequent" during turbulent markets is a supervisory expectation.

### What Counts as the Value of the Property (Art. 124D(3))

!!! quote "Art. 124D(3)"
    Subject to paragraph 9, the value of the property is equal to the most recent valuation that has been obtained in accordance with paragraphs 4 to 7 and 11 (a **qualifying valuation**).

The "qualifying valuation" is the anchor used by:

- [Art. 124C](#real-estate-ltv-definition-art-124c) LTV denominator for the 55% secured-portion split
- [Art. 124F–124I](#real-estate-residential-art-124f124g) loan-splitting tables
- [Art. 124J](#consequence-of-failing--other-real-estate-art-124j) 60% floor on commercial non-income-dependent other RE

The "subject to paragraph 9" carve-out defers to the self-build formula ([see below](#self-build-valuation-art-124d9-and-124d10)) for exposures financing land-plus-construction before completion.

### Revaluation Triggers (Art. 124D(4)–(7))

#### When a new valuation is **required** (Art. 124D(4)–(5))

An institution **shall** obtain a fresh qualifying valuation in any of the following situations:

| Trigger | Article | Condition |
|---------|---------|-----------|
| **Origination** | Art. 124D(4) | Institution issues a new loan for the purchase of the property, OR otherwise issues a new loan secured on the property (including replacing an existing loan of an existing or new obligor). |
| **Event-driven impairment** | Art. 124D(5)(a) | An event occurs that results in a **likely permanent reduction** in the property's value → obtain an updated valuation confirming the decrease. |
| **Market-driven decline >10%** | Art. 124D(5)(b) | Institution estimates that the property value has decreased by more than **10%** relative to the last qualifying valuation as a result of a broader decrease in market prices → obtain an updated valuation confirming the decrease. |
| **Staleness — large exposures** | Art. 124D(5)(c) | Loan amount exceeds **GBP 2,600,000 or 5% of the institution's own funds**, whichever is higher, AND **three years** have passed since the last qualifying valuation. |
| **Staleness — all exposures** | Art. 124D(5)(d) | **Five years** have passed since the last qualifying valuation, regardless of loan size. |

!!! warning "Large-exposure threshold applies to regulatory RE in general, not only CRE"
    Art. 124D(5)(c) uses the wording "where the amount of the loan is more than GBP 2,600,000 or 5% of the own funds of the institution" without restricting the rule to commercial RE. The 3-year revaluation cycle therefore applies to **any** regulatory RE exposure exceeding the threshold — residential, commercial, owner-occupied, income-producing, and self-build alike. The smaller-exposure population (loans ≤ GBP 2.6m and ≤ 5% of own funds) is subject only to the 5-year staleness trigger in paragraph (5)(d).

!!! info "CRR comparison — no explicit revaluation cadence"
    Legacy CRR Art. 208(3) required firms to monitor property values "frequently and at least once every year for commercial immovable property and once every three years for residential immovable property", with statistical methods permitted for surveillance. Art. 124D inverts the cadence: residential and commercial are treated the same under Art. 124D(5), and the **origination** + **event** + **market-decline** legs did not appear with this specificity in the CRR text. Firms migrating from CRR governance should not rely on the 1-year / 3-year split carrying forward.

#### When a new valuation is **permitted but not required** (Art. 124D(6))

!!! quote "Art. 124D(6)"
    If modifications are made to the property that unequivocally increase its value, the institution may obtain an updated valuation to confirm the increase in value.

Paragraph (6) is an optional uplift channel — firms **may** (not shall) revalue upwards when physical property modifications (extension, refurbishment, change of use with planning consent) unequivocally raise market value. The conservative default is to retain the pre-modification qualifying valuation until the next trigger in (5) fires. If the firm exercises the (6) option, the new valuation must still meet Art. 124D(8)(a)–(d).

#### Clock-reset rule after a (5)(b) market-decline revaluation (Art. 124D(7))

!!! quote "Art. 124D(7)"
    If an institution has revalued the property in accordance with point (b) of paragraph 5, it may use the date of that valuation, or the date of the previous qualifying valuation that was not obtained in accordance with point (b) of paragraph 5, to calculate whether it has to obtain an updated valuation in accordance with points (c) or (d) of paragraph 5.

Paragraph (7) gives institutions optionality when the 3-year (c) or 5-year (d) clock would be reset by a market-decline revaluation under (5)(b). Without this relief, a firm that revalues a property downwards in response to a market shock would be forced to re-value *again* three or five years after the reactive date, potentially during another stressed period. Paragraph (7) allows the clock to continue running from the last **routine** (non-5(b)) qualifying valuation — a firm can elect whichever date yields the more prudent schedule. The choice is **per-exposure**, not portfolio-wide, and once the (c) or (d) trigger fires the new valuation becomes the anchor for all subsequent paragraph-5 calculations.

### Self-Build Valuation (Art. 124D(9) and 124D(10))

!!! quote "Art. 1.2 — Self-build exposure (PS1/26 Appendix 1 p. 27)"
    **self-build exposure** means a residential real estate exposure secured by property or land that has been acquired or held for development and construction purposes and that meets the following criteria:

    (1) the property does not, or will not, have more than four residential housing units; and

    (2) the property will be the borrower's primary residence.

Three elements of the definition matter for scope: (a) **residential only** — a mixed-use or purely commercial development cannot be a self-build exposure, so the Art. 124D(9)/(10) land-value floor is unavailable to CRE; (b) **≤ 4 housing units** — larger residential schemes fall back to the general Art. 124D(3) qualifying-valuation rule without the 0.8 self-build discount; and (c) **primary residence** — buy-to-let self-builds, second-homes, and developer-for-sale exposures are excluded. A self-build exposure is the sole category under Art. 124A(1)(a)(iii) that lets an exposure secured by land *held for development and construction* qualify as regulatory RE **before** construction is complete — the other two gates in Art. 124A(1)(a)(i)/(ii) both require finished property. The valuation anchor under Art. 124D(9)/(10) departs from the pure qualifying-valuation rule because there may be no finished building to value at origination.

!!! quote "Art. 124D(9) — Self-build at origination (or between revaluations)"
    Where an exposure is a self-build exposure, the value of the property shall, subject to paragraph 10, be the higher of:

    (a) the underlying land value obtained by the institution when the institution issued a new mortgage loan for the purchase of the property **before construction began**; and

    (b) the most recent qualifying valuation of the property multiplied by **0.8**.

!!! quote "Art. 124D(10) — Self-build after an Art. 124D(5)(a)/(b) revaluation"
    Where an institution is required to obtain an updated valuation for a self-build exposure in accordance with points (a) or (b) of paragraph 5, the value of the property shall be:

    (a) where an updated estimate of the underlying land value is **not available**, the updated property valuation multiplied by **0.8**; or

    (b) where an updated estimate of the underlying land value **is available**, the higher of:

    &nbsp;&nbsp;&nbsp;&nbsp;(i) the updated property valuation multiplied by **0.8**; and

    &nbsp;&nbsp;&nbsp;&nbsp;(ii) the updated estimate of the underlying land value.

| Lifecycle stage | Property value = | Floor mechanism |
|-----------------|------------------|-----------------|
| Origination (Art. 124D(9)) | max( land_value_at_origination , 0.8 × latest_qualifying_valuation ) | Pre-construction land anchor prevents over-reliance on projected build value |
| After (5)(a)/(b) revaluation, no new land estimate (Art. 124D(10)(a)) | 0.8 × updated_property_valuation | Haircut-only — institution has no fresh land comparable |
| After (5)(a)/(b) revaluation, with updated land estimate (Art. 124D(10)(b)) | max( 0.8 × updated_property_valuation , updated_land_value ) | Both anchors refreshed; floor remains the higher of the two |

The **0.8 multiplier** is the key prudential brake: it guarantees that at least a 20% value buffer is held over the current "completed" valuation until the loan matures or the property is sold, reflecting the residual construction / permitting / market-absorption risk that remains even after the build is complete.

!!! warning "No analogous CRR provision"
    CRR Art. 125/126 did not contain a self-build valuation formula. Self-build exposures under CRR were valued using the general "prudently conservative mortgage lending value" standard inherited from Art. 229. Art. 124D(9)–(10) is new regulatory drafting and effective from 1 January 2027.

### Transitional Rule — Pre-2027 Exposures (Art. 124D(11))

!!! quote "Art. 124D(11)"
    For the purposes of paragraph 3 in relation to exposures incurred before 1 January 2027:

    (a) paragraph 4 shall be read as if it was in force from the time the exposure was incurred;

    (b) where one or more of the following circumstances applies:

    &nbsp;&nbsp;&nbsp;&nbsp;(i) it is not reasonably practicable for the institution to identify a valuation obtained in accordance with paragraph 4;

    &nbsp;&nbsp;&nbsp;&nbsp;(ii) the amount of the loan is more than GBP 2,600,000 or 5% of the own funds of the institution, and three years have passed since a valuation was obtained in accordance with paragraph 4; or

    &nbsp;&nbsp;&nbsp;&nbsp;(iii) five years have passed since a valuation was obtained in accordance with paragraph 4,

    the most recent valuation obtained by the institution before 1 January 2027 shall be a qualifying valuation.

| Circumstance for pre-2027 exposures | Qualifying valuation = |
|-------------------------------------|------------------------|
| Art. 124D(11)(b)(i) — Paragraph-4 valuation is **not reasonably practicable to identify** | Most recent pre-2027 valuation held by the institution. |
| Art. 124D(11)(b)(ii) — Loan > GBP 2.6m (or 5% own funds) **and** 3 years since any paragraph-4 valuation | Most recent pre-2027 valuation held by the institution. |
| Art. 124D(11)(b)(iii) — 5 years since any paragraph-4 valuation | Most recent pre-2027 valuation held by the institution. |
| Otherwise | Paragraph-4 valuation deemed to apply from the date the exposure was incurred (Art. 124D(11)(a)). |

Paragraph (11) is the **grandfathering bridge** for legacy portfolios. Without it, every pre-2027 real-estate exposure would lack a "paragraph-4 valuation" on day one of the new regime and would be forced to Art. 124J (other RE) until the institution obtained a fresh valuation. Instead, Art. 124D(11)(a) deems the old valuation to have been obtained under paragraph 4 retrospectively, and (11)(b) provides three escape hatches where the institution can substitute the most recent pre-2027 valuation outright. Once the 3-year (c) / 5-year (d) clocks in paragraph (5) tick over *after* 1 January 2027, the transitional relief lapses and the firm must revalue to the forward-looking Art. 124D standard.

!!! info "Interaction with the Art. 124D(8) quality conditions"
    Art. 124D(11) deems a pre-2027 valuation to be a *qualifying* valuation, but the quality conditions in Art. 124D(8)(a)–(d) apply to any valuation that the firm relies on. Where a pre-2027 valuation was obviously substandard (e.g., a drive-by indexation with no valuer sign-off, or a purchase price exceeded by an origination valuation), firms should expect supervisory challenge under Art. 124D(8) even though paragraph (11) ostensibly accepts the valuation on date-basis grounds.

### Implementation Status

!!! warning "Revaluation triggers and self-build formula are firm-side governance, not calculator logic"
    The RWA calculator consumes a single property value per RE exposure (input field `re_split_property_value`, or legacy `property_value`) and applies it as the Art. 124C LTV denominator. **No field in the current input schema distinguishes** between:

    - Origination valuation vs. most recent revaluation
    - Independent-valuer vs. statistical-method source
    - Self-build vs. finished-property valuation
    - Pre-2027 (transitional) vs. post-2027 (paragraph-4) valuations

    The firm's valuation-governance process is expected to ensure that the `property_value` supplied to the calculator **is** the Art. 124D-compliant qualifying valuation (including: the 0.8 self-build haircut applied upstream, the revaluation cadence respected, and the pre-2027 grandfathering applied where relevant). The calculator does not validate Art. 124D compliance — it treats the supplied value as already qualifying.

    Firms failing any Art. 124D paragraph should either (a) set `is_qualifying_re = False` to route the exposure to Art. 124J, or (b) use the most recent defensible valuation floored by the Art. 124D(9)/(10) self-build formula where applicable. No dedicated input flag captures "Art. 124D non-compliance" directly.

### CRR Comparison

Legacy CRR had no single "Art. 124D". Valuation obligations were spread across:

- **Art. 208(3) CRR** — annual (CRE) / 3-year (RRE) monitoring cadence and statistical-method permission
- **Art. 229 CRR** — "prudently conservative mortgage lending value" definition (commercial valuers)
- **Art. 125(2)(a) CRR / Art. 126(2)(a) CRR** — origination valuation requirement embedded inside the residential / commercial RE criteria

The Basel 3.1 consolidation under Art. 124D: (a) aligns residential and commercial revaluation cadence, (b) introduces the explicit **GBP 2.6m / 5% own funds** large-exposure trigger (no CRR analogue), (c) introduces the explicit **>10% market-decline** trigger with a clock-reset option (Art. 124D(7)), (d) codifies the self-build valuation floor, and (e) provides express grandfathering via Art. 124D(11). The 5-year ceiling (Art. 124D(5)(d)) is **tighter** than legacy CRR's 3-year residential cadence for the subset of exposures below the large-exposure threshold — but **looser** for commercial exposures below that threshold, which under CRR required annual monitoring.

See the [CRR Residential Mortgage spec](../crr/sa-risk-weights.md#residential-mortgage-exposures-crr-art-125) and [CRR Commercial RE spec](../crr/sa-risk-weights.md#commercial-real-estate-crr-art-126) for the pre-revocation treatment.

## Real Estate — ADC Exposures (Art. 124K)

ADC (Acquisition, Development, and Construction) exposures are loans to corporates or SPEs
financing land acquisition for development and construction, or financing development and
construction of residential or commercial real estate. ADC exposures are explicitly excluded
from the regulatory real estate framework (Art. 124A) and receive standalone treatment.

**Regulatory Reference:** PRA PS1/26 Art. 124K (p.58), Glossary definition (p.3)

### Risk Weights

| Scenario | Risk Weight | Conditions | Reference |
|----------|-------------|------------|-----------|
| Standard (non-qualifying) ADC | **150%** | Default for all ADC exposures | Art. 124K(1) |
| Qualifying residential ADC | **100%** | Residential RE only, subject to both conditions below | Art. 124K(2) |

### Qualifying Conditions for 100% (Art. 124K(2))

The reduced 100% risk weight is available **only** for ADC exposures financing land
acquisition for residential RE development/construction, or financing residential RE
development/construction. **Both** of the following must be met:

**(a) Prudent underwriting** (Art. 124K(2)(a)):

- The exposure is subject to prudent underwriting standards, including for the valuation of
  any real estate used as security for the exposure.

**(b) At least one of** (Art. 124K(2)(b)):

| Condition | Requirement |
|-----------|-------------|
| **(b)(i)** Pre-sales/pre-leases | Legally binding pre-sale or pre-lease contracts, where the purchaser/tenant has made a **substantial cash deposit subject to forfeiture** if the contract is terminated, amount to a **significant portion** of total contracts |
| **(b)(ii)** Borrower equity at risk | The borrower has **substantial equity at risk** |

!!! info "Key Restrictions"
    - **Residential only:** The 100% concession is not available for commercial ADC exposures.
      Commercial ADC always receives 150%.
    - **Corporate/SPE obligors:** ADC exposures are defined as loans to corporates or SPEs —
      natural persons cannot have ADC exposures per the PRA glossary definition.
    - **No regulatory RE treatment:** ADC exposures cannot qualify for LTV-based loan-splitting
      (Art. 124F–124H) or income-producing tables (Art. 124I) regardless of collateral quality.

### CRR Comparison

Under current UK CRR (pre-2027), Art. 128 (high-risk items including speculative immovable
property financing) was omitted by SI 2021/1078 effective 1 Jan 2022. Without Art. 128,
ADC-type exposures fall to standard corporate treatment (100% unrated). Basel 3.1 Art. 124K
re-introduces explicit ADC treatment at a higher 150% default, with a 100% concession for
qualifying residential exposures.

See also: [CRR ADC treatment](../crr/sa-risk-weights.md#adc-exposures-art-124k)

### Implementation

The calculator uses two input fields:

| Field | Type | Description |
|-------|------|-------------|
| `is_adc` | Boolean | Flags the exposure as ADC — routes to Art. 124K treatment, bypassing all RE LTV-band logic |
| `is_presold` | Boolean | Flags the ADC exposure as meeting Art. 124K(2) qualifying conditions — reduces RW from 150% to 100% |

**Code:** `b31_adc_rw_expr()` in `data/tables/b31_risk_weights.py` dispatches on `is_presold`.
ADC sits at priority 4 in the Basel 3.1 SA when-chain (`engine/sa/calculator.py`), after
subordinated debt but before all other RE branches — `is_adc=True` overrides any LTV-based
or income-producing treatment.

!!! warning "Qualifying assessment is external"
    The calculator does not validate whether Art. 124K(2) conditions are met. The reporting
    institution must pre-evaluate prudent underwriting standards and pre-sale/equity-at-risk
    thresholds, then set `is_presold = True` accordingly. PRA does not define quantitative
    thresholds for "substantial" or "significant portion" — these are institution-level
    judgements subject to supervisory review.

### Key Scenarios

| ID | Scenario | is_adc | is_presold | Expected RW | Reference |
|----|----------|--------|------------|-------------|-----------|
| B31-A12 | Standard ADC exposure | True | False | 150% | Art. 124K(1) |
| B31-A13 | Qualifying residential ADC (pre-sold) | True | True | 100% | Art. 124K(2) |
| B31-A14 | ADC overrides RE LTV treatment | True | False | 150% | Art. 124K(1) priority |

---

## Real Estate — LTV Definition (Art. 124C)

Art. 124C defines the regulatory loan-to-value ratio used for all LTV-based real estate
risk weights (Art. 124G income-producing residential and Art. 124I income-producing
commercial). This definition also underpins the loan-splitting threshold calculations
in Art. 124F (residential) and Art. 124H (commercial).

**Regulatory Reference:** PRA PS1/26 Art. 124C (p.52)

### LTV Formula (Art. 124C(1))

```
LTV = loan_amount / property_value
```

Where:
- `loan_amount` is defined per Art. 124C(2)–(3)
- `property_value` is determined per Art. 124D (see [Valuation Requirements](#valuation-requirements-art-124d))

### Loan Amount — Numerator (Art. 124C(2))

The loan amount includes:

| Component | Included | Reference |
|-----------|----------|-----------|
| Outstanding loan balance | Yes | Art. 124C(2) |
| Undrawn committed amount of the mortgage loan | Yes | Art. 124C(2) |
| Credit risk adjustments and other own-funds reductions | **No** — excluded | Art. 124C(2) |
| Funded or unfunded credit protection | **No** — excluded | Art. 124C(2) |
| Pledged deposit accounts (on-balance-sheet netting) | **Exception** — may be deducted | Art. 124C(2) |

The single exception to the "no CRM" rule: pledged deposit accounts with the lending
institution that meet **all** requirements for on-balance-sheet netting (Credit Risk
Mitigation Part) AND have been unconditionally and irrevocably pledged for the sole
purpose of loan repayment. These may reduce the loan amount in the LTV numerator.

### Prior Charges Stacking (Art. 124C(3))

!!! warning "Critical Classification Rule"
    The loan amount used in the LTV calculation **must include all other loans** secured
    with charges ranking **ahead of** or **pari passu** with the charge securing the
    current exposure. This is the regulatory basis for `prior_charge_ltv` in the
    calculator's input schema.

**Rules:**

1. **Identify all charges on the property** — any loan secured by a charge that ranks
   in priority ahead of the institution's charge, or ranks pari passu, must be added
   to the numerator.
2. **Insufficient ranking information** — where there is insufficient information to
   determine the ranking of other charges, the institution **must treat** those charges
   as pari passu with its own charge. This is a conservative assumption that increases
   the reported LTV.
3. **Effect on risk weights** — prior charge stacking increases LTV, which:
   - Pushes whole-loan exposures (Art. 124G/124I) into higher risk weight bands
   - Reduces the effective loan-splitting threshold (Art. 124F(2)/124H junior charges)
   - May trigger the 1.25× junior charge multiplier (Art. 124G(2)/124I(3))

**Example:**

```
Property value:             £400,000
Institution's own loan:     £200,000 (outstanding) + £20,000 (undrawn committed)
Senior charge (other lender): £100,000

LTV = (£200,000 + £20,000 + £100,000) / £400,000 = 80%
    (without prior charge stacking: LTV = £220,000 / £400,000 = 55%)
```

### Property Value — Denominator (Art. 124C(4))

The property value is determined in accordance with Art. 124D
([Valuation Requirements](#valuation-requirements-art-124d) above).

### Implementation

The calculator uses two input fields to implement Art. 124C:

| Field | Type | Description | Reference |
|-------|------|-------------|-----------|
| `property_ltv` | Float64 | The fully-stacked LTV ratio incorporating all Art. 124C components (including prior charges per para. 3) | Art. 124C(1)–(4) |
| `prior_charge_ltv` | Float64 | The portion of the LTV attributable to prior/pari passu charges alone — used by Art. 124F(2) and Art. 124G(2) to reduce the loan-splitting threshold and apply the junior charge multiplier | Art. 124C(3), Art. 124F(2) |

The reporting institution is responsible for computing the stacked LTV externally:
the calculator consumes the pre-computed `property_ltv` value and assumes it already
incorporates Art. 124C(2)–(3) components. The separate `prior_charge_ltv` field
enables the calculator to determine the junior charge effect on the loan-splitting
threshold (55% for RRE, 60% for CRE).

!!! info "Relationship between `property_ltv` and `prior_charge_ltv`"
    - `property_ltv` = total regulatory LTV including all prior charges (the single
      number used for risk weight band lookup in Art. 124G/124I tables)
    - `prior_charge_ltv` = the LTV contribution of prior/pari passu charges only (used
      to reduce the secured threshold from 55%/60% under Art. 124F(2)/124H junior charge
      treatment)
    - A first-charge exposure has `prior_charge_ltv = 0.0`
    - An exposure behind a senior lien has `prior_charge_ltv > 0.0`

---

## Real Estate — Material Dependency Classification (Art. 124E)

Art. 124E defines the test that routes residential and commercial real estate exposures
between two treatment tracks:

- **Not materially dependent** on property cash flows → loan-splitting (Art. 124F for
  residential, Art. 124H for commercial)
- **Materially dependent** on property cash flows → whole-loan LTV-band tables
  (Art. 124G Table 6B for residential, Art. 124I for commercial)

This classification is a Basel 3.1 addition with no CRR equivalent. Under CRR, the
loan-splitting / whole-loan distinction was less formally defined and did not include
quantitative thresholds such as the three-property limit.

### Residential RE — Default and Exceptions (Art. 124E(1))

A residential RE exposure is **materially dependent by default**. It is classified as
**not** materially dependent only if it falls into one of five exceptions:

| Exception | Condition | Reference |
|-----------|-----------|-----------|
| **(a) Primary residence** | Exposure to one or more natural persons, secured by a single property that is the obligor's primary residence | Art. 124E(1)(a) |
| **(b) Three-property limit** | Exposure to one or more natural persons that individually meet the three-property limit (para 2) | Art. 124E(1)(b) |
| **(c) SPE with guarantor** | Exposure to an entity created specifically to finance/operate immovable property, where one or more natural persons act as guarantor, receive sole economic benefit, and the entity meets the three-property limit (para 3) | Art. 124E(1)(c) |
| **(d) Social housing** | Exposure to a UK-regulated public housing company or not-for-profit association that exists to serve social purposes and offer tenants long-term housing | Art. 124E(1)(d) |
| **(e) Cooperative/association** | Exposure to an association or cooperative of natural persons that exists solely to grant members use of a primary residence in the securing property | Art. 124E(1)(e) |

!!! info "Three-Property Limit — Natural Persons (Art. 124E(2))"
    A natural person meets the three-property limit if they have **no more than three
    qualifying properties**. A qualifying property is one that:

    1. Is residential real estate
    2. Is **not** the natural person's primary residence
    3. Is security for a residential RE exposure to either:
        - (a) the natural person directly, or
        - (b) an SPE that the natural person guarantees and from which they receive the
          economic benefit

    Properties are counted **across all lenders**, not just the institution assessing the
    exposure.

!!! info "Three-Property Limit — SPE Entities (Art. 124E(3))"
    An SPE entity meets the three-property limit if **all** of the following are satisfied:

    1. The entity has no more than three qualifying residential properties (excluding the
       guarantor's primary residence) securing RE exposures to the entity, across all lenders
    2. The same guarantor(s) stand behind all residential RE exposures to the entity,
       regardless of lender
    3. Each guarantor individually meets the natural person three-property limit (para 2)

!!! warning "Housing Unit Counting (Art. 124E(4))"
    Each separate housing unit counts as an **individual property**, even where multiple
    units are secured by a single charge. A block of four flats under one charge = four
    properties for the three-property count. This is material for multi-unit buy-to-let
    portfolios.

### Reassessment Triggers — Residential RE (Art. 124E(5))

Art. 124E(5) imposes both a **mandatory reassessment trigger** and a **discretionary
update right**, and pairs the update right with an anti-gaming proviso.

!!! quote "Art. 124E(5) (PS1/26 Appendix 1, p. 54–55)"
    An institution **shall reassess** whether a residential real estate exposure meets any
    of the conditions of paragraph 1 when it issues a **new loan secured by residential real
    estate to the obligor (including for the purpose of replacing an existing loan to the
    obligor)**. An institution **may update** its assessment of whether a residential real
    estate exposure meets any of the conditions of paragraph 1 at other times, provided
    **new information is gathered and used in a consistent way across its portfolio and
    updates are not applied selectively in order to reduce own funds requirements**.

| Sentence | Voice | Scope | Effect |
|----------|-------|-------|--------|
| **First (mandatory)** | `shall reassess` | Any new residential-RE-secured loan to the same obligor — including replacement loans | Re-run Art. 124E(1)–(4) classification against the updated obligor-level exposure profile |
| **Second (discretionary + anti-gaming)** | `may update` | Any other time | Permitted only if (i) new information is gathered *and* (ii) applied consistently portfolio-wide; reassessment triggered *selectively* to reduce own-funds requirements is prohibited |

!!! warning "Obligor-level, not property-level"
    The mandatory trigger fires on any new residential-RE-secured loan to the **same
    obligor**, even if the new loan is secured by a different property. A borrower adding
    a second buy-to-let RRE loan at a different address still triggers reassessment of
    every existing RRE exposure to that borrower, because the three-property count in
    Art. 124E(2) is obligor-scoped.

### Commercial RE — Own-Use Test (Art. 124E(6))

A commercial RE exposure is **materially dependent by default**. The sole exception:
each property securing the exposure is **predominantly used by the borrower for its own
business purpose**, where the business purpose does **not** include generating income from
the property via rental agreements.

### Reassessment Trigger — Commercial RE (Art. 124E(7))

!!! quote "Art. 124E(7) (PS1/26 Appendix 1, p. 55)"
    An institution **shall reassess at least annually** whether the commercial real estate
    exposure is materially dependent on the cash-flows generated by the property.

Unlike residential RE where the mandatory trigger is event-driven (new loan to obligor),
commercial RE reassessment is **time-driven** with a minimum 12-month cadence. The
own-use determination under Art. 124E(6) can shift as tenancy structures, lease
agreements, or borrower business models change; annual reassessment ensures a commercial
RE exposure routed to Art. 124H (loan-splitting) does not silently stay there after the
own-use premise no longer holds.

!!! info "Reassessment cadence contrast"
    - **Residential RE (Art. 124E(5))** — mandatory on new loan to obligor; optional at other times subject to anti-gaming proviso.
    - **Commercial RE (Art. 124E(7))** — mandatory at least annually; no anti-gaming proviso (the annual minimum already prevents selective timing).

### Implementation

The material dependency classification is an **input-driven flag** — the engine does not
evaluate Art. 124E conditions internally. Institutions must determine material dependency
upstream and supply it via the `is_income_producing` field on the collateral record.

| Input Field | Maps To | Values |
|-------------|---------|--------|
| `is_income_producing` | Art. 124E material dependency | `True` = materially dependent (whole-loan Art. 124G/124I); `False` = not materially dependent (loan-splitting Art. 124F/124H); `null` = defaults to `False` |

The field flows through the pipeline as `has_income_cover` (renamed during collateral
join) and determines the risk weight calculation path:

- `False` → Art. 124F loan-splitting (residential) or Art. 124H loan-splitting (commercial)
- `True` → Art. 124G Table 6B whole-loan (residential) or Art. 124I whole-loan (commercial)

!!! warning "Data Quality Responsibility"
    The three-property limit, SPE guarantor conditions, social housing status, and
    own-business-use test are **not validated** by the calculator. Incorrect classification
    routes exposures to the wrong risk weight track. Institutions must implement Art. 124E
    assessment procedures upstream of the calculator input.

---

## Real Estate — Residential (Art. 124F–124G)

All residential RE risk weights below require the exposure to meet the
[Art. 124A qualifying criteria](#real-estate-qualifying-criteria-art-124a).

### General Residential — Loan-Splitting (Art. 124F)

Not [materially dependent](#real-estate-material-dependency-classification-art-124e)
on cash flows. The exposure is split into a secured portion
(up to 55% of property value) and a residual portion:

| Portion | Risk Weight | Reference |
|---------|-------------|-----------|
| Secured (up to 55% of property value) | **20%** | Art. 124F(1) |
| Residual (above 55% of property value) | Counterparty RW | Art. 124L |

```
secured_share = min(1.0, 0.55 / LTV)
RW = 0.20 × secured_share + counterparty_RW × (1.0 - secured_share)
```

**Counterparty risk weight** (Art. 124L):

| Counterparty Type | RW |
|-------------------|----|
| Natural person (non-SME) | 75% |
| Retail-qualifying SME | 75% |
| Other SME (unrated) | 85% |
| Social housing / cooperative | max(75%, unsecured RW) |
| Other | Unsecured counterparty RW |

**Junior charges** (Art. 124F(2)): If a prior or pari passu charge exists that the
institution does not hold, the 55% threshold is reduced by the amount of the prior
charge. This decreases the secured portion, increasing the blended risk weight.

### Income-Producing Residential — Whole-Loan (Art. 124G, Table 6B)

[Materially dependent](#real-estate-material-dependency-classification-art-124e)
on cash flows (e.g., buy-to-let, multi-unit rental). Whole-loan approach — single
risk weight on entire exposure:

| LTV Band | Risk Weight |
|----------|-------------|
| ≤ 50% | 30% |
| 50–60% | 35% |
| 60–70% | 40% |
| 70–80% | 50% |
| 80–90% | 60% |
| 90–100% | 75% |
| > 100% | 105% |

**Junior charge multiplier** (Art. 124G(2)): Where prior-ranking charges exist that the
institution does not hold, the whole-loan risk weight is multiplied by **1.25×** for
LTV > 50%. The multiplied risk weight is **not capped** at the table maximum (105%) —
it may exceed the highest table band (e.g., 105% x 1.25 = 131.25%).

---

## Real Estate — Commercial (Art. 124H–124I)

All commercial RE risk weights below require the exposure to meet the
[Art. 124A qualifying criteria](#real-estate-qualifying-criteria-art-124a).

### CRE Loan-Splitting (Art. 124H(1))

Not [materially dependent](#real-estate-material-dependency-classification-art-124e)
on cash flows — the borrower uses the property predominantly for its own business
purpose (Art. 124E(6)).

| Portion | Risk Weight | Reference |
|---------|-------------|-----------|
| Secured (up to **55%** of property value) | **60%** | Art. 124H(1)(a) |
| Unsecured (above 55%) | Counterparty RW per Art. 124L | Art. 124H(1)(b) |

!!! warning "LTV threshold is 55%, not 60%"
    The loan-splitting threshold under PRA PS1/26 Art. 124H(1)(a) is **55%** of the
    value of the property (verified against ps126app1.pdf p.56, 17 Apr 2026). The 60%
    figure is the **risk weight** applied to the secured portion, not the LTV band.
    Junior charge adjustments in Art. 124H(2) also reduce the **55%** threshold by
    the amount of the prior charge.

### CRE Income-Producing (Art. 124I)

[Materially dependent](#real-estate-material-dependency-classification-art-124e)
on cash flows — income from the property (rental, sale proceeds) is the primary
repayment source:

**PRA Art. 124I — 2-Band Table**

| LTV | Risk Weight |
|-----|-------------|
| ≤ 80% | **100%** |
| > 80% | **110%** |

!!! warning "PRA Deviation from BCBS"
    BCBS CRE20.86 uses a 3-band table (≤60%: 70%, >60–80%: 90%, >80%: 110%).
    The PRA simplifies to 2 bands with higher weights for the lower LTV tiers.

### Junior Charge Treatment for Income-Producing CRE (Art. 124I(3))

Where there are prior-ranking charges not held by the institution, the whole-loan
risk weight is replaced by a band-dependent **absolute** weight (not a multiplier
on Art. 124I(1)/(2)):

| LTV Band | Risk Weight (Art. 124I(3)) |
|----------|----------------------------|
| ≤ 60% | **100%** (Art. 124I(3)(a)) |
| > 60% and ≤ 80% | **125%** (Art. 124I(3)(b)) |
| > 80% | **137.5%** (Art. 124I(3)(c)) |

Verified against PRA PS1/26 Art. 124I(3), ps126app1.pdf p.57 (17 Apr 2026).

### Large Corporate CRE (Art. 124H(3))

For non-natural-person, non-SME borrowers with non-cash-flow-dependent CRE:

```
RW = max(60%, min(counterparty_rw, income_producing_rw))
```

This is a distinct third path alongside loan-splitting and income-producing tables.

---

## SA Specialised Lending (Art. 122A–122B)

New exposure class in Basel 3.1. Art. 122A(1) defines a specialised lending exposure as a
corporate exposure that is **not** a real estate exposure and that has the structural
characteristics of project finance, object finance, or commodities finance (so income-producing
real estate is excluded — it is routed via Art. 124H–124I instead). Art. 122A(2) classifies
SA SL into the three sub-types; Art. 122B sets the risk weights.

### Rated SA SL (Art. 122B(1))

> *"Where a relevant issue-specific credit assessment by a nominated ECAI is available for a
> specialised lending exposure, an institution shall apply the risk weight treatment set out
> in Article 122(2)."*

Rated SA SL exposures fall through to the **rated corporate ECAI table** in Art. 122(2). The
type-specific weights below apply only when no eligible issue-specific assessment exists.

### Unrated SA SL Risk Weights (Art. 122B(2))

| SL Type | Risk Weight | Reference |
|---------|-------------|-----------|
| Object finance | **100%** | Art. 122B(2)(a) |
| Commodities finance | **100%** | Art. 122B(2)(b) |
| Project finance (pre-operational) | **130%** | Art. 122B(2)(c) |
| Project finance (operational) | **100%** | Art. 122B(2)(c) |
| Project finance (high-quality operational) | **80%** | Art. 122B(4) |
| IPRE (income-producing real estate) | Follows Art. 124H–124I | Art. 122A(1) (excluded) |

### Operational Phase Definition (Art. 122B(3))

For the purpose of Art. 122B(2)(c) and Art. 122B(4), a project is in the **operational phase**
when the entity created to finance the project has both:

- **(a)** a positive net cash-flow that is sufficient to cover any remaining contractual
  obligations relating to the completion of the project; and
- **(b)** declining long-term debt.

Both limbs are mandatory. Pre-operational PF — including the construction phase and any
period before declining long-term debt is established — receives the 130% weight under Art.
122B(2)(c).

### High-Quality Operational PF — 80% Weight (Art. 122B(4))

> *"Where a project finance exposure is in the operational phase and is considered high
> quality in accordance with the criteria in paragraph 5, an institution shall assign a risk
> weight of 80%."*

The 80% preferential weight is conditional on **both** (i) being in the operational phase per
Art. 122B(3), and (ii) satisfying every condition in Art. 122B(5). Failure of any single
condition disqualifies the exposure and reverts it to the 100% operational PF weight under
Art. 122B(2)(c).

### High-Quality PF Criteria (Art. 122B(5))

A project finance exposure is high quality only if the chapeau condition (a) **and** all
eight sub-conditions in (b)(i)–(viii) are met:

#### Art. 122B(5)(a) — Chapeau (Resilience)

> *"It is an exposure to an entity that is able to meet its financial commitments in a timely
> manner and its ability to do so is robust against adverse changes in the economic cycle and
> business conditions."*

This is a forward-looking assessment of the project entity's resilience under stress, not a
historical performance test. The PRA does not prescribe quantitative thresholds; the assessment
must be performed by the institution and documented.

#### Art. 122B(5)(b) — Eight Structural Conditions

| # | Condition | Verbatim Text (Art. 122B(5)(b)) |
|---|-----------|----------------------------------|
| (i) | **Creditor protection covenants** | "the entity is restricted from acting to the detriment of the creditors (including by not being able to issue additional debt without the consent of existing creditors)" |
| (ii) | **Reserve funds** | "the entity has sufficient reserve funds or other financial arrangements to cover the contingency funding and working capital requirements of the project" |
| (iii) | **Revenue mechanism** | "the revenues are subject to a rate-of-return regulation or take-or-pay contract or are availability-based" (see Art. 122B(6) for "availability-based" definition) |
| (iv) | **Main counterparty rating** | "the entity's revenue depends on one main counterparty and this main counterparty is one of the following:" — see counterparty sub-types below |
| (v) | **Default-protection covenants** | "the contractual provisions governing the exposure to the entity provide for a high degree of protection for creditors in case of a default of the entity" |
| (vi) | **Termination protection** | "the main counterparty or other counterparties which are included in the scope of point (iv) will protect the creditors from the losses resulting from a termination of the project" |
| (vii) | **Asset/contract pledge** | "all assets and contracts necessary to operate the project have been pledged to the creditors to the extent permitted by applicable law" |
| (viii) | **Creditor control on default** | "creditors may assume control of the entity in case of its default" |

#### Art. 122B(5)(b)(iv) — Eligible Main-Counterparty Sub-Types

The "main counterparty" in (iv) must be one of the following three categories. Counterparties
falling outside these three categories disqualify the exposure from the 80% weight irrespective
of how creditworthy they are:

| Sub-type | Eligible Counterparty | Cross-reference |
|----------|------------------------|-----------------|
| (1) | A central bank, central government, regional government, local authority, public sector entity, **or** a corporate entity that would be assigned **a risk weight of 80% or lower** under Part Three Title II Chapter 2 of the CRR (the SA chapter) | PS1/26 Part / CRR Part Three Title II Ch. 2 |
| (2) | A multilateral development bank that would be assigned a **0% risk weight** | Art. 117(2) |
| (3) | An international organisation that would be assigned a **0% risk weight** | Art. 118(1) |

!!! warning "80% Counterparty Cap is the Most Material Gating Condition"
    The (iv)(1) corporate sub-type is restricted to counterparties that themselves attract a
    risk weight of 80% **or lower** under SA. This effectively requires the off-taker to be
    investment-grade rated (CQS 1–3 corporate: 20%/50%/75%) or to qualify for the Art.
    122(6) IG corporate weight (65%). A BB-rated or unrated corporate off-taker (100% RW
    under Art. 122(2)/(5)) **disqualifies** the 80% PF weight. This single condition is the
    most common reason high-quality PF status is denied in practice.

### Availability-Based Revenues — Definition (Art. 122B(6))

For the purposes of Art. 122B(5)(b)(iii), revenues are **availability-based** only if all
three of the following hold:

- **(a)** The entity is entitled to payments from its contractual counterparties **once
  construction is completed**, as long as contract conditions are fulfilled.
- **(b)** The revenues are sized to cover **operating and maintenance costs, debt service
  costs, and equity returns** as the entity operates the project.
- **(c)** The revenues are **not subject to swings in demand**, and are adjusted only for
  lack of performance or lack of availability of the asset to the public.

Demand-risk concessions (e.g. shadow toll roads where revenue rises and falls with traffic
volume) do **not** meet condition (c) and therefore cannot satisfy Art. 122B(5)(b)(iii) via
the availability-based limb. Such projects must instead rely on rate-of-return regulation
or a take-or-pay contract to qualify.

### CRR Comparison

CRR has no SA specialised lending sub-classes. Under CRR, all unrated corporate exposures
(including SL) receive the flat **100%** corporate weight under Art. 122(2). The 130% pre-op,
100% operational, and 80% high-quality operational weights are **all** Basel 3.1 introductions.
For rated SL, both frameworks fall through to the rated corporate table — but CRR does so
implicitly (no SL distinction at all), while Art. 122B(1) makes the rule explicit.

See [CRR sa-risk-weights spec](../crr/sa-risk-weights.md) for the unchanged CRR treatment
and [framework-comparison/key-differences](../../framework-comparison/key-differences.md#high-quality-pf-criteria-art-122b45)
for the side-by-side change summary.

---

## Covered Bond Exposures (Art. 129)

PRA PS1/26 modifies Art. 129 in-place — there is no separate "Art. 129A".

### Rated Covered Bonds (Art. 129(4), Table 7)

PRA PS1/26 Art. 129(4) Table 7 values are **identical** to the CRR Table 6A values.
The PRA did **not** adopt the BCBS CRE20.28–29 reductions.

| CQS of Issuing Institution | Risk Weight |
|-----------------------------|-------------|
| CQS 1 | 10% |
| CQS 2 | **20%** |
| CQS 3 | 20% |
| CQS 4 | **50%** |
| CQS 5 | **50%** |
| CQS 6 | **100%** |

!!! warning "PRA Deviation from BCBS — PRA Table 7 Unchanged from CRR"
    BCBS CRE20.28–29 reduced certain rated covered bond risk weights (CQS 2: 20%→15%,
    CQS 4: 50%→25%, CQS 5: 50%→35%, CQS 6: 100%→50%). The PRA retained all six
    CRR values unchanged in PRA PS1/26 Art. 129(4) Table 7.

!!! success "P1.113 Fixed"
    `B31_COVERED_BOND_RISK_WEIGHTS` in `b31_risk_weights.py` now uses the correct PRA
    Table 7 values (identical to CRR). Previously used BCBS CRE20 values which
    understated capital for CQS 2 (15%→20%) and CQS 6 (50%→100%).

### Unrated Covered Bonds (Art. 129(5))

The derivation table is expanded from 4 to 7 entries to accommodate new institution
risk weights from ECRA and SCRA:

| Institution Senior Unsecured RW | Covered Bond RW | Art. 129(5) Sub-Para | Change |
|---------------------------------|-----------------|----------------------|--------|
| 20% | 10% | (a) | Unchanged |
| 30% | 15% | (aa) | **New** (ECRA CQS 2) |
| 40% | 20% | (ab) | **New** (SCRA Grade A) |
| 50% | 25% | (b) | ↓ from CRR 20% |
| 75% | 35% | (ba) | **New** (SCRA Grade B) |
| 100% | 50% | (c) | Unchanged |
| 150% | 100% | (d) | Unchanged |

### Covered Bond Due Diligence CQS Step-Up (Art. 129(4A))

**Regulatory text.** PRA PS1/26 Art. 129(4A) (p. 61) reads:

> An institution shall conduct due diligence to ensure that the external credit assessments
> appropriately and prudently reflect the creditworthiness of the eligible covered bonds to
> which the institution is exposed. If the due diligence analysis reflects higher risk
> characteristics than that implied by the credit quality step of the exposure, the
> institution shall assign a risk weight associated with a credit quality step that is at
> least one step higher than the risk weight determined by the external credit assessment.

**Trigger.** The step-up is driven by the *credit quality step* of the ECAI assessment used
under Art. 129(4) Table 7 (rated eligible covered bonds). The trigger is the firm's own DD
finding that the CQS mapping understates the bond's credit risk. For unrated covered bonds
risk-weighted via the Art. 129(5) institution-RW derivation chain, the step-up still applies
indirectly where the underlying institution exposure is itself stepped up under
Art. 120(4) — the derivation table at [Covered Bonds — Unrated](#covered-bonds-unrated-art-1295)
then yields the correspondingly higher covered-bond RW.

**Effect.** Worked one-step uplifts against Art. 129(4) Table 7 (rated covered bonds):

| Source CQS | Table 7 RW | Stepped-Up CQS | Stepped-Up RW | Change |
|------------|-----------|----------------|---------------|--------|
| CQS 1 | 10% | CQS 2 | 20% | +10pp |
| CQS 2 | 20% | CQS 3 | 20% | 0pp (plateau — CQS 2/3 both 20%) |
| CQS 3 | 20% | CQS 4 | 50% | +30pp |
| CQS 4 | 50% | CQS 5 | 50% | 0pp (plateau — CQS 4/5 both 50%) |
| CQS 5 | 50% | CQS 6 | 100% | +50pp |
| CQS 6 | 100% | — | 100% | Capped (already bottom of Table 7) |

Like Art. 120(4) for institutions, two CQS→CQS transitions (2→3 and 4→5) yield no numerical
change because Table 7 assigns identical RWs to those adjacent steps. The uplift is required
regardless — Art. 129(4A) mandates the CQS reassignment, even if the RW happens to coincide.
This matters for any downstream process that keys off CQS rather than RW (e.g. disclosure).

**Distinction from Art. 110A.** Art. 129(4A) is a narrower, rated-covered-bond-only rule with
a fixed one-step CQS uplift; [Art. 110A](#due-diligence-obligation-art-110a) applies to every
non-exempt SA exposure (including unrated covered bonds) and permits an unbounded uplift.
Where both would apply, the final RW is
`max(RW_Art_129_4A, RW_Art_110A_override, RW_Table_7)`.

**Parallel provisions.** Art. 129(4A) is textually near-identical to two other class-specific
step-up rules in PS1/26:

| Provision | Obligor class | RW reference |
|-----------|---------------|--------------|
| Art. 120(4) | Rated institutions | Art. 120(1) Table 3 |
| Art. 122(4) | Rated corporates | Art. 122(1) Table 6 |
| **Art. 129(4A)** | **Covered bonds** | **Art. 129(4) Table 7 / Art. 129(5) unrated derivation** |

All three share the same trigger ("DD reveals higher risk than implied by the CQS") and the
same consequence ("at least one CQS step higher"). CRR has no equivalent provision for any
of the three classes — the rules are Basel 3.1-only.

**Implementation status.** The calculator does not yet implement a dedicated Art. 129(4A)
branch. Firms currently carry Art. 129(4A) findings through the Art. 110A pathway: set
`due_diligence_override_rw` on the covered-bond facility to the next-CQS-band weight (e.g.
CQS 3 → 50% to reflect a stepped-up CQS 4 treatment), and the SA calculator will apply it as
a directional floor (see [Implementation](#implementation) above). This is functionally
equivalent and captured in the output via the `due_diligence_override_applied` audit column.

!!! warning "Firm responsibility — not an engine determination"
    The engine does not evaluate whether a DD finding is material enough to trigger
    Art. 129(4A). The firm determines when the step-up applies; the calculator only
    applies the resulting RW as a floor. Evidence that the step-up has been considered
    should be traceable to the firm's DD process documentation — particularly relevant
    for covered bonds, where Art. 129(7) already requires the firm to receive semi-annual
    portfolio information on the cover pool.

---

## Defaulted Exposures (Art. 127)

See [Defaulted Exposures Specification](defaulted-exposures.md) for the full treatment.

Summary: provision-coverage split — ≥20% provisions → 100% RW, <20% → 150% RW.
Secured portion retains collateral-based RW. RESI RE non-income exception: flat 100%.

---

## CIU Exposures (Art. 132)

Under Basel 3.1, CIU (Collective Investment Undertaking) exposures that cannot be looked
through receive a **1,250%** fallback risk weight (Art. 132(2)). This is a significant
increase from the CRR treatment and differs from the equity risk weights (250%/400%)
that might otherwise apply.

!!! warning "CIU Fallback = 1,250%"
    The 1,250% fallback applies to CIUs where the institution cannot apply the
    look-through approach (Art. 132a) or the mandate-based approach (Art. 132b).
    This is equivalent to a full capital deduction and applies regardless of the
    underlying asset composition of the fund.

---

## Equity (Art. 133)

See [Equity Approach Specification](equity-approach.md) for the full treatment.

Summary: exchange-traded/listed/unlisted 250%, higher-risk (unlisted + business < 5yr) 400%, subordinated debt 150%,
central bank 0%, government-supported 250%. Transitional phase-in 2027–2030. The end-state
risk weights apply from **1 January 2030**:

| Equity Type | End-State RW | Reference |
|-------------|-------------|-----------|
| Standard equity (listed/unlisted) | 250% | Art. 133(3) |
| Higher risk (unlisted + business < 5 years) | 400% | Art. 133(4) |
| Subordinated debt / non-equity own funds | 150% | Art. 133(5) |

---

## Basel 3.1 Changes Summary

- **Institution ECRA** (Art. 120): CQS 2 reduced to 30% — Done
- **Institution SCRA** (Art. 121): New grade-based approach with Grade A enhanced 30% — Done
- **Corporate sub-categories** (Art. 122(4)–(11)): SME 85%, IG 65%, non-IG 135% — Done
- **RE qualifying criteria** (Art. 124A): 6-criteria gate for preferential RE weights — Done
- **Other RE fallback** (Art. 124J): 150% / counterparty RW / max(60%, cpty RW) — Done
- **RRE loan-splitting** (Art. 124F–124G): Secured 20% / unsecured counterparty — Done
- **CRE loan-splitting** (Art. 124H): Secured 60% / unsecured counterparty — Done
- **CRE income-producing** (Art. 124I): PRA 2-band (100%/110%) — Done
- **SA Specialised Lending** (Art. 122A–122B): Type-specific weights, incl. 80% high-quality PF — Done
- **Currency mismatch** (Art. 123B): 1.5× multiplier, 150% cap — Done
- **Defaulted provision-coverage** (Art. 127): 100%/150% split — Done
- **Retail threshold** (Art. 123): Changed to GBP 880,000 — Done
- **CIU fallback** (Art. 132(2)): 1,250% for non-look-through CIUs — Documented
- **Short-term ECAI** (Art. 120(2B), Art. 122(3)): New Tables 4A / 6A for short-term assessments — Schema gap
- **SCRA trade finance** (Art. 121(4)): ≤6m trade goods exception for short-term weights — Documented
- **Supporting factors removed** (Art. 501/501a): SME replaced by 85% class — Done
- **Covered bonds rated** (Art. 129(4), Table 7): PRA retains CRR values — spec correct; code bug P1.113
- **Covered bonds unrated** (Art. 129(5)): Expanded 7-entry derivation table for SCRA weights — Done
- **Non-UK unrated PSE/RGLA**: Sovereign CQS-derived weights apply; flat 100% incorrect — code bug P1.112

---

## Key Scenarios

| Scenario ID | Description | Expected RW |
|-------------|-------------|-------------|
| B31-A1 | UK Sovereign CQS 1 | 0% |
| B31-A2 | UK Sovereign unrated | 100% |
| B31-A3 | UK Institution CQS 2 (ECRA) | 30% |
| B31-A4 | Rated corporate CQS 3 | 75% |
| B31-A5 | Unrated corporate (general, no PRA permission) | 100% |
| B31-A6 | Residential RE, 70% LTV (loan-splitting) | Blended: 20% secured + counterparty unsecured |
| B31-A7 | Income-producing commercial RE, 75% LTV | 100% |
| B31-A8 | Retail exposure | 75% |
| B31-A9 | SME corporate (turnover ≤ £44m) | 85% |
| B31-A10 | SME retail (under GBP 880k threshold) | 85% |
| B31-A11 | Non-qualifying income-producing RE (`is_qualifying_re=False`) | 150% (Art. 124J(1)) |

## Acceptance Tests

| Group | Scenarios | Tests | Pass Rate |
|-------|-----------|-------|-----------|
| B31-A: Standardised Approach | A1–A10 | 14 | 100% (14/14) |
