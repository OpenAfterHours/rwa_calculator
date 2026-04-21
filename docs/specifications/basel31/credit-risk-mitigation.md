# Credit Risk Mitigation Specification

Basel 3.1 CRM changes: revised 5-band haircut tables, increased equity and gold haircuts,
and IRB parameter substitution replacing double default.

**Regulatory Reference:** PRA PS1/26 Art. 191A–241, CRE22
**Test Group:** B31-D, B31-D7

---

## Requirements Status

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-8.1 | Revised 5-band maturity haircut tables (was 3-band) | P0 | Done |
| FR-8.2 | Increased equity haircuts: main index 20%, other 30% | P0 | Done |
| FR-8.3 | Increased gold haircut: 20% (was 15%) | P0 | Done |
| FR-8.4 | IRB parameter substitution for guarantors (B31-D7) | P0 | Done |
| FR-8.5 | Double default removal (replaced by parameter substitution) | P0 | Done |
| FR-8.6 | Art. 191A method taxonomy (FCM, PSM, LGD-AM) | P1 | Done |
| FR-8.7 | Unfunded credit protection transitional (Rule 4.11) | P2 | Not Implemented |
| FR-8.8 | Art. 123B currency mismatch 1.5x multiplier (retail/RRE) | P1 | Partial (flag only; auto-detection and 90% hedge test not implemented) |

---

## Overview

Basel 3.1 introduces more granular collateral haircut tables (5 maturity bands instead of 3),
increases haircuts for equity and gold collateral, and replaces the double default treatment
with parameter substitution for IRB-rated guarantors.

### Key Changes from CRR

| Feature | CRR | Basel 3.1 | Reference |
|---------|-----|-----------|-----------|
| Maturity bands | 3 (0–1y, 1–5y, 5y+) | **5** (0–1y, 1–3y, 3–5y, 5–10y, 10y+) | Art. 224 |
| Equity haircut (main index) | 15% | **20%** | Art. 224 Table 3 |
| Equity haircut (other listed) | 25% | **30%** | Art. 224 Table 3 |
| Gold haircut | 15% | **20%** | Art. 224 Table 3 |
| Double default | Available (Art. 202–203) | **Removed** | — |
| IRB guarantor treatment | Double default / SA-RW substitution | **PD parameter substitution** | New |
| Method names | Unnamed | **FCM / PSM / LGD-AM** (Art. 191A) | Art. 191A |

---

## Financial Collateral Haircuts (Art. 224)

### Cash and Gold

| Collateral Type | CRR | Basel 3.1 | Change |
|----------------|-----|-----------|--------|
| Cash / deposit / CLN | 0% | 0% | Unchanged |
| Gold | 15% | **20%** | +5pp |

### Government Bond Haircuts (5-Band)

**PRA PS1/26 Art. 224 Table 1 — 10-day liquidation period** (verified against
ps126app1.pdf p.203, 17 Apr 2026; "entity type (b) of paragraph 1 of Article 197"
— sovereigns / central banks / certain PSEs and MDBs treated as sovereign):

| CQS | 0–1y | 1–3y | 3–5y | 5–10y | 10y+ |
|-----|------|------|------|-------|------|
| CQS 1 | 0.5% | 2% | 2% | 4% | 4% |
| CQS 2–3 | 1% | 3% | 3% | 6% | **6%** |
| CQS 4 | 15% | 15% | 15% | 15% | 15% |

CQS 5–6 government bonds are **ineligible** as financial collateral (Art. 197(1)(b)).

!!! note "Change log — Art. 224 Table 1 sovereign corrections (17 Apr 2026)"
    Earlier drafts of this spec showed 4% at the CQS 2–3 / 3–5y cell and 12% at
    the CQS 2–3 / 10y+ cell. The PRA Table 1 values are **3%** and **6%**
    respectively — CQS 2–3 sovereigns cap out at 6% even for the longest
    residual-maturity band. The 5-band split is not a penal re-scale for
    well-rated sovereigns.

### Corporate and Institution Bond Haircuts (5-Band)

**PRA PS1/26 Art. 224 Table 1 — 10-day liquidation period** (verified against
ps126app1.pdf p.203; "entity types (c) and (d) of paragraph 1 of Article 197" —
institutions / corporates):

| CQS | 0–1y | 1–3y | 3–5y | 5–10y | 10y+ |
|-----|------|------|------|-------|------|
| CQS 1 | 1% | 3% | 4% | 6% | 12% |
| CQS 2–3 | 2% | 4% | 6% | **12%** | **20%** |

CQS 4–6 corporate/institution bonds are **ineligible** (Art. 197(1)(d)).

!!! note "Change log — Art. 224 Table 1 corporate corrections (17 Apr 2026)"
    Earlier drafts of this spec understated the CQS 2–3 haircuts for long residual
    maturities (showing 15% flat at 5–10y and 10y+). PRA Table 1 applies
    **12%** at 5–10y and **20%** at 10y+ for CQS 2–3 corporate/institution debt.
    CQS 1 values have also been brought into line with Table 1 (1 / 3 / 4 / 6 / 12).

### Equity Haircuts

| Equity Type | CRR | Basel 3.1 | Change |
|------------|-----|-----------|--------|
| Main index | 15% | **20%** | +5pp |
| Other listed | 25% | **30%** | +5pp |

### FX Mismatch Haircut

Unchanged: **8%** (10-day base liquidation period).

Scaled for other liquidation periods via:

```
H_fx_scaled = H_fx x sqrt(T_m / 10)
```

| Period | H_fx |
|--------|------|
| 5-day (repo) | 5.66% |
| 10-day (capital market) | 8.00% |
| 20-day (secured lending) | 11.31% |

---

## Maturity Band Classification

The 5-band boundaries use inclusive upper thresholds:

| Band | Residual Maturity |
|------|-------------------|
| 0–1y | ≤ 1.0 year |
| 1–3y | > 1.0 and ≤ 3.0 years |
| 3–5y | > 3.0 and ≤ 5.0 years |
| 5–10y | > 5.0 and ≤ 10.0 years |
| 10y+ | > 10.0 years |

Null maturity defaults to **10y+** (conservative) under Basel 3.1, vs 5y+ under CRR.

---

## Volatility Scaling (Art. 226)

PRA PS1/26 restructures CRR Art. 226 into two numbered paragraphs: paragraph 1 retains
the non-daily revaluation formula (from CRR Art. 226); paragraph 2 absorbs the liquidation
period scaling formula previously in CRR Art. 225(2)(c), since the own-estimates approach
(Art. 225) is removed under Basel 3.1.

### Art. 226(1) — Non-Daily Revaluation Adjustment

When collateral is revalued less frequently than daily, haircuts must be scaled up using
the square-root-of-time formula:

```
H = H_m × sqrt((N_R + T_m − 1) / T_m)
```

| Variable | Definition |
|----------|-----------|
| H | Volatility adjustment to be applied |
| H_m | Volatility adjustment where there is daily revaluation |
| N_R | Actual number of business days between revaluations |
| T_m | Liquidation period for the transaction type (business days) |

When revaluation is daily (N_R = 1), the formula reduces to H = H_m (no adjustment).

!!! warning "Not Yet Implemented"
    Art. 226(1) non-daily revaluation adjustment is not implemented. No
    `revaluation_frequency_days` input field exists in the collateral schema. Haircuts are
    understated when collateral is not marked-to-market daily. See IMPLEMENTATION_PLAN.md
    P1.101.

### Art. 226(2) — Liquidation Period Scaling

When the applicable liquidation period differs from the haircut table's reference period,
scale using:

```
H_m = H_n × sqrt(T_m / T_n)
```

| Variable | Definition |
|----------|-----------|
| T_m | Liquidation period for the transaction type |
| T_n | Liquidation period under Art. 224(2)(a)–(c) (the table reference period) |
| H_m | Volatility adjustment based on T_m |
| H_n | Volatility adjustment based on T_n |

### Liquidation Periods (Art. 224(2))

| Transaction Type | Minimum Holding Period (T_m) |
|-----------------|------------------------------|
| Repo-style / SFT | 5 business days |
| Other capital market transactions | 10 business days |
| Secured lending | 20 business days |

Art. 224 Table 3 provides haircuts at the 10-day holding period. Apply Art. 226(2) to
scale to 5-day (repos) or 20-day (secured lending) periods. Apply Art. 226(1) additionally
when revaluation is not daily.

### Key Change from CRR

| Aspect | CRR | Basel 3.1 |
|--------|-----|-----------|
| Non-daily revaluation formula | Art. 226 (single article) | Art. 226(1) — **unchanged** |
| Liquidation period scaling | Art. 225(2)(c) | Art. 226(2) — **moved** |
| Own-estimates approach | Art. 225 (permitted) | Art. 225 **removed** |
| Art. 226 scope | Supervisory + own-estimates | Supervisory only |

---

## F-IRB LGDS Values (Art. 230, Art. 161)

For F-IRB exposures, supervisory LGD values for secured exposures:

| Collateral Type | CRR LGDS | Basel 3.1 LGDS | Reference |
|----------------|----------|----------------|-----------|
| Financial / cash | 0% | 0% | — |
| Receivables | 35% | **20%** | CRE32.9 |
| Residential RE | 35% | **20%** | CRE32.10 |
| Commercial RE | 35% | **20%** | CRE32.11 |
| Other physical | 40% | **25%** | CRE32.12 |

See [F-IRB Specification](firb-calculation.md) for full LGD details including unsecured
values and the blended LGD formula.

---

## IRB Parameter Substitution (B31-D7)

### Overview

Basel 3.1 replaces the CRR double default treatment with **PD parameter substitution** for
IRB-rated guarantors. This is a new mechanism where the guarantor's PD is substituted into
the IRB capital formula for the guaranteed portion.

### Trigger Conditions

Parameter substitution activates when **all** of the following hold:

1. Framework is Basel 3.1
2. Guarantor has an **internal PD** (rated under the firm's IRB model)
3. Guarantee is eligible per Art. 213–217

If the guarantor has only an external rating (SA guarantor), the standard SA risk weight
substitution applies regardless of framework.

### Calculation Method

For the guaranteed (covered) portion of the exposure Art. 236(1)(a) applies the
IRB capital formula using the **guarantor's** PD together with an LGD drawn from
one of two options (ps126app1.pdf p.215–216, 17 Apr 2026):

```
guarantor_rw = IRB_formula(PD=guarantor_pd_floored, LGD=LGD_covered, MA=MA_original, scaling=1.0)
```

Where:

- `guarantor_pd_floored` = the PD that would be assigned to a comparable direct exposure
  to the protection provider, after the Art. 160 PD floor and the Art. 160(4) "no better
  than direct" uplift.
- `LGD_covered` is one of:
    1. **Borrower LGD, unprotected** — the LGD the exposure would carry if no unfunded
       credit protection existed, after the Art. 161(5) input floor and the Art. 161(6)
       uplift; or
    2. **Guarantor F-IRB LGD** — the LGD that would apply to the guarantee if it were a
       direct exposure to the protection provider under the F-IRB Approach, taking
       seniority into account (Art. 161(1): 40% senior non-FSE, 45% senior FSE, 75%
       subordinated, etc.), with the same Art. 160(4) / 161(6) uplifts.
- Scaling factor = 1.0 (no 1.06).

!!! note "Change log — Art. 236 LGD source clarified (17 Apr 2026)"
    Earlier drafts of this spec stated `LGD = 40% (F-IRB senior unsecured non-FSE)`
    as a fixed value. Art. 236(1)(a) does not fix LGD at 40% — the institution may
    either retain the borrower's unprotected LGD or substitute the guarantor's F-IRB
    LGD. In the common case of a non-FSE senior guarantor the substituted value is
    40% under Art. 161(1)(aa), which is why the simplification was previously shown,
    but for FSE guarantors the substituted LGD is 45% and for subordinated guarantees
    it is 75%.

### Blended RWA

```
RWA = RWA_borrower x (unguaranteed / EAD) + guaranteed_portion x guarantor_rw x 12.5
```

Parameter substitution is only applied when **beneficial** (guarantor RW < borrower's
original IRB RW).

### Expected Loss Under Parameter Substitution

```
EL_blended = EL_original x (unguaranteed / EAD)
           + guarantor_pd_floored x LGD_covered x guaranteed_portion
```

`LGD_covered` is the same value used in the risk-weight calculation above
(Art. 236(1A)(b)) — either the unprotected borrower LGD or the substituted
guarantor F-IRB LGD.

### Audit Trail

The `guarantee_method_used` output column indicates the method applied:

| Value | Meaning |
|-------|---------|
| `PD_SUBSTITUTION` | IRB guarantor under Basel 3.1 |
| `SA_RW_SUBSTITUTION` | SA guarantor, or any guarantor under CRR |
| `NO_GUARANTEE` | No guarantee applied |

---

## CRM Method Taxonomy (Art. 191A)

Art. 191A replaces the old CRR Art. 108, introducing a formal four-part decision tree for
CRM method selection with explicit method names.

### Method Names

| Method | Acronym | Scope |
|--------|---------|-------|
| Financial Collateral Simple Method | FCSM | SA only: financial collateral (Art. 222) |
| Financial Collateral Comprehensive Method | FCCM | SA + IRB: financial collateral (Art. 223) |
| Foundation Collateral Method | FCM | F-IRB: financial and physical collateral (Art. 230) |
| Parameter Substitution Method | PSM | F-IRB / A-IRB: unfunded credit protection (Art. 236) |
| LGD Adjustment Method | LGD-AM | A-IRB: unfunded credit protection (Art. 183) |
| Risk-Weight Substitution Method | RWSM | SA / Slotting: unfunded credit protection (Art. 235) |

### Art. 191A Decision Tree

**Part 1 — Funded CRM with CCR exposure:**
CCR exposures use IMM / SFT VaR / FCCM / FCSM (SA only).

**Part 2 — Funded CRM without CCR (non-CCR exposures):**

1. On-balance sheet netting (Art. 219)
2. Financial collateral → FCSM (SA only, Art. 222) or FCCM (Art. 223)
3. Non-financial collateral → FCM (F-IRB, Art. 229-231) / LGD Modelling (A-IRB)
4. Life insurance / other funded CP → Other Funded Protection Method (Art. 232)

**Part 3 — Unfunded CRM:**

- SA / Slotting → Risk-Weight Substitution Method (Art. 235)
- F-IRB / A-IRB → Parameter Substitution Method (Art. 236)
- A-IRB (own estimates) → LGD Adjustment Method (Art. 183)

**Part 4 — Unfunded CP covered by funded CP:**
Where unfunded protection is itself collateralised, funded CRM is applied to the unfunded
protection first, then the adjusted unfunded protection is applied to the original exposure.

### Anti-Double-Counting and Consistency Rules

- **Para 2(d)**: Funded and unfunded CRM must not be recognised simultaneously on the same
  portion of an exposure (no double-counting).
- **Para 3**: An institution must use the same CRM method for the same type of unfunded
  credit protection across its portfolio (consistency requirement).

### Method Selection by Approach

| Approach | Funded Protection | Unfunded Protection |
|----------|-------------------|---------------------|
| SA | FCSM (Art. 222) or FCCM (Art. 223) | RWSM — SA-RW substitution (Art. 235) |
| F-IRB | FCM (Art. 230) or FCCM (Art. 223) | PSM — PD substitution for IRB guarantors, SA-RW for SA guarantors (Art. 236) |
| A-IRB | LGD modelling (Art. 169A/169B) or FCM/FCCM | LGD-AM (Art. 183) or PSM (Art. 236) |

---

## FCSM Under Basel 3.1 (Art. 222)

The Financial Collateral Simple Method is retained for SA exposures under Basel 3.1.
Paragraph references below verified against ps126app1.pdf pp.199–200 (17 Apr 2026).

### Art. 222(3) — 20% RW Floor

The risk weight of the collateralised portion is the RW that would apply to a
direct exposure to the collateral instrument, with a minimum **20%** floor
(Art. 222(3), second sub-paragraph), **except** as specified in paragraphs 4 and 6.

### Art. 222(4) — 0% / 10% Floor for SFTs (Art. 227 Criteria)

For **securities financing transactions** that meet the criteria in Art. 227, the
collateralised portion receives a **0%** risk weight where the counterparty is a
**core market participant**, and **10%** where the counterparty is not a core market
participant. This paragraph replaces the flat 20% floor for qualifying SFTs.

### Art. 222(6) — 0% Floor for Same-Currency Cash or 0%-RW Sovereign Debt

For **non-SFT transactions** where the exposure and the collateral are denominated
in the **same currency**, the floor drops to **0%** if either:

- **(a)** the collateral is cash on deposit (or a cash-assimilated instrument) with the lending institution, or
- **(b)** the collateral is central-government or central-bank debt that is eligible
  for a 0% SA risk weight, with its market value discounted by 20% (Art. 222(6)(b),
  with the extended definition of "central government / central bank debt" in
  Art. 222(7) covering certain RGLAs, MDBs, and international organisations).

!!! note "Change log — Art. 222 carve-outs clarified (17 Apr 2026)"
    Earlier drafts mixed up the two carve-outs. Paragraph **4** is the
    SFT-with-Art.227 rule (0% core market / 10% otherwise); paragraph **6** is
    the same-currency cash / 0%-RW sovereign carve-out for non-SFT transactions.
    There is no sub-point (d) in Art. 222(4); sub-points (a) and (b) sit under
    Art. 222(**6**).

### Art. 222 — No Maturity Mismatch

Under the FCSM, the collateral's residual maturity must be at least equal to the exposure's
residual maturity. The Art. 238 maturity mismatch adjustment does **not** apply to the
FCSM (Art. 239(1) excludes FCSM from the maturity-mismatch formula).

---

## FCCM E* Formula (Art. 223(5))

The Financial Collateral Comprehensive Method produces a net adjusted exposure value:

```
E* = max(0, E(1 + HE) - CVA(1 - HC - HFX))
```

| Variable | Definition |
|----------|-----------|
| E | Current exposure value |
| HE | Exposure volatility haircut (for SFTs where exposure is a debt security; HE = 0 for standard lending) |
| CVA | Current value of collateral received |
| HC | Collateral volatility haircut (Art. 224 5-band tables) |
| HFX | FX mismatch haircut (8% at 10-day; 0% if same currency) |

---

## Maturity Mismatch (Art. 237-239)

PS1/26 Section 5 (ps126app1.pdf pp.217–219) covers maturity mismatches across
**both funded and unfunded** credit protection. Article 238(1A) enumerates the
six CRM methods within scope; Article 237 sets the eligibility gates that
apply to all six; Article 239 sets the per-method valuation formula.

### Methods in Scope (Art. 238(1A))

The maturity-mismatch framework applies to credit protection recognised under
**any** of the following methods:

| Letter | Method | Type |
|--------|--------|------|
| (a) | On-balance sheet netting (Art. 219) | Funded |
| (b) | FCCM (excluding SFTs covered by a master netting agreement) | Funded |
| (c) | Foundation Collateral Method (Art. 230) | Funded |
| (d) | Other Funded Credit Protection Method (Art. 232) | Funded |
| (e) | Risk-Weight Substitution Method — SA / Slotting guarantees and CDS (Art. 235) | **Unfunded** |
| (f) | Parameter Substitution Method — F-IRB / A-IRB guarantees and CDS (Art. 236) | **Unfunded** |

!!! warning "FCSM and LGD-AM are out of scope"
    - **Financial Collateral Simple Method (FCSM)** — Art. 239(1) excludes
      FCSM entirely: where a maturity mismatch exists, the collateral
      ceases to be eligible funded credit protection (no GA / CVAM
      adjustment is permitted). Cross-reference: [Art. 222 — No Maturity
      Mismatch](#art-222-no-maturity-mismatch).
    - **LGD Adjustment Method (LGD-AM, Art. 183)** — A-IRB own-estimate of
      LGD is not listed in Art. 238(1A). Maturity mismatches on unfunded
      protection recognised through own-LGD estimates are captured within
      the institution's own LGD model rather than via the Art. 239 GA
      formula. This is the only treatment of unfunded protection that
      sits *outside* the Art. 237–239 perimeter.

### Art. 237 — Eligibility Gates

Two cumulative tests determine whether the protection is eligible at all when
a mismatch exists. Failing either makes the protection ineligible — no
adjustment formula is applied; the protection is simply ignored.

**Art. 237(1) — Combined residual-maturity and shorter-than-exposure test.**
A maturity mismatch arises when the residual maturity of the credit protection
is less than that of the protected exposure. Where the protection has
**residual maturity < 3 months *and*** the protection maturity is less than
the underlying exposure maturity, the institution shall not use that
protection as eligible credit protection.

**Art. 237(2) — Disqualifying conditions (either limb).** Where there is a
maturity mismatch, the credit protection is also ineligible if either:

- **(a)** the original maturity of the protection is less than one year; or
- **(b)** the exposure is a short-term exposure subject to a one-day floor on
  the maturity value M under Credit Risk: Internal Ratings Based Approach
  (CRR) Part Article 162(3) (e.g. certain repo / SFT / short-term
  trade-finance IRB exposures with M floored at one day).

These eligibility gates apply uniformly to funded **and** unfunded protection
under the six in-scope methods — a guarantee or CDS with original maturity
< 1 year is ineligible for an exposure with residual maturity > 1 year, just
as a financial-collateral instrument with the same characteristics is.

### Art. 238 — Measuring Protection Maturity

Effective protection maturity is the **time to the earliest date at which the
protection may terminate** (or be terminated). Specific rules:

- **On-balance sheet netting** — earlier of the netting agreement termination
  date and the date the deposit can be withdrawn / loan called (Art. 238(1)).
- **Protection-seller termination option** — maturity is the earliest exercise
  date of that option (Art. 238(2), first sentence).
- **Protection-buyer termination option** — maturity is the earliest exercise
  date **only if** the contract contained a positive incentive at origination
  for the institution to call before contractual maturity; otherwise the
  buyer option is ignored for maturity measurement (Art. 238(2)(a)–(b)).
- **Credit-derivative grace period** — protection maturity is reduced by the
  length of any grace period before failure-to-pay default, where the credit
  derivative is not prevented from terminating before the grace period
  expires (Art. 238(3)).

The effective maturity of the **underlying exposure** is the longest possible
remaining time before the obligor is scheduled to perform, capped at **5
years** (Art. 238(1)).

### Art. 239 — Adjustment Formulas (Funded vs Unfunded)

Two parallel formulas — Art. 239(2) for funded methods (a)–(d) and
Art. 239(3) for unfunded methods (e)–(f). The multiplier
`(t − 0.25) / (T − 0.25)` is identical between the two; only the protection
input differs.

**Art. 239(2) — Funded credit protection (methods (a)–(d)):**

```
CVAM = CVA x (t - 0.25) / (T - 0.25)
```

| Variable | Definition |
|----------|-----------|
| CVA | Volatility-adjusted collateral value per Art. 223(2), or the exposure amount if lower |
| t | Years to credit-protection maturity per Art. 238, capped at T |
| T | Years to exposure maturity per Art. 238, capped at 5 |

For **FCCM**, `CVAM` substitutes for `CVA` in the E* formula at Art. 223(5).
For **on-balance sheet netting**, `CVAM` flows through Art. 219(3), where
"collateral" is read as the netted loans/deposits.

**Art. 239(3) — Unfunded credit protection (methods (e)–(f)):**

```
GA = G* x (t - 0.25) / (T - 0.25)
```

| Variable | Definition |
|----------|-----------|
| G* | Protection amount adjusted for any currency mismatch (Art. 233) |
| t | Years to credit-protection maturity per Art. 238, capped at T |
| T | Years to exposure maturity per Art. 238, capped at 5 |

`GA` is then used as the credit-protection amount input to the **RWSM**
(Art. 235, SA / slotting guarantees and CDS) or the **PSM** (Art. 236,
F-IRB / A-IRB guarantees and CDS). The same GA formula governs guarantee
and credit-derivative maturity mismatches under both SA and IRB — the
distinction between RWSM and PSM is only in *how* the resulting `GA` is
consumed (RW substitution vs PD/LGD parameter substitution), not in the
maturity-mismatch adjustment itself.

When **t ≥ T**, no maturity-mismatch adjustment is needed — the multiplier
collapses to 1 and `GA = G*` / `CVAM = CVA`.

!!! info "Heading scope correction (21 April 2026)"
    Earlier drafts of this spec presented the maturity-mismatch formula
    under the heading "Art. 237–238" with only the unfunded `GA` formula
    visible, which left ambiguity about whether the framework applied to
    guarantee / CDS mismatches at all. The formulas themselves sit in
    **Art. 239**: paragraph 2 (`CVAM`, funded methods (a)–(d)) and
    paragraph 3 (`GA`, unfunded methods (e)–(f)). Art. 237 sets the
    eligibility gates that govern *all* six methods listed in
    Art. 238(1A). Resolves D2.39.

---

## Currency Mismatch 1.5x Multiplier (Art. 123B)

### Overview

PS1/26 introduces a new **1.5x risk-weight multiplier** (Art. 123B of the Credit Risk:
Standardised Approach (CRR) Part) for unhedged retail and residential real estate exposures
where the lending currency differs from the currency of the obligor's source of income. This
captures FX risk on household and SME borrowers that is not otherwise reflected in the
exposure's base risk weight.

### Scope

Applies to exposures assigned to the SA exposure classes at points (h) (retail) and (i)
(residential real estate) of Art. 112(1) where **either**:

- the obligor is a natural person and the lending currency differs from the currency of the
  obligor's source of income (Art. 123B(1)(a)); **or**
- the obligor is a special-purpose entity created to finance or operate immovable property,
  a natural-person guarantor receives the economic benefit of the residential real estate,
  and the lending currency differs from the currency of that guarantor's source of income
  (Art. 123B(1)(b)).

"Source of income" includes salary, rental income and remittances but **excludes** proceeds
from asset sales or institution recourse actions (Art. 123B(4)(a)).

### Multiplier and Cap

```
RW_adjusted = min(1.5 x RW_base, 150%)
```

where `RW_base` is the risk weight calculated under Art. 123 (retail) or Art. 124F-124L
(real estate), as applicable. The multiplier is applied **after** any other risk-weight
overrides (e.g. regulatory-RE loan-splitting, ADC floor, charge-priority adjustments), and
is capped so the final risk weight does not exceed 150%.

### Hedge Exemption (Art. 123B(2))

An exposure is **hedged** (and therefore outside Art. 123B scope) only if:

1. The obligor — or, for the SPE case, the obligor and/or guarantor — has a **natural hedge
   or financial hedge** against the FX risk arising from the currency mismatch; and
2. Those hedges together cover **at least 90% of any instalment** for the exposure.

For natural hedges comprising assets held by the obligor, the hedge value is determined by
applying volatility adjustments assuming the assets are collateral against an exposure
without currency mismatch, using a 5-day liquidation period under Art. 223(2) and
Art. 224-227 (Art. 123B(2)(b)).

**Revolving facilities** (Art. 123B(2A)): instalment amount is the greater of (a) the
contractual minimum, (b) the fully-drawn contractual amount; for multi-currency facilities
the instalment is calculated ignoring current drawings and assuming full draw in a currency
which both mismatches the income currency and for which hedges cover less than 90%
(conservative drawing assumption).

### Fallback Rule (Art. 123B(3))

Where an institution is unable to identify which exposures have a currency mismatch and the
exposure was incurred **prior to 1 January 2027**, the 1.5x multiplier must be applied to
**all** unhedged retail and residential real estate exposures in scope of points (h)/(i) of
Art. 112(1) — **except** where the lending currency equals the domestic currency of the
obligor's country of residence **or** country of employment — subject to the 150% cap.

### Reporting

The multiplier-affected exposures appear in:

- **OF 07.00** row 0380 — "Retail and real estate exposures subject to the currency
  mismatch multiplier (Art. 112(1)(h)/(i))".
- **UKB CR5** — reported against the base (pre-multiplier) risk weight, but the RWEA column
  reflects the multiplier (per Annex XX CR5 instructions).

### Implementation Status

!!! warning "Implementation Status"
    Engine support for Art. 123B is tracked in IMPLEMENTATION_PLAN.md. The calculator
    currently requires an explicit `currency_mismatch_unhedged` input flag; automatic
    identification (lending-currency vs income-currency comparison) and the Art. 123B(2)
    90%-coverage hedge test are not performed. The Art. 123B(3) pre-2027 fallback is
    likewise not implemented — portfolios with unknown mismatch status will not receive the
    conservative blanket multiplier.

### References

- PS1/26 Appendix 1, Credit Risk: Standardised Approach (CRR) Part, **Article 123B** —
  Retail exposures and residential real estate exposures with a currency mismatch
  (Annex D, pages 49–50 of ps126app1.pdf).
- BCBS CRE20.88 (currency mismatch multiplier for retail and RRE exposures — underlying
  methodology).

---

## Unfunded Credit Protection Transitional (Rule 4.11)

Pre-1 January 2027 unfunded credit protection contracts may continue to use CRR eligibility
criteria until **30 June 2028**, even if they do not meet the stricter Basel 3.1 requirements
(e.g., the new "or changeable" criterion in Art. 213).

!!! warning "Not Yet Implemented"
    Rule 4.11 transitional logic is not implemented. The calculator does not perform
    Art. 213 eligibility validation, so the "or change" criterion is not enforced under
    either framework. Implementing this requires a `protection_inception_date` input field
    and date-gated eligibility logic in the CRM processor.
    See [CRR CRM spec](../crr/credit-risk-mitigation.md#unfunded-credit-protection-transitional-rule-411)
    for the full regulatory description and IMPLEMENTATION_PLAN.md item P1.10.

---

## Key Scenarios

| Scenario ID | Description | Key Feature |
|-------------|-------------|-------------|
| B31-D1 | Government bond CQS 1, 10-day — 5-band haircut | Haircut from 5-band table |
| B31-D2 | Equity collateral (main index) — 20% haircut | Increased from CRR 15% |
| B31-D3 | Cash collateral — 0% | Unchanged |
| B31-D4 | Guarantee with SA guarantor — SA-RW substitution | SA method, not PD substitution |
| B31-D5 | Maturity mismatch — adjustment factor | Maturity mismatch formula |
| B31-D6 | FX mismatch — 8% haircut | Unchanged from CRR |
| B31-D7 | IRB guarantor — PD parameter substitution | New B31 method |
| B31-D7b | IRB guarantor — partial guarantee blending | Blended RWA calculation |
| B31-D7c | SA guarantor under B31 — falls back to SA-RW substitution | Not PD substitution |
| B31-D7d | IRB guarantor — guarantee not beneficial (guarantor RW > borrower RW) | No substitution applied |
| B31-D7e | CRR comparison — always SA-RW substitution | CRR has no PD substitution |

## Acceptance Tests

| Group | Scenarios | Tests | Pass Rate |
|-------|-----------|-------|-----------|
| B31-D: Credit Risk Mitigation | D1–D6 | 15 | 100% (15/15) |
| B31-D7: Parameter Substitution | D7, D7b–D7e | 5 | 100% (5/5) |
