# Equity Approach Specification

Basel 3.1 equity treatment: new SA risk weight regime (250%/400%), removal of IRB equity
approaches, transitional phase-in schedule, and CIU treatment.

**Regulatory Reference:** PRA PS1/26 Art. 132–133, Art. 147A(1)(h), Rules 4.1–4.10
**Test Group:** B31-L

---

## Requirements Status

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-9.1 | SA equity risk weights by sub-category (Art. 133) | P0 | Done |
| FR-9.2 | IRB equity approaches removed (Art. 147A(1)(h)) | P0 | Done |
| FR-9.3 | Transitional phase-in schedule (Rules 4.1–4.10, 3-year window 1 Jan 2027 – 31 Dec 2029) | P0 | Done |
| FR-9.4 | CIU fallback treatment (Art. 132(2)) | P0 | Done |
| FR-9.5 | CIU mandate-based treatment (Art. 132(4)) | P0 | Done |
| FR-9.6 | CIU look-through treatment (Art. 132a) | P0 | Done |
| FR-9.7 | Transitional exclusions (central bank, subordinated debt, CIU non-fallback) | P0 | Done |
| FR-9.8 | Higher-risk classification (unlisted + business < 5 years) | P0 | Done |

---

## Overview

Basel 3.1 fundamentally changes equity treatment by:

1. **Removing IRB equity** — Art. 147A(1)(h) prohibits use of IRB approaches for equity
2. **Introducing differentiated SA weights** — replacing CRR's flat 100% (Art. 133(2)) with
   sub-category-specific weights (250%/400%)
3. **Adding a transitional schedule** — phasing in the higher weights over a
   3-year window (1 January 2027 – 31 December 2029), with steady-state
   Art. 133 weights applying from 1 January 2030

### Key Changes from CRR

| Feature | CRR | Basel 3.1 | Reference |
|---------|-----|-----------|-----------|
| SA equity (standard) | 100% flat | **250%** | Art. 133(3) |
| SA equity (higher risk) | 100% flat | **400%** | Art. 133(4) |
| Subordinated debt / non-equity own funds | 100% | **150%** | Art. 133(5) |
| Government-supported equity | 100% | **250%** (standard) | Art. 133(3) |
| IRB Simple approach | Available (Art. 155) | **Removed** | Art. 147A(1)(h) |
| IRB PD/LGD approach | Available | **Removed** | Art. 147A(1)(h) |
| CIU fallback | 1,250% (Art. 132(2)) | **1,250%** (unchanged) | Art. 132(2) |

---

## SA Equity Risk Weights (Art. 133)

### Risk Weight Table

| Equity Sub-Category | Risk Weight | Reference |
|--------------------|-------------|-----------|
| Subordinated debt / non-equity own funds | **150%** | Art. 133(5) |
| Standard equity (listed, exchange-traded, government-supported) | **250%** | Art. 133(3) |
| Unlisted equity (non-higher-risk) | **250%** | Art. 133(3) |
| Other equity | **250%** | Art. 133(3) |
| Higher-risk equity (unlisted + business < 5 years — see [definition below](#higher-risk-classification-art-1334)) | **400%** | Art. 133(4) |

!!! warning "Correction: Art. 133(6) is NOT a 100% Risk Weight (Fixed v0.1.189)"
    Art. 133(6) is an **exclusion clause** that scopes out exposures already handled
    elsewhere: (a) own funds deductions per Chapter 3, (b) 1,250% per Art. 89(3),
    (c) 250% per Art. 48(4). It does **not** assign a 100% risk weight.
    CRR Art. 133(3)(c) had a 100% legislative equity carve-out, but B31 Art. 133
    removes it. Government-supported equity is standard 250% equity under B31.

### Higher-Risk Classification (Art. 133(4))

An equity exposure is classified as **higher risk** (400%) if **both** of the following
conditions are met (PRA PS1/26 Glossary, p.5):

1. **Not listed on a recognised exchange**, AND
2. The underlying **business has existed for less than five years**

The five-year clock starts from the date the business was first established within the
undertaking. Where the business was transferred from another entity, the start date depends
on whether the risk profile substantially changed on transfer (Glossary p.5, conditions
(a)–(b)).

!!! warning "Correction: Higher-Risk Definition (Fixed D1.38)"
    This section previously defined higher-risk equity as "unlisted AND (short-term resale
    OR derivative position), OR PE/VC". That was the **BCBS CRE60.20** definition, not PRA.
    PRA PS1/26 Glossary (p.5) defines higher-risk equity solely by two criteria: unlisted
    + business < 5 years. There is no short-term resale, derivative position, or automatic
    PE/VC criterion. PE/VC is only higher-risk if it meets both conditions.

!!! warning "No CQS Speculative Tiers in PRA"
    The BCBS framework (CRE60.20) includes speculative unlisted equity tiers differentiated
    by CQS. PRA PS1/26 Art. 133 does **not** use CQS-based speculative tiers for equity.
    All non-subordinated equity is either standard (250%, Art. 133(3))
    or higher-risk (400%, Art. 133(4)). The calculator's `is_speculative` flag maps to
    the Art. 133(4) higher-risk definition, not a BCBS CQS tier.

!!! info "Business-Age-Aware Higher-Risk Routing"
    The equity SA risk-weight logic (`engine/equity/calculator.py::_apply_equity_weights_sa`)
    is business-age aware: unlisted PE/VC (`private_equity`, `private_equity_diversified`)
    is routed to the higher-risk 400% weight only when the underlying business has existed
    for less than five years — or when business age is unknown/unevidenced, which is treated
    conservatively as < 5 years (a firm cannot claim the long-established carve-out without
    evidence). Long-established PE/VC (`business_age_years` >= 5) falls through to the
    standard **250%** weight. See D3.37.

All other equity (not subordinated debt, not higher-risk) receives the standard **250%**
weight under Art. 133(3), including listed equity, government-supported equity, and
unlisted PE/VC where the business has existed for five years or more.

---

## IRB Equity Removal (Art. 147A(1)(h))

Under Basel 3.1, **all equity exposures must use the Standardised Approach**. The following
CRR approaches are no longer available:

- **IRB Simple** (Art. 155) — exchange-traded 290%, PE diversified 190%, other 370%
- **IRB PD/LGD** — modelled PD with 90% LGD floor
- **Internal Models** — VaR-based equity capital

The removal is implemented in the equity calculator's approach determination:

```python
# Basel 3.1: IRB equity removed — all equity uses SA
if not resolved_pack.feature("equity_irb_approaches_available"):
    return EquityApproach.SA
```

Under CRR, the calculator returns `IRB_SIMPLE` if any exposure class has F-IRB or A-IRB permission.

---

## Transitional Phase-In (Rules 4.1–4.10)

Both the SA equity transitional (Rules 4.1–4.3) and the IRB equity/CIU
transitional (Rules 4.4–4.10) run for **three years**: from 1 January 2027 to
31 December 2029, with the steady-state Art. 133 weights (250%/400%)
applying from 1 January 2030 onward. The two pathways are textually distinct
in PS1/26 Appendix 1, Chapter 4, and apply to different populations of firms.

!!! info "SA equity vs. IRB equity/CIU transitional — both run 3 years"
    A reader should not conflate the two transitional regimes with the
    output-floor transitional (which is a 4-year phase-in 2027–2030,
    Art. 92(5)). The equity transitional periods are explicitly bounded
    "beginning with 1 January 2027 and ending with 31 December 2029" in
    PS1/26 App 1 Rule 4.2 and Rule 4.3, and the IRB-track Rules 4.5–4.8
    are themselves anchored to "the IRB equities and CIU transition
    period" defined by Rules 4.4 and 4.7 over the same window.
    Steady-state 250%/400% under Art. 133(3)/(4) applies from 1 January 2030.

### Comparative timeline — equity transitional regimes

| Aspect | SA equity transitional (Rules 4.1–4.3) | IRB equity / CIU transitional (Rules 4.4–4.10) |
|--------|---------------------------------------|------------------------------------------------|
| Scope (firms) | Did **not** have Art. 143 IRB permission on 31 Dec 2026 (Rule 4.1) | **Had** Art. 143 IRB permission on 31 Dec 2026 (Rules 4.4, 4.7) |
| Scope (exposures) | All direct equity exposures | Direct equity (Rules 4.5–4.6) **and** CIU equity underlyings previously on Art. 155(2) simple-RW (Rules 4.7–4.8) |
| Start date | 1 January 2027 | 1 January 2027 |
| End date | **31 December 2029** | **31 December 2029** |
| Duration | **3 years** | **3 years** |
| Mechanism | Direct phased weights (Rules 4.2 / 4.3 schedule) | "Higher of" legacy Art. 155 IRB weight (or Art. 155(2) simple-RW for CIU) and the SA Rule 4.2/4.3 transitional weight |
| Opt-out | n/a — these firms have no legacy IRB equity methodology | Rules 4.9–4.10: irrevocable election into immediate steady-state Art. 133 / Art. 132A (with prior PRA notice) |
| Steady state from | 1 January 2030 (Art. 133(3)/(4)) | 1 January 2030 (Art. 133(3)/(4)) |

### Phase-In Schedule (Rules 4.2–4.3)

The Rule 4.2/4.3 schedule below is the *operative* phase-in for the SA-only
track and is also the floor leg of the IRB-track "higher of" tests in
Rules 4.6 and 4.8.

| Year | Standard RW Floor (Rule 4.2) | Higher-Risk RW Floor (Rule 4.3) |
|------|------------------------------|--------------------------------|
| 2027 | **160%** | **220%** |
| 2028 | **190%** | **280%** |
| 2029 | **220%** | **340%** |
| 2030+ (steady state, Art. 133) | **250%** | **400%** |

The transitional works as a **floor**:

```
final_rw = max(assigned_rw, transitional_floor_rw)
```

During the transitional period, the floor ensures exposures receive at least the
phase-in weight, even if the calculator would assign a lower weight.

### Transitional Exclusions

The following equity sub-categories are **excluded** from the transitional floor
(their weights apply directly without a phase-in floor):

- **Central bank** (0%) — already below the floor, exclusion is moot
- **Subordinated debt / non-equity own funds** (150%) — fixed rate (Art. 133(5))
- **CIU look-through** — weight derives from underlying assets, not Art. 133
- **CIU mandate-based** — weight derives from fund mandate, not Art. 133

### SA Transitional (Rules 4.1–4.3) — Firms Without IRB Permission

Rule 4.1 restricts Rules 4.2–4.3 to firms that **did not** have permission to use the
IRB Approach (Art. 143 of CRR) on 31 December 2026. These firms apply the phase-in
schedule above directly to all equity exposures over the **three-year window
1 January 2027 – 31 December 2029** (Rule 4.2 chapeau, Rule 4.3 chapeau). From
1 January 2030 the steady-state Art. 133(3)/(4) weights (250%/400%) apply
without any transitional modification.

### IRB Transitional (Rules 4.4–4.6) — Firms With IRB Permission

Rule 4.4 scopes Rules 4.5–4.6 to firms that **had** IRB permission on
31 December 2026, and bounds those rules to the **"IRB equities and CIU
transition period"** — which Rules 4.5/4.6 implicitly tie to Rules 4.2/4.3,
i.e. **1 January 2027 – 31 December 2029 (3 years)**. From 1 January 2030,
the steady-state Art. 133(3)/(4) weights apply directly with no legacy-IRB
"higher of" test.

These firms bifurcate their equity portfolio per Rule 4.5:

1. **SA equities** (Rule 4.5(1)): Equity exposures that were on the Standardised Approach
   (Art. 148 or Art. 150 of CRR) at 31 Dec 2026 use the same phase-in schedule as
   Rules 4.2/4.3 above.
2. **IRB equities** (Rules 4.5(2) + 4.6): Equity exposures that were on the IRB Approach
   (Art. 143 of CRR) at 31 Dec 2026 use the **higher of**:
     - the risk weight from the firm's legacy IRB methodology (Art. 155 of CRR, as in
       force on 31 Dec 2026), and
     - the transitional SA risk weight from Rules 4.2 or 4.3.

This "higher of" test provides a floor-based transition — IRB firms cannot produce risk
weights below the transitional SA schedule, but retain their legacy IRB weights where
those are higher.

### CIU Transitional (Rules 4.7–4.8) — Firms With IRB Permission

During the **same three-year IRB equities and CIU transition period
(1 January 2027 – 31 December 2029)** scoped by Rule 4.7, Rule 4.8 applies
to firms that had Art. 143 IRB permission on 31 December 2026. For CIU
equity underlyings that were subject to the simple risk weight approach
(Art. 155(2) of CRR, as in force before 1 Jan 2027), the firm assigns the
**higher of**:

- the old simple risk weight (CRR Art. 155(2)), and
- the transitional SA equity weight from Rules 4.2/4.3.

This applies when using look-through (Art. 132A(1) / Art. 152(4)) or mandate-based
(Art. 132A(2) / Art. 152(5)) approaches. From 1 January 2030 the standard
Art. 132A / Art. 152 CIU treatment applies without the legacy Art. 155(2) floor.

### Opt-Out (Rules 4.9–4.10) — Firms With IRB Permission

Instead of Rules 4.5–4.6 and 4.8, a firm with IRB equity/CIU permission at
31 Dec 2026 may elect under Rule 4.9 to apply:

- full steady-state Art. 133 weights immediately (250%/400%) for direct equity, and
- standard CIU treatment (Art. 132A / Art. 152) without the simple risk weight floor.

This election is **irrevocable**: Rule 4.10 requires prior notice to the PRA and,
once exercised, prevents the institution from later returning to Rules 4.5–4.8.
The opt-out covers both direct equity and CIU underlyings — a firm cannot opt out of
one while retaining the other (Rule 4.9(1) and 4.9(2) are jointly elected).
The opt-out is meaningful only during 2027–2029; from 1 January 2030 every
firm is on the steady-state Art. 133 / Art. 132A regime regardless of the
election.

---

## Transitional provisions (Rules 4.1–4.10) — PDF citations

This section anchors the transitional phase-in rules to verbatim text from
PS1/26 Appendix 1 (`docs/assets/ps126app1.pdf`). The Rules sit in Chapter 4
("TRANSITIONAL PROVISIONS") of the Credit Risk: Standardised Approach (CRR) Part.

### Rule 4.1 — Scope gate for SA-only firms (PS1/26 App 1, p.20)

> "4.2 and 4.3 only apply to an institution that did not have permission to use
> the Internal Ratings Based Approach under Article 143 of CRR on 31 December 2026."

### Rule 4.2 — Standard SA equity transitional (PS1/26 App 1, p.20)

> "This rule modifies paragraph 3 of Credit Risk: Standardised Approach (CRR) Part
> Article 133 for a transitional period beginning with 1 January 2027 and ending
> with 31 December 2029, in which equity exposures that are not higher risk equity
> exposures or within the scope of paragraph 6 of Credit Risk: Standardised
> Approach (CRR) Part Article 133 shall be assigned the following risk weights:
>
> (1) 160% during the period beginning with 1 January 2027 and ending with 31 December 2027;
> (2) 190% during the period beginning with 1 January 2028 and ending with 31 December 2028; and
> (3) 220% during the period beginning with 1 January 2029 and ending with 31 December 2029."

From 1 January 2030, the steady-state 250% under Art. 133(3) applies directly — there
is no Rule 4.2(4).

### Rule 4.3 — Higher-risk SA equity transitional (PS1/26 App 1, p.21)

> "This rule modifies paragraph 4 of Credit Risk: Standardised Approach (CRR) Part
> Article 133 for a transitional period between 1 January 2027 and 31 December
> 2029, in which equity exposures that are higher risk equity exposures and are
> not within scope of paragraph 6 of Credit Risk: Standardised Approach (CRR) Part
> Article 133 shall be assigned the following risk weights:
>
> (1) 220% during the period beginning with 1 January 2027 and ending with 31 December 2027;
> (2) 280% during the period beginning with 1 January 2028 and ending with 31 December 2028; and
> (3) 340% during the period beginning with 1 January 2029 and ending with 31 December 2029."

### Rules 4.4–4.6 — IRB transitional: max(legacy Art. 155, SA transitional) (PS1/26 App 1, p.21)

Rule 4.4 is the IRB-track scope gate (the equivalent of Rule 4.1 on the
SA-only track) and is also the textual anchor for the **3-year duration**
of the IRB equity transitional. It introduces the term "the IRB equities
and CIU transition period" that is then referenced throughout
Rules 4.5–4.8:

> "4.4 During the IRB equities and CIU transition period, 4.5 to 4.6 apply by
> way of derogation from the treatment laid down in paragraph 3 of Credit Risk:
> Standardised Approach (CRR) Part Article 133 to an institution which, on 31
> December 2026, had permission to apply the Internal Ratings Based Approach
> under Article 143 of CRR."

Rule 4.5 bifurcates the firm's equity portfolio; Rule 4.6 is the "higher of"
test that ties IRB-track weights to the Rule 4.2/4.3 dates (1 Jan 2027 –
31 Dec 2029) by reference:

> "4.6 Subject to 4.9, an institution shall calculate the risk weight for each
> equity exposure as the higher of:
>
> (1) the risk weight calculated using the relevant methodology used by the institution as specified in its permission to use the Internal Ratings Based Approach under Article 155 of CRR as that provision was in force on 31 December 2026; and
> (2) the risk weight calculated under 4.2 or 4.3."

This means IRB equity firms do not get a "pure legacy Art. 155" transition — their
post-2026 weight can never fall below the Rule 4.2/4.3 schedule, and the
transition itself ends with Rules 4.2/4.3 on 31 December 2029.

### Rules 4.7–4.8 — CIU look-through / mandate-based equity underlyings (PS1/26 App 1, pp.21–22)

Rule 4.7 mirrors Rule 4.4 for the CIU pathway and confirms that CIU
look-through / mandate-based equity underlyings share the **same 3-year
"IRB equities and CIU transition period"**:

> "4.7 During the IRB equities and CIU transition period, 4.8 applies by way of
> derogation from the treatment laid down in Credit Risk: Standardised Approach
> (CRR) Part Article 132A and Credit Risk: Internal Ratings Based Approach (CRR)
> Part Article 152 to an institution which, on 31 December 2026, had permission
> to apply the Internal Ratings Based Approach under Article 143 of CRR."

> "4.8 Subject to 4.9, an institution which calculates risk weights of CIUs using:
>
> (1) the look-through approach in paragraph 1 of Credit Risk: Standardised Approach (CRR) Part Article 132A or paragraph 4 of Credit Risk: Internal Ratings Based Approach (CRR) Part Article 152; or
> (2) the mandate-based approach in paragraph 2 of Credit Risk: Standardised Approach (CRR) Part Article 132A or paragraph 5 of Credit Risk: Internal Ratings Based Approach (CRR) Part Article 152,
>
> shall assign a risk weight to each underlying exposure in the CIUs to which the
> institution would have applied the simple risk weight approach in accordance
> with point (a) of paragraph 4 of Standardised Approach and Internal Ratings
> Based Approach to Credit Risk (CRR) Part Article 152, as that provision was in
> force before 1 January 2027, by using the higher of:
>
> (3) the risk weight that would have applied to the underlying exposure under the simple risk weight approach set out in Article 155(2) of CRR, as that provision was in force before 1 January 2027; and
> (4) the risk weight calculated under 4.2 or 4.3."

Only equity underlyings that would have qualified for Art. 155(2) legacy simple
risk weight treatment are within scope of Rule 4.8; non-equity underlyings of CIUs
flow through the usual Art. 132A/Art. 152 pathways without a transitional floor.

### Rules 4.9–4.10 — Irrevocable opt-out into steady-state (PS1/26 App 1, p.22)

Rule 4.9 lets an IRB-permission firm skip Rules 4.5–4.8 and apply
the steady-state Art. 133 / Art. 132A / Art. 152 treatment from 1 January 2027.
Rule 4.10 is the irrevocability provision, requiring prior PRA notice and
locking the firm out of any future return to the transitional approaches:

> "4.9 Subject to 4.10, instead of using the alternative approaches set out
> in 4.5, 4.6 and 4.8, an institution may choose to calculate both:
>
> (1) risk weights for equity exposures in accordance with Credit Risk:
> Standardised Approach (CRR) Part Article 133, instead of in accordance with
> the two approaches set out in 4.5 and 4.6; and
>
> (2) risk weights of exposures underlying CIUs within the scope of 4.8(1) and
> 4.8(2) in accordance with:
>
> (a) if the institution has an IRB Permission, Credit Risk: Internal Ratings
> Based Approach (CRR) Part Article 152;
>
> (b) if the institution does not have an IRB Permission, Credit Risk:
> Standardised Approach (CRR) Part Article 132A."

> "4.10 An institution shall give the PRA prior notice of its use of the
> approaches in 4.9. Once an institution uses the approach in 4.9 it shall not
> use the approaches in 4.5 to 4.8."

Note that the opt-out applies **jointly** to direct equity (Rule 4.9(1)) and
CIU equity underlyings (Rule 4.9(2)) — the Rule 4.9 chapeau requires the
institution to "calculate **both**" categories under steady-state Art. 133 /
Art. 132A / Art. 152 if it elects out of the transitional regime.

!!! warning "Not yet implemented — SA transitional (Rules 4.2/4.3)"
    The calculator currently applies the steady-state 250%/400% weights from day one
    for all firms. Rules 4.2/4.3 phase-in (160%→190%→220% / 220%→280%→340%) is
    not wired into the equity calculator. See **IMPLEMENTATION_PLAN.md P1.137**
    (SA equity transitional phase-in).

!!! warning "Not yet implemented — IRB legacy-Art. 155 max (Rules 4.6/4.8)"
    The "higher of legacy Art. 155 weight and Rule 4.2/4.3 transitional" logic for
    firms holding IRB equity permission on 31 Dec 2026 (Rule 4.6) and the same
    logic for CIU look-through / mandate-based equity underlyings (Rule 4.8) are
    not yet implemented. Implementing these requires (a) capturing the legacy
    Art. 155 methodology weight per exposure, and (b) storing a firm-level flag
    indicating whether IRB equity permission existed on 31 Dec 2026. See
    **IMPLEMENTATION_PLAN.md P1.138** (IRB equity transitional max, Rule 4.6)
    and **IMPLEMENTATION_PLAN.md P1.139** (CIU equity transitional max, Rule 4.8).

---

## CIU Treatment (Art. 132, 132a, 132b)

Collective Investment Undertakings (CIUs) — funds, ETFs, unit trusts — have three treatment
options depending on the firm's knowledge of the fund's holdings:

### 1. Look-Through Approach (Art. 132a)

When the firm can identify the CIU's underlying holdings:

- Each underlying is risk-weighted per its own exposure class and CQS
- A **value-weighted average RW** is computed across all holdings
- **Leverage adjustment** (Art. 132a(3)): when `fund_nav > 0`, RWA is grossed up
  by dividing total value by NAV, capturing the effect of fund leverage

```
ciu_rw = sum(holding_value_i x rw_i) / fund_nav
```

Fallback if look-through data is incomplete: **250%** (B31) / **150%** (CRR).

### 2. Mandate-Based Approach (Art. 132b)

When the firm knows the fund's investment mandate but not individual holdings:

- The fund's mandate defines the maximum risk-weight-applicable class
- `ciu_mandate_rw` is set based on the mandate's highest-risk category
- **Third-party calculation factor** (Art. 132(4)): if the RW is calculated by a third party
  (not the firm), multiply by **1.2×**

Default mandate RW if not specified: **250%** (B31) / **150%** (CRR).

### 3. Fallback Approach (Art. 132(2))

When neither look-through nor mandate-based is available:

| Condition | Risk Weight | Reference |
|-----------|-------------|-----------|
| Regulatory CIU fallback | **1,250%** | Art. 132(2) |

!!! note "Fixed in v0.1.181"
    The CIU fallback is correctly applied as **1,250%** under both CRR and Basel 3.1,
    matching PRA PS1/26 Art. 132(2): "shall assign a risk weight of 1,250%
    ('fall-back approach')". Prior to v0.1.181 the code incorrectly applied Art. 133
    equity weights (250%/400%) instead.

### CIU Approach Selection

The approach is determined by the `ciu_approach` input column:

| Value | Approach | Transitional Floor |
|-------|----------|-------------------|
| `look_through` | Look-through (Art. 132a) | Excluded |
| `mandate_based` | Mandate-based (Art. 132b) | Excluded |
| `fallback` | Fallback (Art. 132(2)) | Applied |
| null / unset | Defaults to fallback | Applied |

---

## PRA Notification — Third-Country "Relevant CIU" Exposures (Art. 132(8))

PS1/26 introduces a new UK-specific notification regime for institutions whose
CIU exposures are managed from outside the UK. It is **not** a risk-weight rule —
it is a firm-governance reporting obligation that sits alongside the SA equity /
CIU calculations and feeds into PRA supervisory oversight of third-country
fund-management concentrations.

!!! warning "Plan-item misattribution: Art. 132(3A)/(3B) and Art. 132(4A) do not exist"
    `DOCS_IMPLEMENTATION_PLAN.md` items **D4.58** and **D4.66** describe this
    notification regime as "Art. 132(3A)/(3B)" (AML/CFT-deficient third countries,
    ≥2% of own funds) and "Art. 132(4A)" (GBP 2 billion RWA / GBP 500 million
    exposure). Neither sub-paragraph exists in PS1/26 Appendix 1, and PS1/26
    contains **no AML/CFT-based** CIU notification trigger. The actual provision
    is **Art. 132(8)**, with thresholds of **0.5% of total credit-risk + dilution-risk
    RWA** (not 2% of own funds, not GBP 2bn RWA) **and GBP 500 million exposure
    value**, triggered by the firm's use of look-through or mandate-based
    approaches for **third-country-managed** CIUs (the "relevant CIU" definition
    in PS1/26 Art. 1.2 Glossary), **not** by AML/CFT deficiency of the CIU's
    establishment country. This page documents the verbatim Art. 132(8) text;
    D4.58 and D4.66 should be reconciled into a single resolved item.

### Definition — "Relevant CIU" (PS1/26 Art. 1.2 Glossary, p.27)

> "**relevant CIU** means a CIU:
>
> (1) that is managed by a company which is registered in a third country; and
>
> (2) for which an institution applies the look-through approach in accordance
> with Article 132A(1) or the mandate-based approach in accordance with Article
> 132A(2) to calculate the risk-weighted exposure amount for their exposures in
> the form of units or shares in the CIU."

The definition is **scope-limited to third-country-managed CIUs** for which the
institution actually uses look-through or mandate-based. CIUs falling back to
the 1,250% Art. 132(2) treatment are outside the "relevant CIU" perimeter and
do not contribute to the Art. 132(8) thresholds. The trigger is **third-country
fund-management domicile**, not the CIU's country of establishment, and not any
AML/CFT assessment of either jurisdiction.

### Verbatim Art. 132(8) (PS1/26 App 1, pp. 64–65)

> "8.
>
> (a) An institution shall notify the PRA if either:
>
> (i) the total risk-weighted exposure amounts for all of its exposures in the
> form of units or shares in relevant CIUs exceed 0.5% of the institution's total
> risk-weighted exposures for credit risk and dilution risk calculated in
> accordance with Title II of Part Three of CRR and the Credit Risk: General
> Provisions (CRR) Part, the Credit Risk: Standardised Approach (CRR) Part, the
> Credit Risk: Internal Ratings Based Approach (CRR) Part, the Credit Risk
> Mitigation (CRR) Part and the Counterparty Credit Risk (CRR) Part; or
>
> (ii) the total exposure values for all of its exposures in the form of units
> or shares in relevant CIUs exceed GBP 500 million;
>
> in each case calculated on an individual or consolidated basis.
>
> (b) An institution shall make the notification in point (a) of this paragraph
> promptly if:
>
> (i) at any time either of the thresholds in point (a)(i) or (ii) of this
> paragraph is reached; and
>
> (ii) until such time as it makes a notification under point (c) of this
> paragraph, on an annual basis thereafter.
>
> (c) An institution which has made or is required to have made a notification
> under point (a) of this paragraph shall also notify the PRA promptly when both
> the total risk-weighted exposure amounts and total exposure values are below
> the relevant thresholds set out in point (a)(i) and (ii) of this paragraph.
>
> (d) An institution shall include in the notification made under point (a) of
> this paragraph:
>
> (i) a list of the countries in which fund managers of all relevant CIUs to
> which it is exposed are located; and
>
> (ii) the total exposure values and total risk-weighted exposure amounts in
> respect of its exposures in the form of units or shares in relevant CIUs for
> each of those countries."

### Plain-English Summary

| Element | Position |
|---------|----------|
| Who is in scope | Institutions using **look-through (Art. 132A(1))** or **mandate-based (Art. 132A(2))** for CIUs **managed by a company registered in a third country**. Fallback (1,250%) CIUs are out of scope. |
| Trigger 1 — relative limb | Total RWA on relevant-CIU exposures > **0.5% of total credit-risk + dilution-risk RWA** (Art. 132(8)(a)(i)) |
| Trigger 2 — absolute limb | Total exposure value on relevant-CIU exposures > **GBP 500 million** (Art. 132(8)(a)(ii)) |
| Trigger logic | **Either** limb breach is sufficient ("if either"). The 0.5% RWA limb and the GBP 500m exposure-value limb are **independent**, not cumulative. |
| Calculation basis | Individual **or** consolidated basis (Art. 132(8)(a) closing words). |
| Initial notification | "Promptly" once either threshold is reached (Art. 132(8)(b)(i)). |
| Recurring notification | **Annually** thereafter, until the firm makes a "below threshold" notification (Art. 132(8)(b)(ii)). |
| Stand-down notification | Promptly, once **both** measures fall below the thresholds (Art. 132(8)(c) — note the conjunctive "both"). |
| Scope of disclosure | List of countries hosting fund managers of all relevant CIUs **plus** per-country exposure value and RWA (Art. 132(8)(d)). |

!!! info "Trigger asymmetry: 'either' to enter, 'both' to exit"
    The institution enters the notification regime as soon as **either** limb
    (a)(i) or (a)(ii) is breached, but only exits when **both** measures fall
    below their respective thresholds (Art. 132(8)(c)). A firm that is below the
    0.5% RWA limb but above the GBP 500m exposure-value limb (or vice versa)
    remains inside the notification regime.

### Distinction from Other PRA Notification Triggers

There is **only one** Art. 132 PRA notification regime in PS1/26 — Art. 132(8).
Plan items D4.58 ("AML/CFT, ≥2% of own funds") and D4.66 ("GBP 2 billion RWA")
both refer to the same underlying Art. 132(8) provision but with **incorrect
attributions, incorrect thresholds, and an incorrect AML/CFT trigger that is not
in PS1/26 at all**. The genuine Art. 132(8) provision is summarised above.

The output-floor disclosure (Art. 92(5)) and the IRB equity opt-out notice
(Rule 4.10) are unrelated notification regimes that operate on different
triggers and are not within Art. 132's scope.

!!! warning "D4.66 reconciliation: cited 'Art. 132(4A)' / 'GBP 2bn' do not exist"
    `DOCS_IMPLEMENTATION_PLAN.md` item **D4.66** describes a "PS1/26 Art. 132(4A)"
    notification trigger of "**GBP 2 billion** total RWA in relevant CIUs OR
    **GBP 500 million** total exposure values in relevant CIUs". A search of the
    PS1/26 Appendix 1 source PDF confirms:

    - **No sub-paragraph "Art. 132(4A)" exists** anywhere in PS1/26 Appendix 1.
      The only Art. 132 sub-paragraphs are 132(1)–132(8) plus the standalone
      Articles 132A / 132B / 132C.
    - **No "GBP 2 billion" figure appears** anywhere in PS1/26 Appendix 1 in
      relation to Art. 132 (or anywhere else in the CIU notification regime).
    - The actual thresholds in **Art. 132(8)(a)** are
      (i) **0.5% of total credit-risk + dilution-risk RWA** and
      (ii) **GBP 500 million exposure value**, with **either** limb sufficient
      to trigger notification. The GBP 500m limb in D4.66 is correct; the
      "GBP 2bn RWA" limb is fabricated and the relative limb is in fact
      0.5% of credit-risk + dilution-risk RWA, not an absolute GBP figure.
    - The annual-notification cadence and per-country listing requirement
      cited in D4.66 are correctly captured in **Art. 132(8)(b)(ii)** and
      **Art. 132(8)(d)** respectively (verbatim quoted above).

    D4.66 is therefore **fully covered by the same Art. 132(8) coverage that
    closed D4.58** — the canonical content lives in this single section, and
    no new sub-section is warranted. D4.66 is ready to be ticked alongside the
    misattribution note already recorded for D4.58.

### CRR Comparison

!!! info "CRR Art. 132 omitted from UK CRR"
    Under UK-onshored CRR (in force until 31 December 2026), **CRR Art. 132 was
    omitted by SI 2021/1078** and CIU treatment was instead governed by PRA
    Rulebook Articles 132a–132c without an explicit relevant-CIU notification
    regime. The Art. 132(8) third-country notification regime is therefore a
    **Basel 3.1 / PS1/26-only addition** with no CRR predecessor — there is no
    transitional treatment because there is no legacy provision to transition
    from.

| Aspect | CRR (UK Rulebook, to 31 Dec 2026) | Basel 3.1 (PS1/26, from 1 Jan 2027) |
|--------|------------------------------------|--------------------------------------|
| Third-country fund-manager notification | None | **Art. 132(8)** (0.5% RWA / GBP 500m) |
| "Relevant CIU" Glossary definition | Not defined | **Defined** (third-country manager + look-through / mandate-based) |
| Reporting cadence | n/a | Prompt + annual until cleared |
| Country-level exposure breakdown | Not required | **Required** (Art. 132(8)(d)) |

### Operational Implementation

The Art. 132(8) regime is a **firm-governance and reporting obligation** that
sits outside the RWA calculator's scope. The calculator may still flag exposures
as `is_relevant_ciu = True` for downstream COREP / firm-level aggregation, but
the calculation of whether either threshold is breached, and the production of
the per-country breakdown, are operational tasks owned by the firm's CIU
inventory and PRA-reporting workflow.

For the matching COREP changes — including the new "of which: exposures to
relevant CIUs" rows in the relevant template — see
[COREP reporting changes](../../framework-comparison/reporting-differences.md#section-4-ciu-approach)
and the [CIU user-guide page](../../user-guide/exposure-classes/cius.md#pra-notification-threshold-relevant-cius-art-1328).

---

## Waterfall Precedence

When classifying equity exposures, the following priority order applies:

1. **CIU** (Art. 132) — if the exposure is a fund holding
2. **Central bank / sovereign equity** — 0% (sovereign treatment, not Art. 133)
3. **Equity** (Art. 133) — 250%/400% by sub-category, including subordinated debt (150%,
   Art. 133(5)). Art. 133(6) is an exclusion clause, not a risk weight.
4. **High-risk** (Art. 128) — 150% (re-introduced in B31, see [SA Risk Weights](sa-risk-weights.md))

Equity exposures take priority over high-risk classification. PE/VC that meets the
higher-risk definition (unlisted + business < 5 years) is classified as equity
(Art. 133(4), 400%), not high-risk (Art. 128, 150%). PE/VC that does not meet the
higher-risk definition receives standard 250% (Art. 133(3)).

---

## Key Scenarios

| Scenario ID | Description | Expected RW |
|-------------|-------------|-------------|
| B31-L1 | Exchange-traded equity (standard) | 250% |
| B31-L2 | Private equity (higher risk — business < 5yr) | 400% |
| B31-L3 | Speculative unlisted (higher risk) | 400% |
| B31-L4 | Central bank equity | 0% |
| B31-L5 | Government-supported equity | 250% |
| B31-L6 | Subordinated debt | 150% |
| B31-L7 | Unlisted equity (standard) | 250% |
| B31-L8 | CIU look-through (diversified fund) | Weighted average of underlyings |
| B31-L9 | CIU mandate-based | Mandate RW |
| B31-L10 | CIU mandate-based with third-party calc | Mandate RW × 1.2 |
| B31-L11 | CIU fallback (listed) | 1,250% |
| B31-L12 | CIU fallback (unlisted) | 1,250% |
| B31-L13 | 2027 transitional: standard equity | max(250%, 160%) = 250% |
| B31-L14 | 2027 transitional: higher-risk equity | max(400%, 220%) = 400% |
| B31-L15 | 2027 transitional: standard below floor | Floor binds at 160% |
| B31-L16 | Central bank excluded from transitional | 0% (no floor) |
| B31-L17 | Government-supported subject to transitional | 250% (exceeds all floors) |
| B31-L18 | CIU look-through excluded from transitional | Look-through RW (no floor) |
| B31-L19 | PE diversified (higher risk — business < 5yr) | 400% |
| B31-L20 | Other equity (catch-all) | 250% |
| B31-L21 | Leveraged fund look-through | RW grossed up by leverage |
| B31-L22 | Listed equity (standard) | 250% |
| B31-L23 | 2028 transitional: standard equity floor | max(assigned, 190%) |

## Acceptance Tests

| Group | Scenarios | Tests | Pass Rate |
|-------|-----------|-------|-----------|
| B31-L: Equity Approach | L1–L23 | 49 | 100% (49/49) |
