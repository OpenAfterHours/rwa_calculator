# Model Permissions Specification

Basel 3.1 approach restrictions under Art. 147A limiting which exposure classes may use A-IRB,
and routing exposures to F-IRB, slotting, or SA based on regulatory constraints.

**Regulatory Reference:** PRA PS1/26 Art. 147A; PS1/26 Glossary p. 78 (LFSE definition, corresponds to CRR Art. 142(1)(4))
**Test Group:** B31-M

---

## Requirements Status

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-11.1 | Art. 147A approach restriction routing | P0 | Done |
| FR-11.2 | FSE restriction: all FSEs → F-IRB only (Art. 147A(1)(e)) | P0 | Done |
| FR-11.3 | Large corporate restriction: revenue >£440m → F-IRB only (Art. 147A(1)(e)) | P0 | Done |
| FR-11.4 | Institution exposure → F-IRB only, Art. 147A(1)(b) (no A-IRB) | P0 | Done |
| FR-11.5 | Equity exposure → SA only (Art. 147A(1)(h) per Art. 147(2)(e)) | P0 | Done |
| FR-11.6 | Sovereign/PSE (quasi-sovereigns) → SA only (Art. 147A(1)(a)) | P0 | Done |
| FR-11.7 | IPRE/HVCRE → Slotting only, Art. 147A(1)(c) (if no A-IRB permission) | P0 | Done |
| FR-11.8 | Model permissions config and fallback logic | P0 | Done |

---

## Overview

Art. 147A introduces **mandatory approach restrictions** that limit which exposure classes may use
the Advanced IRB (A-IRB) approach under Basel 3.1. These restrictions address concerns about
model risk in areas where internal estimates have proven unreliable or insufficiently validated.

The restrictions are enforced in the classifier stage of the pipeline, after hierarchy resolution
and before calculation. Exposures that fail the Art. 147A check are routed to a permitted approach.

## Art. 147A Approach Restrictions

### Restriction Table

The letter scheme in Art. 147A(1) points to sub-classes in **Art. 147(2)**
(verified against PRA PS1/26 ps126app1.pdf pp.88, 92–93, 17 Apr 2026). Financial
corporates and large corporates are **grouped together** under point (c)(ii) of
Art. 147(2) — both are handled by Art. 147A(1)(**e**), not by separate letters.

| Exposure Class | Permitted Approaches | Restriction | Reference |
|---------------|---------------------|-------------|-----------|
| Sovereign (incl. central banks, quasi-sovereigns) | SA only | No IRB permission | Art. 147A(1)(a) → Art. 147(2)(a) |
| PSE (treated as sovereign) | SA only | Follows sovereign treatment | Art. 147A(1)(a) |
| Institution | F-IRB only (SA with permission) | A-IRB not permitted | Art. 147A(1)(b) → Art. 147(2)(b) |
| SL IPRE / HVCRE | SA or Slotting only | No F-IRB or A-IRB | Art. 147A(1)(c) → Art. 147(2)(c)(i) |
| SL — OF / PF / CF | SA, F-IRB, A-IRB or Slotting | Subject to granted permission | Art. 147A(1)(d) → Art. 147(2)(c)(i) |
| **Financial corporate (all FSEs) AND Large corporate (revenue > £440m)** | **F-IRB only** (SA with permission) | A-IRB not permitted — both sub-classes share one rule under Art. 147(2)(c)(ii) | **Art. 147A(1)(e)** → Art. 147(2)(c)(ii) |
| Other general corporate (non-FSE, revenue ≤ £440m) | F-IRB (default); A-IRB with Art. 143(2A)/(2B) permission | A-IRB available only with explicit permission | Art. 147A(1)(f) → Art. 147(2)(c)(iii) |
| Retail (mortgage, QRRE, other) | A-IRB (SA with permission) | **Carry-forward from CRR** — retail has always been A-IRB-only (CRR Art. 151(7) mandated own-LGD/own-CCF for retail; F-IRB was only available for sovereign/institution/corporate under CRR Art. 151(8)). Not a new B31 restriction. | Art. 147A(1)(g) → Art. 147(2)(d); cf. CRR Art. 151(7) |
| Equity | SA only | IRB equity approaches removed (Art. 155 left blank) | Art. 147A(1)(h) → Art. 147(2)(e) |

!!! note "Art. 147A(1)(e) — FSEs and Large Corporates Share One Restriction"
    Under PRA PS1/26, **Art. 147A(1)(e)** covers both financial sector entities (FSEs,
    defined in Art. 4(1)(27)) and large corporates (revenue > £440m) because Art. 147(2)(c)(ii)
    groups them into the single sub-class "financial corporates and large corporates".
    Both are restricted to **F-IRB** (or SA with permission) — A-IRB is not available.
    The LFSE **total-assets** threshold — **GBP 79 billion** under PS1/26 Glossary p. 78
    (corresponds to CRR Art. 142(1)(4), which sets **EUR 70 billion** under CRR) — is a
    **separate** provision that drives the 1.25× correlation multiplier (Art. 153(2));
    it does NOT determine the approach restriction in Art. 147A(1)(e). Small FSEs below
    the LFSE threshold are still restricted to F-IRB under Art. 147A(1)(e).

!!! note "Earlier drafts incorrectly cited Art. 147A(1)(d) for large corporates"
    Previous versions of this spec cited "Art. 147A(1)(d)" for the large-corporate
    F-IRB restriction. That letter actually covers object/project/commodities finance
    under Art. 147(2)(c)(i). The authoritative rule for both large corporates and FSEs
    is Art. 147A(1)(**e**), verified against ps126app1.pdf p.92.

!!! info "Retail A-IRB-Only Is a CRR Carry-Forward, Not a New B31 Restriction"
    Art. 147A(1)(g) formalises — in the new structured Basel 3.1 wording — a rule that
    has been in force since the original CRR. Under **CRR Art. 151(7)**, firms applying
    IRB to retail (Art. 147(2)(d)) were **required** to provide own estimates of LGDs
    and conversion factors, i.e. A-IRB. **CRR Art. 151(8)** restricted F-IRB (supervisory
    LGDs under Art. 161(1) and supervisory CCFs under Art. 166(8)(a)–(d)) to exposure
    classes (a)–(c) — sovereigns, institutions, and corporates — with retail explicitly
    excluded from that list.

    The Basel 3.1 changes for retail are **not** about removing F-IRB (it was never
    available) — they are:

    - **New input floors**: PD floor 0.05% QRRE transactor / 0.10% non-transactor / 0.05% mortgage /
      0.10% other retail (Art. 160(1a)/(2)); LGD floors per Art. 164(4); EAD floors per
      Art. 166 — see [`airb-calculation.md`](airb-calculation.md).
    - **Subclass redefinition**: QRRE transactor/non-transactor split (PRA Glossary p.9);
      £90k single-obligor threshold in Art. 147(5A)(c).
    - **Maturity parameter unchanged**: `M = 1` continues to apply to retail under
      Art. 154(1)(c), as it did under CRR. This is a property of the retail IRB formula,
      not an Art. 147A restriction.

    See [`../../framework-comparison/key-differences.md#irb-approach-restrictions`](../../framework-comparison/key-differences.md#irb-approach-restrictions)
    for the full CRR-vs-B31 approach matrix, where the retail row correctly shows "A-IRB | A-IRB".

### Large Corporate Definition

**Art. 147A(1)(e) via Art. 147(2)(c)(ii):** A corporate exposure is classified as
"large corporate" if:

- The obligor's **consolidated annual revenue** exceeds **£440 million** (GBP)

!!! warning "Distinct Thresholds — Approach Restriction vs Correlation Multiplier"
    The **£440m revenue** threshold (Art. 147A(1)(e), via Art. 147(2)(c)(ii)) for the
    large-corporate approach restriction is entirely distinct from the LFSE
    **total-assets** threshold (**GBP 79 billion** under PS1/26 Glossary p. 78;
    EUR 70 billion under CRR Art. 142(1)(4)) for the FSE correlation multiplier.
    They target different populations and use different metrics:

    - **Art. 147A(1)(e)**: revenue-based (large corporates) and entity-type based (all FSEs),
      restricts A-IRB → F-IRB.
    - **LFSE threshold** (PS1/26 Glossary / CRR Art. 142(1)(4)): asset-based, applies 1.25×
      correlation uplift under Art. 153(2).

### Financial Sector Entity (FSE) Definition

**Art. 4(1)(27), Art. 147A(1)(e):** An FSE is an entity whose primary business involves:

- Banking, insurance, asset management, or financial intermediation

**All FSEs** (regardless of size) are restricted to F-IRB under Art. 147A(1)(e). This includes
both regulated and unregulated financial entities.

Separately, a **large FSE (LFSE)** — total assets ≥ **GBP 79 billion** under PS1/26 Glossary
p. 78 (CRR equivalent: ≥ EUR 70 billion per Art. 142(1)(4)) — receives the 1.25x correlation
multiplier under Art. 153(2). This correlation uplift is distinct from the approach restriction —
even small FSEs that do not trigger the correlation multiplier are still restricted to F-IRB.

### IPRE/HVCRE Routing

**Art. 147A(1)(c)** (via Art. 147(2)(c)(i)): Income-producing real estate (IPRE) and
high-volatility commercial real estate (HVCRE) exposures must use either the
**Standardised Approach** (with Art. 148 / Art. 150 permission) or the **Slotting Approach**.
F-IRB and A-IRB are **not** available for IPRE/HVCRE. In practice, most firms without
an Art. 148/150 SA permission for these sub-classes will route to slotting.

## Permission Configuration

Model permissions are configured via the `model_permissions` input data source, which specifies
per-exposure-class and per-model approach permissions:

```python
config = CalculationConfig.basel_3_1(
    irb_approach_permissions={
        ExposureClass.CORPORATE: ApproachType.AIRB,
        ExposureClass.RETAIL: ApproachType.AIRB,
        ExposureClass.INSTITUTION: ApproachType.FIRB,  # A-IRB not permitted
    }
)
```

### Routing Precedence

The classifier applies restrictions in the following order:

1. **Art. 147A hard constraints** — exposure class-level restrictions (equity→SA, sovereign→SA,
   institution→F-IRB, all FSEs→F-IRB, IPRE/HVCRE→slotting, retail→A-IRB) override any permission
2. **Threshold-based restrictions** — large corporate (>£440m revenue) overrides A-IRB permission
   to F-IRB
3. **Model permissions** — firm-specific approach permissions from the `model_permissions` table
4. **Fallback** — exposures with no valid permission fall back to SA

!!! note "Implementation"
    Art. 147A routing is implemented in `src/rwa_calc/engine/classifier.py`.
    Model permissions are loaded from the `model_permissions` data source and resolved
    at the exposure level. Invalid `model_id` values fall back to SA silently.

## Permanent Partial Use Materiality Thresholds (Art. 150(1A))

Art. 150(1A) permits firms to use the Standardised Approach permanently for certain exposure
classes or types, subject to materiality thresholds:

| Threshold | Condition | Reference |
|-----------|-----------|-----------|
| Significantly lower capital | SA RWA < 95% of IRB RWA for the roll-out class | Art. 150(1A)(a) |
| Immaterial | SA RWA <= 5% of total group credit risk RWA | Art. 150(1A)(b) |
| Type-level immateriality | All SA types within the class <= 5% of IRB-eligible total group RWA | Art. 150(1A)(c) |
| Majority | SA must not exceed 50% of RWA within a roll-out class | Art. 150(1A)(d) |

!!! warning "Not Yet Implemented"
    Art. 150(1A) materiality thresholds are not enforced in the calculator. The calculator
    routes exposures based on Art. 147A approach restrictions and model permissions, but does
    not validate that the aggregate SA usage is within the above thresholds. This is a
    firm-level portfolio constraint, not an exposure-level calculation.

---

## Fallback Behaviour

When no model permission matches an exposure:

- The exposure is routed to the **Standardised Approach** (SA)
- No error is raised (this is expected for exposures not covered by IRB approval)
- The fallback is logged as a data quality note, not an error

---

## Key Scenarios

| Scenario ID | Description | Expected Routing |
|-------------|-------------|------------------|
| B31-M1 | Corporate with AIRB permission, revenue < £440m | A-IRB |
| B31-M2 | Corporate with AIRB permission, revenue > £440m (large corporate) | F-IRB (Art. 147A(1)(e)) |
| B31-M3 | Large FSE with total assets ≥ GBP 79bn (PS1/26 Glossary) | F-IRB (Art. 147A(1)(e)) |
| B31-M3a | Small FSE with total assets < GBP 79bn | F-IRB (Art. 147A(1)(e) — all FSEs, not just large) |
| B31-M4 | Institution with AIRB permission | F-IRB (Art. 147A(1)(b)) |
| B31-M5 | Equity exposure | SA (Art. 147A(1)(h)) |
| B31-M6 | Sovereign exposure | SA (Art. 147A(1)(a)) |
| B31-M7 | PSE treated as sovereign | SA (Art. 147A(1)(a)) |
| B31-M8 | IPRE with no A-IRB permission | Slotting (Art. 147A(1)(c)) |
| B31-M9 | HVCRE with no A-IRB permission | Slotting (Art. 147A(1)(c)) |
| B31-M10 | PF with A-IRB permission | A-IRB (no restriction) |
| B31-M11 | Corporate at £440m boundary (exact threshold) | F-IRB (≥ £440m triggers Art. 147A(1)(e)) |
| B31-M12 | Exposure with no model permission | SA (fallback) |

## Acceptance Tests

| Group | Scenarios | Tests | Pass Rate |
|-------|-----------|-------|-----------|
| B31-M: Model Permissions | M1–M12 | 16 | 100% (16/16) |
