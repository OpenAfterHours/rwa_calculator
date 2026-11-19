# CIU Exposures

**CIU exposures** are holdings of units or shares in **Collective Investment Undertakings**
(funds — UCITS, AIFs, money-market funds, ETFs). Under Basel 3.1 (PRA PS1/26 Art. 132–132C),
CIUs are a standalone exposure class with three calculation approaches and a 1,250%
fallback.

## Definition

A CIU exposure is any holding of units or shares in a fund. Under Basel 3.1 Art. 112
Table A2 priority 2, CIUs sit **second only to securitisation positions** in the
exposure-class waterfall — the CIU treatment overrides any other classification an
underlying instrument might attract.

| Form | Treatment |
|------|-----------|
| Units / shares in UCITS | CIU class |
| Units / shares in AIFs | CIU class |
| Money-market fund holdings | CIU class |
| ETFs (when held as units) | CIU class |
| Off-balance-sheet commitments to subscribe | CIU class via Art. 132C |

CIUs that are **excluded** from the CIU treatment (Art. 132B(1)–(2)) include CET1/AT1/T2
instruments held by the CIU and required to be deducted, exposures to entities at 0% RW
(after a firm election), and equities incurred under government-sponsored legislative
programmes — these flow back to Art. 133 equity treatment.

## The Three Approaches (Art. 132A)

PRA PS1/26 Art. 132 establishes three calculation approaches in **descending order of
preference**:

```mermaid
flowchart TD
    A[CIU Holding] --> B{Sufficient information<br>about underlying exposures?}
    B -->|Yes| C[Look-through Approach<br>Art. 132A(1)]
    B -->|No| D{Mandate / prospectus<br>data quality conditions met?}
    D -->|Yes| E[Mandate-Based Approach<br>Art. 132A(2)]
    D -->|No| F[Fallback Approach<br>Art. 132(2) — 1,250%]
```

### Look-Through Approach (Art. 132A(1))

The institution **risk-weights every underlying exposure of the CIU as if it held them
directly**, then multiplies the resulting weighted total by its fractional holding in the
fund. This is the lowest-RW route but has the strictest data requirements.

**Conditions (Art. 132(3)):**

- The CIU's prospectus or equivalent document discloses (i) authorised asset categories
  and (ii) where investment limits apply, the relative limits and methodology to compute them.
- Reporting from the CIU / management company:
    - **Quarterly minimum** frequency on the CIU's exposures
    - Granularity sufficient to compute the chosen approach
    - For look-through: underlying exposures **verified by an independent third party**

### Mandate-Based Approach (Art. 132A(2))

Where the institution lacks sufficient data to look through individual exposures, it
calculates the RWA against the **maximum exposures permitted by the CIU's mandate**.

**Conservative assumption (Art. 132A(2) second sub-paragraph):** the institution must
assume the CIU first incurs exposures, **to the maximum extent allowed**, in the asset
categories attracting the **highest own-funds requirement**, then continues in
descending order until the maximum total exposure limit is reached, **and that the CIU
applies leverage to the maximum extent allowed** under its mandate.

**Reduced reporting:** Quarterly reporting is **not required** for mandate-based — the
institution may rely on the CIU's investment mandate plus updates only on first
acquisition and on mandate change (Art. 132(3) derogation).

### Fallback Approach (Art. 132(2))

Where neither look-through nor mandate-based conditions are met:

| Treatment | Risk Weight |
|-----------|-------------|
| Fallback CIU exposure | **1,250%** |

A 1,250% weight is equivalent to a full capital deduction (1 ÷ 8% = 12.5×) — every
GBP of exposure consumes a full GBP of common equity capital. This is intentional: it
makes look-through and mandate-based the only economically viable approaches for
material CIU portfolios.

!!! warning "Fallback applies regardless of underlying composition"
    The 1,250% weight applies even where the CIU is invested entirely in 0%-weighted
    sovereigns. The Basel 3.1 design penalises **opacity**, not the underlying credit
    risk — firms cannot avoid 1,250% by asserting the underlying exposures *would*
    qualify for low weights.

> **Details:** See [CIU Exposures (Art. 132) specification](../../specifications/basel31/sa-risk-weights.md#ciu-exposures-art-132) for the full spec including the third-party calculation route under Art. 132(4) and multi-level CIU rules under Art. 132(5).

## Combining Approaches (Art. 132(2) Sub-Para 3)

An institution **may use a combination** of look-through, mandate-based, and fallback
on a single CIU **provided the conditions for each approach are met for the relevant
exposures**. A CIU disclosing 70% of its assets via verified look-through reporting
and treating the remaining 30% as a mandate-based bucket is permitted, as is partial
treatment with 1,250% fallback for the un-disclosed slice.

## Multi-Level CIUs — CIUs of CIUs (Art. 132(5))

Where a level-1 CIU itself holds units in a level-2 CIU:

| Level-1 approach | Level-2 onward | Constraint |
|------------------|----------------|------------|
| Look-through | Any of look-through / mandate-based / fallback | Free choice |
| Mandate-based | Any of look-through / mandate-based / fallback | Free choice |
| Look-through at level 1 → look-through at level 2 → look-through at level 3 | Permitted only if **previous level used look-through** | Strict cascade |
| Look-through breaks at any level | All subsequent levels → **fallback** | — |

**In the calculator.** The `ciu_holdings` table carries no look-through or mandate
data for a level-2 CIU, so a holding whose `exposure_class` is `ciu` is weighted at the
**1,250% fallback** on its value (the level-2 "any other scenario"), in both regimes.
The same weight applies to a holding whose class the engine cannot identify — a null or
a value outside the `ExposureClass` vocabulary (`securitisation`, `subordinated_debt`,
`sovereign`, …) — because it cannot be weighted "as if directly held" (Art. 132A(1));
the input gate reports those values as `SA008`. A `high_risk` holding takes the
Art. 128 150% under Basel 3.1 (100% under CRR, where Art. 128 is omitted). See the
holding-class table in the
[CRR equity specification](../../specifications/crr/equity-approach.md).

## Third-Party Calculation Reliance (Art. 132(4))

An institution lacking the data to compute Art. 132A approaches itself may rely on a
third party's calculation, provided:

- **(a)** The third party is the depository institution / depository financial
    institution (where the CIU invests exclusively in securities deposited there) **or**
    the CIU management company.
- **(b)** The third party uses Art. 132A(1), (2), or (3) (i.e., not its own bespoke
    method).
- **(c)** An external auditor has confirmed the correctness of the third party's calculation.

**1.2× multiplier:** The institution multiplies the third-party RWA by **1.2** as a
"data-quality penalty". This multiplier is **waived** if the institution has unrestricted
access to the detailed underlying calculations and can produce them on PRA request.

## Cap on Risk-Sensitive Approaches (Art. 132(6))

The RWA produced by look-through or mandate-based **shall be capped** at the RWA the
fallback (1,250%) would produce. This is a regulatory backstop — exotic structured
funds where the modelled RWA on underlying derivatives or short positions might
*exceed* 1,250% are still capped at 1,250%.

## Off-Balance-Sheet CIU Commitments (Art. 132C)

Where an institution has an **off-balance-sheet commitment** to subscribe to a CIU
(e.g., a subscription line not yet drawn):

For commitments where the institution applies look-through or mandate-based to the
on-balance portion:

```
RW*_i = (RWEA_i / E*_i) × (A_i / EQ_i)
```

Where:

- `RWEA_i` = the RWA of the CIU's exposures under Art. 132A
- `E*_i` = the on-balance exposure value of the CIU
- `A_i` = the accounting value of the CIU's assets
- `EQ_i` = the accounting value of the CIU's equity (so `A_i / EQ_i` is the leverage ratio)

For all **other** off-balance commitments (i.e. where the institution falls back
to 1,250% on the on-balance portion): `RW*_i = 1,250%`.

## PRA Notification Threshold — "Relevant CIUs" (Art. 132(8))

A **"relevant CIU"** (defined in PS1/26 Art. 1.2 Glossary) is a CIU:

- managed by a company **registered in a third country**, AND
- for which the institution applies look-through (Art. 132A(1)) or mandate-based
  (Art. 132A(2)) — i.e., this notification regime does not bite where the firm uses
  the 1,250% fallback.

The institution **must notify the PRA** when **either** of the following thresholds
is reached on an individual or consolidated basis (Art. 132(8)(a)):

| Threshold | Trigger |
|-----------|---------|
| Total RWAs for relevant-CIU exposures exceed **0.5% of the institution's total credit-risk + dilution-risk RWA** | Art. 132(8)(a)(i) |
| Total exposure values for relevant-CIU exposures exceed **GBP 500 million** | Art. 132(8)(a)(ii) |

The notification must include:

- A list of the countries in which the fund managers of all relevant CIUs are located
  (Art. 132(8)(d)(i))
- The total exposure values and total RWAs in respect of those countries (Art. 132(8)(d)(ii))

The institution must also notify the PRA promptly when **both** thresholds drop back
below the limits (Art. 132(8)(c)), and must repeat the notification annually while in
breach (Art. 132(8)(b)).

!!! info "Why third-country managers specifically?"
    The PRA notification regime targets jurisdictions where the prudential supervision,
    transparency, and recourse against the fund manager may be weaker than UK / EEA
    standards. The notification gives the PRA visibility over concentrations of
    fund-management exposure to jurisdictions outside its direct supervisory reach,
    independent of the underlying assets in the CIU.

!!! warning "GBP 500m, not GBP 2bn"
    The exposure-value threshold is **GBP 500 million** in PRA PS1/26 Art. 132(8)(a)(ii).
    The 0.5% RWA-based threshold is the relative limb. Earlier consultation drafting
    or BCBS-aligned references to other figures should be treated as superseded by the
    final PS1/26 values.

## CRR vs Basel 3.1 — Key Differences

!!! info "CRR Art. 132 omitted from UK CRR"
    Under UK-onshored CRR (effective until 31 Dec 2026), **CRR Art. 132 was omitted**
    and CIU treatment is governed by the PRA Rulebook directly via Art. 132a–132c.
    CRR firms today already operate under a near-identical look-through / mandate-based
    / 1,250% framework — Basel 3.1's main change is the addition of **Art. 132A** as a
    consolidated approaches article and the introduction of the **Art. 132(8)
    relevant-CIU notification regime** for third-country managers.

| Aspect | CRR (PRA Rulebook) | Basel 3.1 (PRA PS1/26) |
|--------|---------------------|------------------------|
| Look-through | Art. 132a — same conditions | Art. 132A(1) — same conditions |
| Mandate-based | Art. 132b — same logic | Art. 132A(2) — same logic, reduced reporting derogation |
| Fallback | 1,250% (Art. 132c) | 1,250% (Art. 132(2)) |
| Third-party reliance | Allowed with 1.2× penalty | Allowed with 1.2× penalty (Art. 132(4)) |
| Cap on look-through | None explicit | **Capped at fallback RWA** (Art. 132(6)) |
| Off-balance commitments | Standard CCF on commitment value | **Art. 132C leverage-based formula** |
| Multi-level CIU (CIU of CIUs) | Limited guidance | Explicit cascade rule (Art. 132(5)) |
| Third-country relevant-CIU notification | None | **GBP 500m / 0.5% RWA** notification (Art. 132(8)) |
| AML/CFT treatment of fund manager domicile | Implicit firm risk-management | **Explicit "relevant CIU" definition** for third-country managers |

## Implementation Status

!!! warning "CIU Calculator Coverage"
    The current calculator implements the **1,250% fallback** for any exposure flagged
    as a non-look-through CIU, but does not natively compute the look-through or
    mandate-based RWA. Firms applying Art. 132A(1) or (2) must compute the underlying-
    exposure RWA externally and pass it as a pre-computed value, or set
    `apply_ciu_fallback = True` to attract the 1,250% weight. Multi-level CIUs, the
    Art. 132(4) third-party 1.2× penalty, the Art. 132C off-balance leverage formula,
    and the Art. 132(8) third-country notification regime are firm-governance
    obligations sitting outside the calculator scope.

## Calculation Examples

### Example 1 — Look-Through Equity Fund

**Exposure:**

- £20,000,000 holding in a UK UCITS equity fund (1.5% of fund)
- Fund holds £1,000,000,000 of FTSE-100 listed equity
- Quarterly verified third-party look-through reporting available

**Calculation:**

```
# Look-through: equity SA RW = 250% (Art. 133(3) listed)
RWA_underlying = 1,000,000,000 × 250% = 2,500,000,000
# Pro-rata to holding fraction
Institution_RWA = 2,500,000,000 × 1.5% = 37,500,000
```

### Example 2 — Mandate-Based Mixed Fund

**Exposure:**

- £15,000,000 holding in a multi-asset fund (3% of fund)
- Mandate permits up to 60% equity, 30% IG corporate bonds, 10% leverage
- No quarterly look-through data available — mandate-based applies

**Conservative mandate-based stack:**

```
# Highest-RW first: 60% equity at 250% = 60% × 250% = 150%
# Next: 30% IG corporate at 65% = 30% × 65% = 19.5%
# Plus 10% leverage applied to the highest weight: 10% × 250% = 25%
Effective_RW = 150% + 19.5% + 25% = 194.5%
RWA_underlying = 1,000,000,000 × 194.5% = 1,945,000,000  # full fund
Institution_RWA = 1,945,000,000 × 3% = 58,350,000
# Cap (Art. 132(6)): cannot exceed 15,000,000 × 1250% = 187,500,000 — not binding
```

### Example 3 — Fallback (Opaque Hedge Fund)

**Exposure:**

- £5,000,000 investment in an offshore hedge fund
- No mandate disclosure, no look-through reporting

**Calculation:**

```
RW = 1,250% (Art. 132(2) fallback)
RWA = 5,000,000 × 1,250% = 62,500,000
# Equivalent to full deduction: 5m × 8% = 400,000 capital required = 5m × 8%
```

### Example 4 — Relevant-CIU Notification Trigger

**Scenario:**

- Total RWA for credit + dilution risk: £20,000,000,000
- 0.5% threshold: £100,000,000 RWA
- Holdings in third-country-managed CIUs: £1,200,000,000 exposure value, £840,000,000 RWA

**Outcome:**

```
# Test 1 (RWA): 840,000,000 > 100,000,000 → trigger
# Test 2 (Exposure value): 1,200,000,000 > 500,000,000 → trigger (independently)
→ PRA notification required (Art. 132(8)(a)).
```

The institution must list the third-country domiciles of every relevant CIU's fund
manager and provide per-country exposure-value and RWA totals.

## Input Schema Summary

| Field | Type | Description |
|-------|------|-------------|
| `apply_ciu_fallback` | bool | When `True`, applies Art. 132(2) 1,250% fallback regardless of other inputs |
| `ciu_approach` | enum | `"look_through"` / `"mandate_based"` / `"fallback"` — selects Art. 132A approach |
| `ciu_lookthrough_rwa` | Decimal | Pre-computed underlying-exposures RWA when look-through or mandate-based applies |
| `ciu_third_party_calculation` | bool | When `True`, applies Art. 132(4) 1.2× multiplier to `ciu_lookthrough_rwa` |
| `ciu_unrestricted_access` | bool | When `True` together with `ciu_third_party_calculation`, waives the 1.2× multiplier |
| `is_relevant_ciu` | bool | Flags third-country-managed CIU for Art. 132(8) notification reporting |

## Regulatory References

| Topic | PRA PS1/26 / CRR | BCBS CRE |
|-------|------------------|----------|
| CIU framework | Art. 132 | CRE60.10–60.40 |
| Approaches (look-through, mandate-based) | Art. 132A | CRE60.16–60.20 |
| Exclusions (deductions, equity programmes) | Art. 132B | — |
| Off-balance-sheet CIU commitments | Art. 132C | CRE60.21 |
| Fallback 1,250% | Art. 132(2) | CRE60.27 |
| Third-party reliance and 1.2× penalty | Art. 132(4) | CRE60.18 |
| Cap on look-through / mandate-based | Art. 132(6) | CRE60.20 |
| Multi-level CIU cascade | Art. 132(5) | CRE60.22 |
| Relevant-CIU PRA notification | Art. 132(8) | — (UK-specific) |
| "Relevant CIU" definition (third-country manager) | PS1/26 Art. 1.2 Glossary | — |
| Legacy CRR CIU rules | CRR Art. 132 (omitted) → PRA Rulebook Art. 132a–132c | — |
| Equity exposures (excluded from CIU treatment) | Art. 132B(2) → Art. 133 | CRE60.11 |

## Next Steps

- [Real Estate Exposures](secured-by-real-estate.md) — for funds holding RE
- [Other Exposure Classes — Equity](other.md#equity-exposures) — equity exclusion route under Art. 132B(2)
- [Standardised Approach](../methodology/standardised-approach.md)
- [SA Risk Weights specification (Basel 3.1)](../../specifications/basel31/sa-risk-weights.md)
