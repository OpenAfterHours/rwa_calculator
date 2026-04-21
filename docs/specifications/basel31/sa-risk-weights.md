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
| Grade A | **40%** | 20% | Meets all minimum prudential requirements and buffers (Art. 121(2)(b)) |
| Grade B | **75%** | 50% | Does not meet Grade A criteria but not materially deficient |
| Grade C | **150%** | 150% | Material deficiency in prudential standards |

!!! info "Grade A vs Grade A Enhanced"
    Grade A enhanced (30%, Art. 121(5)) requires **quantitative** thresholds: CET1 ≥ 14% and
    leverage ratio ≥ 5%. Grade A (40%) requires only **qualitative** compliance: the institution
    meets all minimum requirements and capital buffers. This distinction is new in Basel 3.1
    (CRE20.19).

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
    (Art. 122(11)). IRB output floor firms may elect the IG/non-IG split via Art. 122(8).

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

### Charge Conditions (Art. 124A(2))

Criterion (c) is satisfied if **any** of the following apply:

| Condition | Requirement |
|-----------|-------------|
| **(a)** First charge | Exposure is secured by a first-ranking charge over the property |
| **(b)** All prior charges held | Institution holds all charges ranking ahead of the exposure's charge |
| **(c)** Junior charge alternative | (i) Charge provides legally enforceable claim constituting effective CRM; (ii) each charge-holder can independently initiate sale; (iii) sale must seek fair market value or best price |

### Valuation Requirements (Art. 124D)

The valuation standard required by criterion (d):

- Valuation at origination by an independent qualified valuer or robust statistical method
- Must not exceed market value; for purchase financing, the lower of market value and purchase price
- Must not reflect expectations of speculative price increases
- Re-valuation triggers: material value reduction events, market decrease >10%, exposures >GBP 2.6m after 3 years, or all exposures every 5 years
- Self-build: value = higher of (underlying land value, 0.8 × latest qualifying valuation)

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

### Reassessment Triggers (Art. 124E(5))

Institutions must reassess material dependency when issuing a **new loan** secured by
residential RE to the same obligor (including replacement loans). Reassessment at other
times is permitted if new information is gathered and applied **consistently across the
portfolio** — selective reassessment to reduce capital requirements is prohibited.

### Commercial RE — Own-Use Test (Art. 124E(6)–(7))

A commercial RE exposure is **materially dependent by default**. The sole exception:
each property securing the exposure is **predominantly used by the borrower for its own
business purpose**, where the business purpose does **not** include generating income from
the property via rental agreements.

Institutions must reassess commercial RE material dependency **at least annually**
(Art. 124E(7)).

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
[Art. 124A qualifying criteria](#real-estate--qualifying-criteria-art-124a).

### General Residential — Loan-Splitting (Art. 124F)

Not [materially dependent](#real-estate--material-dependency-classification-art-124e)
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

[Materially dependent](#real-estate--material-dependency-classification-art-124e)
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
[Art. 124A qualifying criteria](#real-estate--qualifying-criteria-art-124a).

### CRE Loan-Splitting (Art. 124H(1))

Not [materially dependent](#real-estate--material-dependency-classification-art-124e)
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

[Materially dependent](#real-estate--material-dependency-classification-art-124e)
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
