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
| FR-8.7 | Unfunded credit protection transitional (Rule 4.11) | P2 | Done |

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

**PRA PS1/26 Art. 224 Table 3 — 10-day liquidation period**

| CQS | 0–1y | 1–3y | 3–5y | 5–10y | 10y+ |
|-----|------|------|------|-------|------|
| CQS 1 | 0.5% | 2% | 2% | 4% | 4% |
| CQS 2 | 1% | 3% | 4% | 6% | 12% |
| CQS 3 | 1% | 3% | 4% | 6% | 12% |
| CQS 4 | 15% | 15% | 15% | 15% | 15% |

CQS 5–6 government bonds are **ineligible** as financial collateral (Art. 197(1)(b)).

!!! note "CRR Comparison — Government Bonds"
    CRR used 3 bands: 0–1y, 1–5y, 5y+. For CQS 1 the split has no material impact
    (all sub-bands within 1–5y and 5y+ retain the same values). The main impact is
    CQS 2–3 bonds with 10y+ residual maturity: haircut increases from 6% to **12%**.

### Corporate and Institution Bond Haircuts (5-Band)

**PRA PS1/26 Art. 224 Table 3 — 10-day liquidation period**

| CQS | 0–1y | 1–3y | 3–5y | 5–10y | 10y+ |
|-----|------|------|------|-------|------|
| CQS 1 | 1% | 4% | 6% | 10% | 12% |
| CQS 2 | 2% | 6% | 8% | 15% | 15% |
| CQS 3 | 2% | 6% | 8% | 15% | 15% |

CQS 4–6 corporate/institution bonds are **ineligible** (Art. 197(1)(d)).

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

### Non-Daily Revaluation

When collateral is not revalued daily, haircuts are scaled up:

```
H_m = H x sqrt(T_m / 10)
```

Where `T_m` is the liquidation period in business days.

### Liquidation Periods

| Transaction Type | Period |
|-----------------|--------|
| Repo / SFT | 5 days |
| Capital market | 10 days |
| Secured lending | 20 days |

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

For the guaranteed portion of the exposure:

```
guarantor_rw = IRB_formula(PD=guarantor_pd_floored, LGD=0.40, MA=MA_original, scaling=1.0)
```

Where:

- `guarantor_pd_floored` = guarantor's PD, subject to the same PD floors as the borrower
- LGD = **40%** (F-IRB senior unsecured non-FSE rate under Basel 3.1)
- Scaling factor = 1.0 (no 1.06)

### Blended RWA

```
RWA = RWA_borrower x (unguaranteed / EAD) + guaranteed_portion x guarantor_rw x 12.5
```

Parameter substitution is only applied when **beneficial** (guarantor RW < borrower's
original IRB RW).

### Expected Loss Under Parameter Substitution

```
EL_blended = EL_original x (unguaranteed / EAD) + guarantor_pd_floored x 0.40 x guaranteed_portion
```

### Audit Trail

The `guarantee_method_used` output column indicates the method applied:

| Value | Meaning |
|-------|---------|
| `PD_SUBSTITUTION` | IRB guarantor under Basel 3.1 |
| `SA_RW_SUBSTITUTION` | SA guarantor, or any guarantor under CRR |
| `NO_GUARANTEE` | No guarantee applied |

---

## CRM Method Taxonomy (Art. 191A)

Basel 3.1 introduces explicit method names:

| Method | Acronym | Scope |
|--------|---------|-------|
| Foundation Collateral Method | FCM | F-IRB: financial and physical collateral |
| Parameter Substitution Method | PSM | F-IRB: unfunded credit protection |
| LGD Adjustment Method | LGD-AM | A-IRB: unfunded credit protection |

### Method Selection by Approach

| Approach | Funded Protection | Unfunded Protection |
|----------|-------------------|---------------------|
| SA | Financial Collateral Simple Method (Art. 222) or Comprehensive Method | SA-RW substitution |
| F-IRB | FCM (Art. 230) | PSM (PD substitution for IRB guarantors, SA-RW for SA guarantors) |
| A-IRB | LGD modelling (Art. 169A/169B) or FCM | LGD-AM or PSM |

---

## Unfunded Credit Protection Transitional (Rule 4.11)

Pre-1 January 2027 unfunded credit protection contracts may continue to use CRR eligibility
criteria until **30 June 2028**, even if they do not meet the stricter Basel 3.1 requirements
(e.g., the new "or changeable" criterion in Art. 213).

!!! note "Implementation Status"
    The transitional rule is noted in the spec for completeness. The calculator applies the
    framework-appropriate CRM rules based on `CalculationConfig.regulatory_framework`.

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
