# Covered Bond Exposures

**Eligible covered bonds** are debt securities issued by credit institutions and
secured by a dedicated pool of high-quality assets (the cover pool) over which
bondholders have a priority claim. Under PRA PS1/26 Art. 129, covered bonds receive
**preferential risk weights** materially below senior-unsecured exposures to the
same issuer, in recognition of the dual-recourse structure (issuer + cover pool).

## Definition

A **CRR covered bond** is a bond subject to special legislation protecting the
bondholders against losses, where the bondholder has a **priority claim** on a
ring-fenced cover pool in the event of issuer default. An eligible covered bond
qualifies for Art. 129 preferential treatment when it meets:

- The Art. 129(1) **eligible cover-pool composition** rules
- The Art. 129(3) **valuation requirements** for any RE in the pool
- The Art. 129(7) **investor disclosure / portfolio information** rules

Covered bonds sit at **priority 6** in the Art. 112 Table A2 exposure class waterfall —
above institutions, sovereigns, and corporates but below securitisation, CIUs,
subordinated debt, high-risk items, and defaults.

!!! note "Treatment is by issuer institution, not by cover-pool composition"
    Covered bond risk weights are derived from the **issuer's** CQS (rated table)
    or senior-unsecured RW (unrated derivation). The cover pool determines
    eligibility, not the risk weight directly.

## Eligibility — Art. 129(1)

An eligible covered bond must be **collateralised by any of the following eligible
assets** (Art. 129(1)(a)–(g)):

| # | Eligible cover-pool assets | Reference |
|---|------------------------------|-----------|
| (a) | Exposures to or guaranteed by the **UK central government, Bank of England, UK regional government, UK PSE, or UK local authority** | Art. 129(1)(a) |
| (b)(i)–(vi) | Exposures to or guaranteed by **third-country sovereigns/central banks/MDBs/international organisations/PSEs/RGLAs** at CQS 1 (mapped per Commission Implementing Regulation (EU) 2016/1799) | Art. 129(1)(b)(i)–(vi) |
| **(b)(vii)** | **CQS 2 sovereign-type exposures up to 20% of nominal outstanding covered bonds** — the concentration carve-out | Art. 129(1)(b)(vii) |
| **(c)** | **CQS 1/2 institution exposures up to 15% of nominal outstanding covered bonds** — the institution concentration carve-out | Art. 129(1)(c) |
| (d) | Loans secured by **residential RE up to ≤80% LTV** of pledged property | Art. 129(1)(d) |
| (e) | *[Provision left blank]* | — |
| (f) | Loans secured by **commercial RE up to ≤60% LTV** (extendable to 70% with ≥10% overcollateralisation, legal certainty, and priority claim) | Art. 129(1)(f) |
| (g) | Loans secured by **maritime liens on ships up to ≤60% LTV** (less prior maritime liens) | Art. 129(1)(g) |

### Concentration Carve-Outs

The two concentration limits in (b)(vii) and (c) are the operationally most material
restrictions for issuers — they determine how much **non-CQS-1 sovereign-type or
institution exposure** can sit in the cover pool without breaching eligibility:

| Carve-out | Limit (vs. nominal outstanding covered bonds) |
|-----------|-----------------------------------------------|
| CQS 2 sovereign-type (b)(vii) | **20%** |
| CQS 1/2 institution (c) | **15%** |

**Art. 129(1A) carve-out from the limits:** Exposures arising from the **transmission
and management of payments** of the underlying obligors, or from the **liquidation
proceeds** in respect of loans secured by pledged properties of the senior units or
debt securities, **are excluded from the calculation** of the (c) institution
concentration limit. This prevents pure cash-flow conduit operations from consuming
the 15% institution allowance.

### Other Eligibility Conditions

- Bondholder priority claim in the issuer's insolvency (Art. 129(2) — collateral
  exclusively restricted by legislation to bondholder protection).
- Cover-pool RE collateral meets:
    - Art. 208 collateral requirements (excluding the default-revaluation requirement)
    - Art. 229(1) valuation rules (excluding the prior-charges adjustment)
- Issuer makes **semi-annual portfolio information** available (Art. 129(7)):
    - Cover-pool value and outstanding bonds
    - Geographic distribution, asset type, loan size, interest rate, currency risk
    - Maturity structure
    - Percentage of loans > 90 days past due

### Pre-2007 Legacy Bonds (Art. 129(6))

CRR covered bonds **issued before 31 December 2007** that meet the Art. 129(7)
disclosure requirements remain eligible until maturity, and are **not subject to
the Art. 129(1) cover-pool composition or Art. 129(3) valuation rules**.

## Risk Weights — Rated (Art. 129(4), Table 7)

Where the covered bond has a credit assessment from a nominated ECAI:

| CQS of Covered Bond | Risk Weight |
|----------------------|-------------|
| 1 | 10% |
| 2 | 20% |
| 3 | 20% |
| 4 | 50% |
| 5 | 50% |
| 6 | 100% |

!!! warning "PRA Deviation from BCBS — Table 7 Unchanged from CRR"
    BCBS CRE20.28–29 reduced certain rated covered bond risk weights (CQS 2: 20%→15%,
    CQS 4: 50%→25%, CQS 5: 50%→35%, CQS 6: 100%→50%). The PRA **did not** adopt these
    reductions. PRA PS1/26 Art. 129(4) Table 7 is **identical** to CRR Table 6A.

> **Details:** See [Covered Bond Exposures (Art. 129) specification](../../specifications/basel31/sa-risk-weights.md#covered-bond-exposures-art-129) for the full Table 7 spec, the BCBS deviation rationale, and code-status notes.

## Risk Weights — Unrated (Art. 129(5))

For covered bonds without an ECAI assessment, the risk weight is **derived from the
issuing institution's senior-unsecured risk weight**:

| Institution Senior-Unsecured RW | Covered Bond RW | Sub-paragraph | Source |
|---------------------------------|------------------|--------------|--------|
| 20% | 10% | (a) | Inherited from CRR |
| **30%** | **15%** | (aa) | **New — ECRA CQS 2 entry** |
| **40%** | **20%** | (ab) | **New — SCRA Grade A entry** |
| 50% | 25% | (b) | ↓ from CRR 20% |
| **75%** | **35%** | (ba) | **New — SCRA Grade B entry** |
| 100% | 50% | (c) | Inherited from CRR |
| 150% | 100% | (d) | Inherited from CRR |

The Basel 3.1 expansion adds three new entries — (aa), (ab), and (ba) — to capture
risk weights produced by the new ECRA Art. 120 Table 3 (CQS 2 = 30%) and the SCRA
Art. 121 institution grades (Grade A enhanced 30% / Grade A 40% / Grade B 75%). CRR
had only the 4-row table (a)/(b)/(c)/(d).

The institution senior-unsecured RW is determined under **Art. 120 (ECRA)** for
rated banks or **Art. 121 (SCRA)** for unrated banks. If the issuing institution is
**itself unrated** under CRR, the sovereign-derived approach (Art. 121, Table 5)
provides the institution RW which then maps via Art. 129(5).

## Due Diligence CQS Step-Up — Art. 129(4A)

Basel 3.1 Art. 129(4A) requires firms to conduct **due diligence on the ECAI rating**
of every rated covered bond:

> *An institution shall conduct due diligence to ensure that the external credit
> assessments appropriately and prudently reflect the creditworthiness of the
> eligible covered bonds to which the institution is exposed. If the due diligence
> analysis reflects higher risk characteristics than that implied by the credit
> quality step of the exposure, the institution shall assign a risk weight associated
> with a credit quality step that is at least one step higher than the risk weight
> determined by the external credit assessment.*

| Source CQS | Table 7 RW | Stepped-Up CQS | Stepped-Up RW | Change |
|------------|-----------|----------------|----------------|--------|
| CQS 1 | 10% | CQS 2 | 20% | +10pp |
| CQS 2 | 20% | CQS 3 | 20% | 0pp (Table 7 plateau) |
| CQS 3 | 20% | CQS 4 | 50% | +30pp |
| CQS 4 | 50% | CQS 5 | 50% | 0pp (Table 7 plateau) |
| CQS 5 | 50% | CQS 6 | 100% | +50pp |
| CQS 6 | 100% | — | 100% | Capped (already bottom) |

!!! info "Plateau transitions still mandatory"
    CQS 2→3 and CQS 4→5 produce no numerical RW change because Table 7 assigns
    identical weights to those adjacent steps. The CQS reassignment is still required
    under Art. 129(4A) — relevant for any downstream process that keys off CQS rather
    than RW (e.g. disclosure templates, internal limit frameworks).

The Art. 129(4A) step-up applies parallel to Art. 120(4) (rated institutions) and
Art. 122(4) (rated corporates). All three share identical drafting; CRR has no
equivalent provision for any of the three classes.

!!! warning "Implementation — Art. 110A Pathway"
    The calculator does not yet implement a dedicated Art. 129(4A) branch. Firms
    currently route Art. 129(4A) findings through the Art. 110A
    `due_diligence_override_rw` input on the covered-bond loan or contingent — set
    to the next-CQS-band weight (e.g. CQS 3 → 50% to reflect a stepped-up CQS 4
    treatment) and the SA calculator will apply it as a directional floor. The output records the application via
    `due_diligence_override_applied`. See [B31 SA Risk Weights — Art. 129(4A)](../../specifications/basel31/sa-risk-weights.md#covered-bond-due-diligence-cqs-step-up-art-1294a).

## CRR vs Basel 3.1 — Key Differences

| Aspect | CRR (until 31 Dec 2026) | Basel 3.1 (from 1 Jan 2027) |
|--------|-------------------------|-----------------------------|
| Rated table (Table 6A / 7) | CQS 1–6: 10/20/20/50/50/100 | **Identical** — PRA did not adopt BCBS reductions |
| Unrated derivation | 4-row table (20%/50%/100%/150% institution → 10%/20%/50%/100%) | **7-row table** with new (aa)/(ab)/(ba) entries for ECRA CQS 2, SCRA Grade A, SCRA Grade B |
| Cover-pool concentration carve-outs | Same — 20% CQS 2 sovereign-type, 15% CQS 1/2 institution | Unchanged |
| Pre-2007 legacy treatment | Available | Continued via Art. 129(6) |
| DD step-up obligation | None | **Art. 129(4A) — at least one CQS higher if DD reveals higher risk** |
| Eligibility list | Same | Sub-paragraph (e) blanked; otherwise identical |

> **Details:** See [Key Differences — Covered Bonds](../../framework-comparison/key-differences.md#covered-bonds-art-129) for the full CRR vs Basel 3.1 comparison.

## Covered Bonds Issued by the Reporting Institution

A bank investing in **its own** covered bonds (or those of a connected institution)
generally cannot use Art. 129 preferential treatment — the dual-recourse rationale
fails when bondholder = issuer. Such positions are netted out at the consolidation
boundary or treated as a deduction from own funds.

## Covered Bonds Held as Cover-Pool Eligible Collateral

Where a CRM provider holds a covered bond as **financial collateral**, the bond
itself can be eligible collateral under the Financial Collateral Comprehensive
Method, with haircuts driven by its CQS-mapped institution debt category, not by
the Art. 129 preferential RW. See [Credit Risk Mitigation](../methodology/crm.md)
for haircut tables.

## Calculation Examples

### Example 1 — Rated Covered Bond, CQS 2

**Exposure:**

- £30,000,000 holding in a UK building society's residential mortgage covered bond
- Bond rated AA– → CQS 2

**Calculation:**

```
RW = 20% (Table 7, CQS 2)
RWA = 30,000,000 × 20% = 6,000,000
```

For comparison, a senior-unsecured exposure to the same building society at CQS 2
(institution Table 3 ECRA) would receive 30% under PRA PS1/26 — the covered bond
saves 10pp of RW.

### Example 2 — Unrated Covered Bond, ECRA CQS 2 Issuer

**Exposure:**

- £15,000,000 holding in an unrated covered bond
- Issuing institution is ECRA-rated CQS 2 → senior-unsecured RW = 30% (PRA PS1/26
  Art. 120 Table 3)

**Calculation:**

```
Institution senior-unsecured RW = 30% → Art. 129(5)(aa) → covered bond RW = 15%
RWA = 15,000,000 × 15% = 2,250,000
```

This entry did not exist under CRR — under CRR, the issuer would have been at 50%
institution RW (CRR Table 3), giving a 20% covered-bond RW (CRR Art. 129(5)(b))
and £3,000,000 of RWA.

### Example 3 — Unrated Covered Bond, SCRA Grade A Issuer

**Exposure:**

- £20,000,000 holding in an unrated covered bond
- Issuing institution is SCRA Grade A (unrated) → senior-unsecured RW = 40% (PRA
  PS1/26 Art. 121)

**Calculation:**

```
Institution senior-unsecured RW = 40% → Art. 129(5)(ab) → covered bond RW = 20%
RWA = 20,000,000 × 20% = 4,000,000
```

### Example 4 — DD Step-Up

**Exposure:**

- £50,000,000 covered bond at CQS 1 (Table 7 RW = 10%)
- Firm DD finds the cover pool's geographic concentration exceeds the firm's risk
  appetite — assigns DD CQS 2 (one step higher)

**Calculation:**

```
Default Table 7 RW = 10%
After Art. 129(4A) step-up: CQS 2 → RW = 20%
RWA = 50,000,000 × 20% = 10,000,000  (vs 5,000,000 without step-up)
```

Implementation: set `due_diligence_override_rw = 0.20` on the covered-bond loan or
contingent, and the SA calculator applies the 20% as a directional floor. Only the
loan and contingent tables accept the field: a facility's undrawn-headroom row, SA-CCR
and SFT rows, and `equity_exposures` holdings cannot carry it, so an override meant for
them has no effect (see
[B31 SA Risk Weights — Due Diligence](../../specifications/basel31/sa-risk-weights.md#due-diligence-obligation-art-110a)).

### Example 5 — Cover-Pool Concentration Breach

**Scenario:**

- Cover pool holds £100,000,000 of CQS 2 sovereign-type assets against £400,000,000
  of nominal outstanding covered bonds
- Concentration: 100/400 = 25%

**Outcome:**

The 20% Art. 129(1)(b)(vii) limit is **breached**. The bond therefore fails Art. 129
eligibility entirely and reverts to **standard institution treatment** under
Art. 120/121 — 30% (ECRA CQS 2) or the SCRA grade weight, not 20% under Table 7.
The eligibility test is **all-or-nothing**; partial recognition of the bond at a
blended weight is not permitted.

## Input Schema Summary

| Field | Type | Description |
|-------|------|-------------|
| `is_eligible_covered_bond` | bool | Flags the exposure for Art. 129 treatment; `False` reverts to issuer institution RW |
| `external_cqs` | int (1–6) or NULL | Drives the Table 7 lookup when not NULL |
| `issuer_institution_rw` | Decimal | Senior-unsecured RW of the issuing institution — drives Art. 129(5) derivation when `external_cqs` is NULL |
| `due_diligence_override_rw` | Decimal | Art. 110A directional floor used to express Art. 129(4A) step-up findings — loan and contingent tables only (the facility schema has no such field) |
| `is_pre_2007_covered_bond` | bool | Triggers the Art. 129(6) legacy carve-out from cover-pool composition rules |

## Regulatory References

| Topic | PRA PS1/26 / CRR | BCBS CRE |
|-------|------------------|----------|
| Eligibility — cover pool composition | Art. 129(1)(a)–(g) | CRE20.27 |
| CQS 2 sovereign-type 20% concentration carve-out | Art. 129(1)(b)(vii) | CRE20.27 |
| CQS 1/2 institution 15% concentration carve-out | Art. 129(1)(c) | CRE20.27 |
| Payment-transmission exclusion from limits | Art. 129(1A) | CRE20.27 |
| Eligible cover-pool collateral protection rule | Art. 129(2) | CRE20.27 |
| RE valuation requirements | Art. 129(3) | CRE20.27 |
| Rated risk weights (Table 7) | Art. 129(4) | CRE20.28 (BCBS reductions not adopted) |
| Due diligence CQS step-up | **Art. 129(4A) — Basel 3.1 only** | — |
| Unrated derivation table | Art. 129(5)(a)–(d), with new (aa)/(ab)/(ba) | CRE20.29 |
| Pre-2007 legacy carve-out | Art. 129(6) | CRE20.27 footnote |
| Investor portfolio disclosure (semi-annual) | Art. 129(7) | CRE20.27 |
| Issuer-level due-diligence (general SA) | Art. 110A | CRE20.7 |

## Next Steps

- [Institution Exposures](institution.md) — covered bond issuer treatment
- [Real Estate Exposures](secured-by-real-estate.md) — for RE-backed cover pools
- [CIU Exposures](cius.md) — funds investing in covered bonds
- [Standardised Approach](../methodology/standardised-approach.md)
- [SA Risk Weights specification (Basel 3.1)](../../specifications/basel31/sa-risk-weights.md#covered-bond-exposures-art-129)
