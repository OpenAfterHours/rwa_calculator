# Model Permissions Specification

Basel 3.1 approach restrictions under Art. 147A limiting which exposure classes may use A-IRB,
and routing exposures to F-IRB, slotting, or SA based on regulatory constraints.

**Regulatory Reference:** PRA PS1/26 Art. 147A, Art. 4(1)(146)
**Test Group:** B31-M

---

## Requirements Status

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-11.1 | Art. 147A approach restriction routing | P0 | Done |
| FR-11.2 | FSE restriction: all FSEs → F-IRB only (Art. 147A(1)(e)) | P0 | Done |
| FR-11.3 | Large corporate restriction: revenue >£440m → F-IRB only | P0 | Done |
| FR-11.4 | Institution exposure → F-IRB only (no A-IRB) | P0 | Done |
| FR-11.5 | Equity exposure → SA only | P0 | Done |
| FR-11.6 | Sovereign/PSE → SA only | P0 | Done |
| FR-11.7 | IPRE/HVCRE → Slotting only (if no A-IRB permission) | P0 | Done |
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

| Exposure Class | Permitted Approaches | Restriction | Reference |
|---------------|---------------------|-------------|-----------|
| Equity | SA only | IRB equity approaches removed entirely (Art. 155 left blank) | Art. 147A(1)(a) |
| Sovereign | SA only | No IRB permission for sovereigns | Art. 147A(1)(b) |
| PSE (treated as sovereign) | SA only | Follows sovereign treatment | Art. 147A(1)(b) |
| Institution | F-IRB only | A-IRB not permitted | Art. 147A(1)(c) |
| Financial corporate (all FSEs) | F-IRB only | A-IRB not permitted for any financial sector entity | Art. 147A(1)(e) |
| Large corporate (revenue > £440m) | F-IRB only | A-IRB not permitted | Art. 147A(1)(d) |
| SL IPRE / HVCRE | Slotting only | Must use slotting (no F-IRB or A-IRB) | Art. 147A(2) |
| Corporate (standard, non-FSE, revenue <= £440m) | F-IRB or A-IRB | A-IRB with permission, F-IRB otherwise | — |
| Retail | A-IRB only | No maturity adjustment (existing rule) | Art. 147A(1)(f) |
| Specialised lending (PF, OF, CF) | F-IRB, A-IRB, or Slotting | Subject to existing permissions | — |

!!! note "Art. 147A(1)(e) — All FSEs Restricted to F-IRB"
    Art. 147A(1)(e) restricts **all** financial sector entities (as defined in Art. 4(1)(27))
    to F-IRB, not just large FSEs. The EUR 70bn / GBP 79bn threshold (Art. 4(1)(146)) determines
    the **1.25x correlation multiplier** (Art. 153(2)), which is a separate provision. Even small
    regulated FSEs cannot use A-IRB under Basel 3.1.

### Large Corporate Definition

**Art. 147A(1)(d):** A corporate exposure is classified as "large corporate" if:

- The obligor's **consolidated annual revenue** exceeds **£440 million** (GBP)

!!! warning "Distinct from Large FSE"
    The **£440m revenue** threshold (Art. 147A(1)(d)) for large corporate approach restriction
    is entirely distinct from the **EUR 70bn total assets** threshold (Art. 4(1)(146)) for the
    financial sector entity (FSE) correlation multiplier. They target different populations
    and use different metrics:

    - Art. 147A(1)(d): revenue-based, restricts A-IRB → F-IRB
    - Art. 4(1)(146): asset-based, applies 1.25× correlation uplift

### Financial Sector Entity (FSE) Definition

**Art. 4(1)(27), Art. 147A(1)(e):** An FSE is an entity whose primary business involves:

- Banking, insurance, asset management, or financial intermediation

**All FSEs** (regardless of size) are restricted to F-IRB under Art. 147A(1)(e). This includes
both regulated and unregulated financial entities.

Separately, a **large FSE** (total assets > EUR 70 billion, ≈ GBP 79bn, per Art. 4(1)(146))
receives the 1.25x correlation multiplier under Art. 153(2). This correlation uplift is distinct
from the approach restriction — even small FSEs that do not trigger the correlation multiplier
are still restricted to F-IRB.

### IPRE/HVCRE Routing

**Art. 147A(2):** Income-producing real estate (IPRE) and high-volatility commercial real estate (HVCRE)
exposures must use the **slotting approach** unless the firm has specific A-IRB approval for these
sub-classes. In practice, most firms without granular A-IRB IPRE permission will route to slotting.

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
| B31-M2 | Corporate with AIRB permission, revenue > £440m (large corporate) | F-IRB (Art. 147A(1)(d)) |
| B31-M3 | Large FSE with total assets > EUR 70bn | F-IRB (Art. 147A(1)(e)) |
| B31-M3a | Small FSE with total assets < EUR 70bn | F-IRB (Art. 147A(1)(e) — all FSEs, not just large) |
| B31-M4 | Institution with AIRB permission | F-IRB (Art. 147A(1)(c)) |
| B31-M5 | Equity exposure | SA (Art. 147A(1)(a)) |
| B31-M6 | Sovereign exposure | SA (Art. 147A(1)(b)) |
| B31-M7 | PSE treated as sovereign | SA (Art. 147A(1)(b)) |
| B31-M8 | IPRE with no A-IRB permission | Slotting (Art. 147A(2)) |
| B31-M9 | HVCRE with no A-IRB permission | Slotting (Art. 147A(2)) |
| B31-M10 | PF with A-IRB permission | A-IRB (no restriction) |
| B31-M11 | Corporate at £440m boundary (exact threshold) | F-IRB (≥ £440m triggers) |
| B31-M12 | Exposure with no model permission | SA (fallback) |

## Acceptance Tests

| Group | Scenarios | Tests | Pass Rate |
|-------|-----------|-------|-----------|
| B31-M: Model Permissions | M1–M12 | 16 | 100% (16/16) |
