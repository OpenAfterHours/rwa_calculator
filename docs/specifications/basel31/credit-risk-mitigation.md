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
| FR-8.9 | Art. 232(3) life insurance derivation table with B31 input tiers (30% / 65% / 135%) | P1 | Done |

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
| Life insurance derivation (Art. 232(3)) | 4 input tiers (20/50/100/150) | **7 input tiers** — adds 30%, 65%, 135% | Art. 232(3) |

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
| LGD Adjustment Method | LGD-AM | A-IRB **with own-LGD estimate permission** for the exposure class: unfunded credit protection (Art. 183) |
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
- F-IRB → Parameter Substitution Method (Art. 236) only
- A-IRB without own-LGD permission for the class → Parameter Substitution Method (Art. 236) only
- A-IRB **with own-LGD permission** for the class → LGD Adjustment Method (Art. 183) **or** Parameter
  Substitution Method (Art. 236). Selection is a firm-level methodology choice subject to the Art.
  191A(3) consistency rule (same method across the same type of unfunded protection).

**Part 4 — Unfunded CP covered by funded CP:**
Where unfunded protection is itself collateralised, funded CRM is applied to the unfunded
protection first, then the adjusted unfunded protection is applied to the original exposure.

### Anti-Double-Counting and Consistency Rules

- **Para 2(d)**: Funded and unfunded CRM must not be recognised simultaneously on the same
  portion of an exposure (no double-counting).
- **Para 3**: An institution must use the same CRM method for the same type of unfunded
  credit protection across its portfolio (consistency requirement).
- **AIRB own-LGD anti-double-counting (Art. 169A)**: Where collateral has been used to
  construct the firm's own LGD model, that collateral must not also contribute supervisory
  CRM benefit to non-AIRB exposures of the same counterparty. The pipeline supports this via
  the `is_airb_model_collateral` flag on the collateral table (default `False`):
  - When `True`, the collateral is allocated only to AIRB-pool exposures (rows where the
    modelled LGD is preserved). Non-AIRB exposures receive zero. Direct allocation onto a
    non-AIRB exposure raises a CRM006 data-quality warning.
  - Even when `False`, AIRB-pool exposures are excluded from the **pro-rata base** at
    facility / counterparty level, so unflagged collateral routes entirely to non-AIRB rows
    rather than being "wasted" on AIRB rows whose LGD ignores it.

### Method Selection by Approach

| Approach | Funded Protection | Unfunded Protection |
|----------|-------------------|---------------------|
| SA | FCSM (Art. 222) or FCCM (Art. 223) | RWSM — SA-RW substitution (Art. 235) |
| F-IRB | FCM (Art. 230) or FCCM (Art. 223) | PSM — PD substitution for IRB guarantors, SA-RW for SA guarantors (Art. 236) |
| A-IRB (own-LGD permission **not** held for class) | LGD modelling unavailable — use FCM / FCCM | PSM (Art. 236) — LGD-AM not available |
| A-IRB (own-LGD permission held for class) | LGD modelling (Art. 169A/169B) or FCM / FCCM | LGD-AM (Art. 183) **or** PSM (Art. 236) — firm methodology choice under Art. 191A(3) |

!!! warning "LGD-AM is not universally available to A-IRB firms"
    "A-IRB" is not a single blanket permission. Under PS1/26 Art. 143(2A)(c) / Art.
    143(2B)(b)(iii), a firm specifies in its IRB permission which exposure classes,
    exposure subclasses or types of exposure it proposes to run under A-IRB — and
    A-IRB permission for one class does not extend to another. A firm holding A-IRB
    permission for one class (e.g. retail mortgages) but only F-IRB for another
    (e.g. general corporates) must use **PSM (Art. 236)** for the F-IRB class and
    may not reach for LGD-AM there. See [LGD-AM Availability Gate](#lgd-am-availability-gate-art-143-art-1791aa-art-147a)
    below.

### LGD-AM Availability Gate (Art. 143, Art. 179(1)(aa), Art. 147A)

LGD-AM sits inside the A-IRB own-LGD model rather than as a stand-alone CRM
overlay. Four PS1/26 provisions, read together, gate whether a firm may apply
LGD-AM to a given exposure at all.

#### 1. A-IRB permission for the exposure class (Art. 143(2A)(c))

Art. 143(2A) requires a firm, when applying for IRB permission, to state "in
relation to **each exposure class, exposure subclass or type of exposures**"
which IRB approach it proposes — (a) Slotting, (b) F-IRB, or (c) A-IRB. The
permission therefore attaches to the class/subclass, not to the institution as
a whole. Art. 143(2B) confirms that a firm with IRB permission for one approach
(e.g. F-IRB) that wishes to move a class to a more sophisticated approach
(e.g. A-IRB) needs **further** prior PRA permission.

Consequence: LGD-AM is available **only** for exposures that fall inside an
exposure class / subclass / type of exposures for which the firm currently
holds A-IRB permission. F-IRB classes are restricted to PSM under Art. 236.

#### 2. Art. 179(1)(aa) — own-LGD ban on guarantee recoveries except via LGD-AM

Art. 179(1)(aa) (ps126app1.pdf p.131) states verbatim: "an institution shall
**not** take account of recoveries from guarantees, credit derivatives and
other support arrangements when quantifying LGD estimates, **except where
recoveries are recognised under the LGD Adjustment Method in accordance with
Article 183**."

Consequence: the LGD Adjustment Method is the *only* channel through which an
A-IRB firm may reflect unfunded credit protection inside its own-LGD model.
Firms without A-IRB permission for the class cannot take the Art. 179(1)(aa)
exception — they fall back to PSM (Art. 236) applied outside the LGD model.

#### 3. Art. 147A — approach restrictions that pre-empt LGD-AM

Even where a firm holds A-IRB permission historically, PS1/26 Art. 147A
removes A-IRB from the menu for certain classes. The restrictions most
material for LGD-AM scope are:

| Art. 147A limb | Exposure class | Permitted approaches | LGD-AM available? |
|----------------|----------------|----------------------|-------------------|
| (1)(a) | Sovereigns and quasi-sovereigns (incl. RGLAs, PSEs, MDBs, International Organisations) | SA only | **No** — A-IRB not available |
| (1)(b) | Institutions | F-IRB or SA | **No** — A-IRB not available |
| (1)(e) | Large corporates (consolidated revenue > £440m) and financial sector entities | F-IRB or SA | **No** — A-IRB not available |
| (1)(d) | Equity exposures | SA only | **No** — IRB approach not available |

For these classes, PSM under Art. 236 is the only unfunded-CRM channel,
regardless of any historical A-IRB permission. See
[Model Permissions spec](model-permissions.md) for the full Art. 147A
restriction table.

#### 4. Art. 191A(3) — portfolio-wide consistency

Art. 191A(3) requires a firm to use the **same CRM method for the same type of
unfunded credit protection** across its portfolio. A firm that elects LGD-AM
for guarantees in one A-IRB class must not also run PSM on the same type of
guarantee in another A-IRB class — the consistency rule is per protection
type, not per exposure class. (The rule does not force LGD-AM onto F-IRB
classes: PSM remains mandatory there under limb 1 above.)

!!! info "Decision summary — where LGD-AM is available"
    For a given (exposure class, protection type) pair, LGD-AM is on the menu
    **only** when **all** of the following hold:

    1. The firm holds an A-IRB permission for the exposure class under Art.
       143(2A)(c) or Art. 143(2B)(b)(iii).
    2. Art. 147A does not remove A-IRB from the permitted-approach list for
       that class.
    3. The firm has chosen LGD-AM (rather than PSM) as its portfolio-wide
       method for this protection type under Art. 191A(3).
    4. The unfunded credit protection meets the Art. 183(1A) eligibility
       conditions (written contract, no unilateral cancellation, not a
       second-to-default derivative).

    If any condition fails, the firm applies PSM (Art. 236) instead, with SA
    risk-weight substitution for SA-approach guarantors.

---

## Tranched Coverage (Art. 234)

Art. 234 governs **partial / tranched** unfunded credit protection — structures
where the protection covers only part of the loss range on the underlying exposure
(for example, a guarantee that absorbs losses between an attachment point and a
detachment point, while the borrower retains the first-loss and senior tranches).

Under Art. 234 the protected and unprotected tranches are treated as separate
exposures, and the protection is recognised only on the covered tranche, with the
risk weight or PD/LGD of the protection provider substituted via the appropriate
method (RWSM under Art. 235 for SA / Slotting, or PSM under Art. 236 for IRB).

!!! warning "Not Yet Implemented"
    Art. 234 tranched / partial-coverage unfunded protection is not modelled. The
    CRM processor treats unfunded credit protection as covering a single contiguous
    portion of the exposure (the `covered_amount` field) and does not split the
    underlying exposure into attachment / detachment tranches with separate risk
    weights per tranche. Structured protection arrangements that cover only a
    middle loss tranche are therefore mis-stated.
    See IMPLEMENTATION_PLAN.md item **P1.30(e)** (Art. 234 partial protection
    tranching) for the tracking entry and effort estimate.

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

## Life Insurance Method (Art. 232)

Life insurance policies assigned to the institution are the principal
non-cash item recognised through the **Other Funded Credit Protection
Method** (`OFCP`) introduced by PS1/26 Art. 191A. Paragraph references below
verified against `ps126app1.pdf` pp.211–212.

### Scope Gate (Art. 232(A1))

Art. 232 applies only to an institution that has elected the Other Funded
Credit Protection Method under the Art. 191A(1) taxonomy. Under Basel 3.1
life insurance is **not** available through FCSM or FCCM — those methods
are restricted to financial collateral (Art. 222, 223). This is a structural
change from CRR, where Art. 232 stood alone without the Art. 191A method
taxonomy.

### Paragraph 1 — Cash / Cash-Assimilated Deposits Held by a Third Party

Where the Art. 212(1) conditions are met (pledge / assignment, notification,
payment-control), cash on deposit with — or cash-assimilated instruments
issued by the institution and held by — a **third-party institution** in a
**non-custodial arrangement** may be treated as a **guarantee by the third
party institution**. The exposure is then routed through the unfunded CRM
path (Art. 235 Risk-Weight Substitution for SA, or Art. 236 Parameter
Substitution for IRB) per the Part 3 decision tree of Appendix 1.

### Paragraph 2 — Life Insurance Treatment

Where the Art. 212(2) conditions are met (policy pledged / assigned,
insurer notified, right to cancel on default, surrender value declared and
non-reducible, maturity-match), the portion of the exposure collateralised
by the **current surrender value** is subjected to:

- **(a) Standardised Approach**: risk-weighted per paragraph 3 (derivation
  table below).
- **(b) Foundation IRB**: assigned **LGD = 40%**. CRR's broader "IRB but not
  own estimates of LGD" phrasing is narrowed to F-IRB in PS1/26 — A-IRB
  firms now handle life insurance through their own LGD models (subject to
  Art. 169A/169B).

The credit protection value equals the current surrender value, reduced for
currency mismatch in accordance with Art. 233(3) **and (4)** (PS1/26 adds
the (4) cross-reference to capture the full Art. 233 currency-mismatch
machinery, not just the 8% haircut).

### Paragraph 3 — SA Derivation Table (Life Insurance)

The risk weight applied to the secured portion is derived from the risk
weight that **would** be assigned to a **senior unsecured exposure to the
insurer** under the SA (Credit Risk: Standardised Approach (CRR) Part and
Chapter 2 of Title II of Part Three of CRR):

| PS1/26 para | Insurer Senior-Unsecured RW        | Secured Portion RW |
|-------------|------------------------------------|--------------------|
| (a)         | 20%                                | 20%  |
| (b)         | **30%** or 50%                     | 35%  |
| (c)         | **65%**, 100% or **135%**          | 70%  |
| (d)         | 150%                               | 150% |

!!! info "New Basel 3.1 input tiers — 30%, 65%, 135%"
    PS1/26 Art. 232(3) expands the paragraph 3 groupings to accommodate the
    new SA institution / corporate risk weights introduced by the Basel 3.1
    reforms. The output columns are unchanged; only the inputs widen:

    | New input | Origin | Article |
    |-----------|--------|---------|
    | **30%** → 35% | SCRA Grade A enhanced (well-capitalised bank) | Art. 121(5) |
    | **65%** → 70% | Investment-grade corporate | Art. 122(2)(a) |
    | **135%** → 70% | Non-investment-grade corporate (institution permission) | Art. 122(6)(b) |

    Under CRR the derivation table had only **four** input tiers
    (20% / 50% / 100% / 150%). A CRR firm holding life insurance issued by a
    well-capitalised but unrated bank could not map the B31 30% SCRA Grade A
    enhanced weight onto the derivation table at all — the gap is closed by
    Art. 232(3)(b). The 135% non-IG corporate tier is gated on PRA permission
    per Art. 122(6); firms without that permission fall back to the 100%
    tier (Art. 122(5)).

### Paragraph 4 — Repurchase-on-Request Instruments (Art. 200(1)(c))

Instruments repurchased on request by the issuing institution and eligible
under Art. 200(1)(c) may be treated as a **guarantee by the issuing
institution** (again routed via Art. 235 / 236 per the Part 3 decision
tree). Protection value = face value if face-repurchase, or the Art. 197(4)
valuation if market-price-repurchase.

### Paragraph 5 — Mandatory Maturity-Mismatch Adjustment (new)

Unlike FCSM, which is exempt from the Art. 237-239 maturity-mismatch
framework (see [Art. 239(1)](#art-237-eligibility-gates)), the Other
Funded Credit Protection Method **is** in scope. Paragraph 5 makes this
explicit: an institution using OFCP "shall take into account any maturity
mismatch in accordance with the provisions of Articles 237 to 239". CRR
had no equivalent standalone sub-paragraph — the obligation was implicit
through the general Art. 238 scope — so PS1/26 tightens the wording
without changing the substantive outcome.

### Structural Changes vs CRR Art. 232

| Change | CRR Art. 232 | PS1/26 Art. 232 |
|--------|--------------|-----------------|
| Scope gate | Standalone article | New paragraph A1: only for firms using OFCP under Art. 191A |
| Para 1 routing | "Guarantee by the third party institution" | Same, but explicitly routed via Art. 235 / 236 decision tree (Part 3 Appendix 1); cash instruments must be in a **non-custodial arrangement** |
| Para 2 IRB scope | "IRB Approach but not subject to own estimates of LGD" | Narrowed to "Foundation IRB Approach" |
| Para 3 input tiers | 4 tiers: 20% / 50% / 100% / 150% | 7 tiers: 20% / **30%** / 50% / **65%** / 100% / **135%** / 150% |
| Para 2 currency mismatch | Cross-ref Art. 233(3) only | Cross-ref Art. 233(3) **and (4)** |
| Para 5 maturity mismatch | Not stated (implicit via Art. 238) | Explicit sub-paragraph requiring Art. 237-239 adjustment |

### Implementation

Life insurance collateral flows through the Art. 232 derivation table in
`engine/crm/life_insurance.py`. Inputs: the insurer identifier on the
facility / loan row, the pledged surrender value, and the policy currency.
The insurer's senior-unsecured SA RW is re-computed against the framework
in play (CRR: CRR Table 3 / 4; B31: ECRA Table 3 / 4 or SCRA Table 5 per
Art. 121). The mapping is then applied to produce the secured-portion RW
emitted as the `life_ins_secured_rw` column (see
[Output Schemas](../../data-model/output-schemas.md)).

!!! warning "Output-column naming documented separately"
    The `life_ins_collateral_value` / `life_ins_secured_rw` output columns
    are tracked for schema documentation under DOCS_IMPLEMENTATION_PLAN
    D3.53 — not part of the current D2.48 closure.

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
      FCSM entirely: where a maturity mismatch exists, *"an institution
      using the Financial Collateral Simple Method **shall not use** the
      collateral as eligible funded credit protection"* (PS1/26 Art. 239(1)
      verbatim). The collateral is simply not recognised — no GA / CVAM
      adjustment is permitted. Cross-reference: [Art. 222 — No Maturity
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
the underlying exposure maturity, *"an institution **shall not use** that
protection as eligible credit protection"* (PS1/26 Art. 237(1) verbatim).

**Art. 237(2) — Disqualifying conditions (either limb).** Where there is a
maturity mismatch, *"an institution **shall not use** the credit protection
as eligible credit protection where either of the following conditions is
met"* (PS1/26 Art. 237(2) verbatim):

- **(a)** the original maturity of the protection is less than one year; or
- **(b)** the exposure is a short-term exposure subject to a one-day floor on
  the maturity value M under Credit Risk: Internal Ratings Based Approach
  (CRR) Part Article 162(3) (e.g. certain repo / SFT / short-term
  trade-finance IRB exposures with M floored at one day).

!!! info "Near-final → final wording change (resolves D2.55)"
    The near-final rule instrument (PS9/24) rendered both Art. 237(1) and
    Art. 237(2) chapeau as *"an institution **may not** use that
    protection"* — which could be read as discretionary. The final PS1/26
    rule instrument (effective 1 January 2027) replaces *"may not"* with
    *"**shall not**"* in both paragraphs and in Art. 239(1) (FCSM
    exclusion), making the outcome unambiguously mandatory. The change
    is visible in the comparison document at `docs/assets/comparison-of-the-final-rules.pdf`
    pp. 221–223 (strikethrough / insert mark-up). Functionally the
    outcome is identical in both drafts — the protection is simply not
    recognised — but the final text removes any residual drafting
    ambiguity. Under the prior CRR text the same outcome was framed as
    *"that protection **does not qualify** as eligible credit
    protection"* (CRR Art. 237, outcome-voiced rather than
    obligation-voiced); see the CRR CRM spec for the verbatim CRR
    phrasing.

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
