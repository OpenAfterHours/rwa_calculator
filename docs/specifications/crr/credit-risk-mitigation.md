# Credit Risk Mitigation Specification

Collateral haircuts, overcollateralisation, FX mismatch, maturity mismatch, and guarantee substitution.

**Regulatory Reference:** CRR Articles 192-241

**Test Group:** CRR-D

---

## Requirements Status

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-2.1 | Collateral recognition for 9 types | P0 | Done |
| FR-2.2 | Supervisory haircuts with maturity/currency mismatch | P0 | Done |
| FR-2.3 | Overcollateralisation ratios | P0 | Done |
| FR-2.4 | Multi-level collateral allocation | P0 | Done |
| FR-2.5 | Guarantee substitution | P0 | Done |
| FR-2.6 | Cross-approach CCF substitution | P0 | Done |

---

## Collateral Haircuts (CRR Art. 224)

### Financial Collateral

| Collateral Type | Haircut (10-day) |
|----------------|------------------|
| Cash / Deposit | 0% |
| Gold | **20%** |

### Government Bonds (by CQS and Residual Maturity)

| CQS | 0-1 year | 1-5 years | 5+ years |
|-----|----------|-----------|----------|
| 1 | 0.5% | 2% | 4% |
| 2-3 | 1% | 3% | 6% |
| 4 | 15% | 15% | 15% |

**Note on CQS eligibility:**

- CQS 1-4 government/central bank bonds are eligible as financial collateral (Art. 197(1)(b): "credit quality step 4 or above" means CQS 1–4 are all eligible)
- CQS 4 government bonds use a flat 15% haircut (Art. 224 Table 1)
- CQS 5-6 government bonds are **ineligible** as financial collateral (Art. 197)
- CQS 1-3 institution/corporate bonds are eligible (Art. 197(1)(c)/(d)); CQS 4-6 institution/corporate bonds are **ineligible**

### Corporate/Institution Bonds (by CQS and Residual Maturity — Art. 224 Table 1, 10-day)

| CQS | ≤1yr | 1-3yr | 3-5yr | 5-10yr | >10yr |
|-----|------|-------|-------|--------|-------|
| 1 | 1% | 3% | 4% | 6% | 12% |
| 2-3 | 2% | 4% | 6% | 12% | 20% |

### Equity (Art. 224 Table 3, 10-day)

| Type | Haircut |
|------|---------|
| Main index | **20%** |
| Other listed | **30%** |

### Non-Financial Collateral

Non-financial collateral does not use the supervisory volatility haircut framework (Art. 224). Instead, it is recognised through the **Foundation Collateral Method** (Art. 230-231) using LGDS values and overcollateralisation ratios. The haircut-like values below represent the effective value reduction:

| Type | Effective Haircut | Mechanism |
|------|-------------------|-----------|
| Receivables | ~40% | LGDS = 20%, OC ratio = 1.25x |
| Real estate | ~40% | LGDS = 20%, OC ratio = 1.4x |
| Other physical | ~44% | LGDS = 25%, OC ratio = 1.4x |

See [F-IRB LGDS Values](#f-irb-lgds-values-art-230) and [Overcollateralisation](#overcollateralisation-crr-art-230) below for the precise treatment.

### FX Mismatch Haircut (CRR Art. 233)

When collateral currency differs from exposure currency: **8%** additional haircut.

### Zero-Haircut Conditions (CRR Art. 227)

Under certain conditions, supervisory haircuts may be set to **0%** for repo-style transactions:

- Both the exposure and collateral are **cash or CQS 1 government bonds**
- The transaction is subject to **daily margin maintenance** with a one-day margin period of risk
- In the event of a counterparty failure to deliver margin, the transaction can be **terminated and collateral liquidated promptly**
- Settlement is via a **delivery-versus-payment** or equivalent mechanism
- The documentation is **standard market documentation** for the repo/SFT transaction type

Where these conditions are met, H_c = 0%, H_e = 0%, and H_fx = 0% (if applicable).

!!! note "Implementation Status"
    Zero-haircut conditions are not yet evaluated in the calculator. All transactions currently use the standard supervisory haircuts. This is a future enhancement.

### Volatility Scaling (CRR Art. 226)

Art. 226 defines **two separate scaling formulas**:

**Art. 226(2) — Scaling between liquidation periods:**
```
H_m = H_n × sqrt(T_m / T_n)
```
Where `H_n` is the haircut at liquidation period `T_n` and `H_m` is the haircut at the target period `T_m`.

**Art. 226(1) — Non-daily revaluation adjustment:**
```
H = H_m × sqrt((NR + T_m - 1) / T_m)
```
Where `NR` is the actual number of business days between revaluations and `T_m` is the liquidation period in days.

### Liquidation Period Dependency (CRR Art. 224, Tables 1-4)

| Transaction Type | Minimum Holding Period (T_m) |
|-----------------|------------------------------|
| Repo-style transactions | 5 business days |
| Other capital market transactions | 10 business days |
| Secured lending | 20 business days |

Art. 224 Tables 1-4 provide haircuts at all three liquidation periods. When scaling is needed (e.g., applying a 10-day table haircut to a repo), use Art. 226(2). When revaluation is not daily, additionally apply Art. 226(1).

### F-IRB LGDS Values (Art. 230)

Under the Foundation Collateral Method, the collateral-adjusted LGD (LGD*) uses supervisory LGDS values:

| Collateral Type | LGDS |
|----------------|------|
| Financial collateral | 0% |
| Receivables | 20% |
| Commercial / residential real estate | 20% |
| Other physical collateral | 25% |

### LGD* Formula — Foundation Collateral Method (Art. 230)

The formula blends LGDU (unsecured) and LGDS (secured) across the secured and unsecured portions:

```
LGD* = LGDU × (EU / E(1+HE)) + LGDS × (ES / E(1+HE))
```

Where:
- `E(1+HE)` = exposure value grossed up by the exposure volatility haircut
- `ES` = haircut-adjusted collateral value, capped at `E(1+HE)`: `ES = min(C(1-HC-HFX), E(1+HE))`
- `EU` = unsecured portion: `EU = E(1+HE) - ES`
- `LGDU` = unsecured LGD (40% non-FSE / 45% FSE under CRR; same under B31 per Art. 161(1))
- `LGDS` = secured LGD (0% financial, 20% receivables/RE, 25% other physical)
- `HC` = collateral haircut, `HE` = exposure haircut, `HFX` = FX mismatch haircut (8% if currencies differ)

!!! warning "Previous Formula Was Wrong"
    The formula previously documented here (`LGD* = LGD × (E*/E)` where `E* = max(0, E(1+HE) - C(1-HC-HFX))`) applies a single LGD to the residual exposure fraction. This is only correct when LGDS = LGDU. For non-financial collateral (LGDS = 20-25%, LGDU = 40-45%), the correct formula must blend both rates across the secured and unsecured portions.

### Mixed Collateral Pools (Art. 231)

When an exposure is secured by multiple collateral types, allocation is **sequential (waterfall)**, not pro-rata:

```
For each collateral type i (in chosen order):
  ES_i = min(C_i, E(1+HE) - sum(ES_k for k < i))
  EU = E(1+HE) - sum(ES_i)

Blended LGD* = sum(LGDS_i × ES_i / E(1+HE)) + LGDU × EU / E(1+HE)
```

The institution may choose the ordering (most favourable = lowest LGDS first). Typical waterfall: financial collateral first (LGDS=0%), then receivables (20%), then real estate (20%), then other physical (25%), with the remainder at LGDU.

!!! warning "Previous Formula Was Wrong"
    The formula previously documented here used pro-rata allocation (`E_i = E × (C_i / sum(C_all))`). Art. 231 requires sequential fill — each collateral type absorbs as much exposure as possible before the next type. Pro-rata and sequential give different LGD* when total collateral < total exposure.

## Non-Financial Collateral Recognition (CRR Art. 230)

Non-financial collateral is recognised through the Foundation Collateral Method using the LGD* formula with LGDS values and the HC=40% haircut mechanism.

!!! warning "Overcollateralisation Ratios Are Not in Art. 230"
    The overcollateralisation ratios (1.25x receivables, 1.4x RE/physical) and 30% minimum thresholds previously documented here do not appear in Art. 230 of CRR or PRA PS1/26. Art. 230 uses the HC=40% mechanism within the LGD* formula. Applying additional ratio checks on top of the LGD* formula would be double-counting. These ratios may derive from old CRR Art. 227 (SA overcollateralisation for physical collateral under the Simple Method). The code at `engine/crm/collateral.py` implements these ratios — needs verification against the actual regulation.

### Minimum Coverage Requirements

Art. 230 does specify conditions for collateral eligibility:
- The collateral must be properly valued and regularly revalued
- The collateral value must be sufficient to justify the LGDS applied
- Specific conditions apply per collateral type (e.g., real estate valuation requirements per Art. 229)

## Maturity Mismatch Eligibility (CRR Art. 237)

When a maturity mismatch exists (collateral maturity < exposure maturity), credit protection
is only eligible if **all** of the following conditions are met (Art. 237(2)):

1. **Residual maturity ≥ 3 months** — protection with < 3 months residual maturity is disallowed
2. **Original maturity ≥ 1 year** — protection instruments originally issued with a term < 1 year are ineligible when a mismatch exists
3. **Not a 1-day M floor exposure** — exposures subject to Art. 162(3) 1-day maturity floor (repos, SFTs with daily margining) cannot use maturity-mismatched protection at all

If any condition fails, the protection value is zeroed (collateral value = 0 for the mismatched portion).

## Maturity Mismatch Adjustment (CRR Art. 238)

When collateral maturity is shorter than exposure maturity and the Art. 237 eligibility
conditions are met:

```
adjustment_factor = (t - 0.25) / (T - 0.25)
```

Where `t` = residual collateral maturity (years), `T` = min(residual exposure maturity, 5) years.

**No adjustment** when collateral residual maturity ≥ exposure residual maturity (no mismatch).

## Multi-Level Collateral Allocation

Collateral is allocated at three levels, distributed pro-rata:

1. **Exposure level** - Collateral pledged directly against an exposure
2. **Facility level** - Collateral pledged against a facility, shared across its exposures
3. **Counterparty level** - Collateral pledged against a counterparty, shared across all exposures

Financial and non-financial collateral are tracked separately to apply the correct overcollateralisation ratios and minimum thresholds.

## Guarantee Substitution (CRR Art. 213-217)

### Approach

The guarantor's risk weight replaces the borrower's risk weight for the guaranteed portion of the exposure, but only when this is beneficial.

### Application Logic

1. Look up the guarantor's risk weight based on entity type and CQS
2. Compare to the borrower's risk weight
3. If guarantor RW < borrower RW, apply substitution on the guaranteed portion
4. If guarantor RW ≥ borrower RW, no substitution (guarantee is non-beneficial)

### Blended Risk Weight

For partially guaranteed exposures:

```
RW_blended = (unguaranteed_portion x borrower_RW + guaranteed_portion x guarantor_RW) / EAD
```

### Tracking Fields

The calculator tracks pre- and post-CRM values for audit:

- `pre_crm_counterparty_reference` / `post_crm_counterparty_guaranteed`
- `pre_crm_exposure_class` / `post_crm_exposure_class_guaranteed`
- `guaranteed_portion` / `unguaranteed_portion`
- `is_guarantee_beneficial`

## Unfunded Credit Protection Adjustments (Art. 233)

### FX Mismatch for Guarantees/CDS (Art. 233(3-4))

When a guarantee or credit derivative is denominated in a different currency from the exposure:

```
G* = G × (1 - H_fx)
```

Where `H_fx` is from Art. 224 Table 4 at the applicable liquidation period (8% at 10-day, scaled by Art. 226(1) if not daily revalued). The guaranteed amount must be reduced before applying substitution.

### CDS Restructuring Exclusion Haircut (Art. 233(2) / Art. 216(1))

If a credit derivative does not include restructuring as a credit event:
- Protection value is **reduced by 40%** (if protection amount ≤ exposure value)
- Protection value is **capped at 60% of exposure value** (if protection amount > exposure value)
- Exception: Art. 216(3) exemption applies where restructuring requires 100% vote amendment and the reference entity is subject to a well-established bankruptcy code

## Partial Protection and Tranching (CRR Art. 233A / Art. 234)

### Proportional Coverage (Art. 233A)

When unfunded credit protection covers only a proportion of the exposure:

- The **covered portion** receives the protection provider's risk weight (substitution)
- The **uncovered portion** retains the obligor's risk weight
- The split is simple pro-rata: `covered = guarantee_amount / exposure_value`

### Tranched Coverage (Art. 234)

When credit protection covers a specific tranche (first loss or mezzanine) rather than proportional coverage:

- **First loss tranche**: The protection covers losses up to a specified threshold. The firm bears losses above the threshold. The protected portion uses the protection provider's risk weight; the retained senior tranche uses the obligor's risk weight.
- **Second loss / mezzanine tranche**: More complex — the firm bears first losses up to the attachment point, protection covers the mezzanine band. The first loss portion may attract higher risk weights (up to 1250% for securitisation-like treatment).
- **Maturity mismatch**: Standard maturity mismatch adjustment (Art. 238) applies to the protected tranche.

!!! note "Implementation Status"
    Proportional coverage is implemented. Tranched coverage (Art. 234) is not yet implemented — all guarantee coverage is treated as proportional. This is a future enhancement for structured credit protection.

## Cross-Approach CCF Substitution (CRR Art. 153(3))

When an IRB exposure is guaranteed by a counterparty under the Standardised Approach, the guaranteed portion uses SA CCFs instead of IRB supervisory CCFs.

### Guarantor Approach Determination

The guarantor's approach is "sa" when:
- The firm lacks IRB permission for the guarantor's exposure class, OR
- The guarantor has only an external rating (no internal PD)

The guarantor's approach is "irb" only when both conditions are met:
- The firm has IRB permission for the guarantor's exposure class, AND
- The guarantor has an internal rating with PD

### EAD Split

```
ead_guaranteed = guarantee_ratio × (drawn + undrawn × ccf_sa)
ead_unguaranteed = (1 - guarantee_ratio) × (drawn + undrawn × ccf_irb)
```

### Output Fields

- `ccf_original`, `ccf_guaranteed`, `ccf_unguaranteed`
- `guarantee_ratio`, `guarantor_approach`, `guarantor_rating_type`

## Provision Resolution (Before CRM)

Provisions are resolved **before** the CRM waterfall (and before CCF application). See [Provisions Specification](provisions.md) for the drawn-first deduction approach and multi-level beneficiary resolution. The CRM waterfall (collateral → guarantees) operates on the provision-adjusted EAD.

## CRM Method Selection (PRA PS1/26 Art. 191A)

Basel 3.1 introduces a formal decision tree framework for CRM method selection (Appendix 1):

### Part 1 — Funded CRM with CCR Exposure
CCR exposures → IMM / SFT VaR Method / Financial Collateral Comprehensive Method / Financial Collateral Simple Method (SA only)

### Part 2 — Funded CRM without CCR
1. On-balance sheet netting → Art. 219
2. Financial collateral → Comprehensive Method (Art. 223) or Simple Method (Art. 222, SA only)
3. Immovable property / receivables / other physical → Foundation Collateral Method (Art. 229-231, IRB only)
4. Life insurance / instruments from institutions → Other Funded Protection Method (Art. 232)

### Part 3 — Unfunded CRM
- SA / Slotting → Risk-Weight Substitution Method (Art. 235)
- FIRB / AIRB → Parameter Substitution Method (Art. 236)
- AIRB (own estimates) → LGD Adjustment Method (Art. 183)

### Part 4 — Unfunded Covered by Funded
Nested application of Parts 1-3 where unfunded protection is itself collateralised.

## Financial Collateral Simple Method (Art. 222)

SA-only method (FCSM). The risk weight of the collateral substitutes for the exposure risk weight on the secured portion:

- **Floor**: 20% minimum risk weight (except qualifying repo-style transactions per Art. 222(4): 0%)
- **Art. 222(6) 0% condition**: 0% RW applies where exposure and collateral are same currency AND either (a) cash/deposit collateral, or (b) 0%-RW sovereign bond collateral with a **20% market value discount** applied
- **Eligibility**: Collateral must be eligible financial collateral per Art. 197
- **Maturity**: Collateral maturity must cover exposure maturity (no mismatch allowed)
- **Formula**: `RW_secured = max(20%, RW_collateral)`, `RW_unsecured = RW_obligor`

The calculator uses the Financial Collateral Comprehensive Method by default.

!!! note "Basel 3.1 FCSM Retention"
    Under Basel 3.1 (PRA PS1/26), the FCSM remains available for SA exposures only. IRB exposures must use the Comprehensive Method or LGD Modelling Collateral Method.

## Credit-Linked Notes (Art. 218)

Credit-linked notes (CLNs) issued by the institution are treated as **cash collateral** (funded credit protection):

- The CLN is treated as cash equivalent — Art. 194(6)(c) condition is deemed satisfied
- The embedded CDS must qualify as eligible unfunded credit protection
- Funded protection value = nominal amount of the CLN minus any credit event reduction

!!! warning "Previous Description Was Wrong"
    CLNs were previously described as "funded credit protection from the issuer" with "issuer risk weight" to be considered. Art. 218 does not introduce a separate issuer risk weight check — the CLN is treated as cash collateral.

## Life Insurance Method (Art. 232)

Life insurance policies assigned to the lending institution as collateral:

- **Eligible**: Only life insurance policies with a current surrender value assigned/pledged to the institution (Art. 200(b) + Art. 212(2) operational requirements)
- **Haircut**: The collateral value is the current surrender value, subject to a haircut based on the difference between surrender value and the claim at maturity
- **SA risk weight**: The secured portion uses a **mapped risk weight** (not direct substitution):

| Insurer Risk Weight | Secured Portion RW |
|--------------------|-------------------|
| 20% | 20% |
| 30% or 50% | 35% |
| 65%, 100%, or 135% | 70% |
| 150% | 150% |

- **F-IRB treatment** (Art. 232(2)(b)): The secured portion uses LGD = **40%** (not the standard LGDU)
- **A-IRB treatment**: Own LGD estimate for the secured portion

!!! warning "Previous Description Was Wrong"
    Three errors corrected: (1) Risk weight is a mapped table, not direct substitution from the insurer; (2) IRB treatment (LGD = 40%) was missing; (3) Eligibility was cited as Art. 201 (unfunded protection providers) — correct reference is Art. 200(b) (eligible funded collateral) + Art. 212(2) (operational requirements).

## Parameter Substitution Method (Art. 236)

IRB-only method for unfunded credit protection (guarantees and credit derivatives):

- **Covered portion**: Uses protection provider's PD with exposure's LGD
  - FIRB: covered LGD = supervisory LGD for senior unsecured claim on guarantor
  - AIRB: covered LGD = own LGD estimate for senior unsecured claim on guarantor
- **Uncovered portion**: Uses obligor's own PD and LGD
- **Expected loss**: `EL_covered = PD_guarantor × LGD_covered`, `EL_uncovered = PD_obligor × LGD`
- **Double recovery constraint**: Combined coverage from funded + unfunded cannot exceed 100%

## LGD Modelling Collateral Method (Basel 3.1 Art. 169A/169B)

New Basel 3.1 method for recognising collateral in A-IRB LGD estimates. This replaces the CRR approach of free-form LGD modelling with collateral:

### Scope (Art. 169A)

- Available **only** for A-IRB exposures where the firm has approval to model LGD
- Firms must demonstrate that their LGD models appropriately capture collateral effects
- Model must be validated separately for secured and unsecured exposure segments

### Key Requirements (Art. 169B)

- LGD estimates must reflect collateral-specific recovery characteristics
- **Haircut approach**: Firms may use own-estimate haircuts subject to PRA approval, or supervisory haircuts
- **Collateral revaluation**: Firms must revalue collateral at least annually, more frequently for volatile collateral
- **Downturn LGD**: Collateral values must be adjusted for economic downturn conditions
- The method must produce LGD estimates that are **at least as conservative** as the Foundation Collateral Method (Art. 230-231)
- LGD estimates remain subject to the **A-IRB LGD floors** per Art. 161(5)

### Relationship to Other Methods

| Approach | CRM Method | Reference |
|----------|-----------|-----------|
| SA | FCSM (Art. 222) or Comprehensive Method (Art. 223) | Art. 191A Part 2 |
| F-IRB | Foundation Collateral Method (Art. 229-231) | Art. 191A Part 2 |
| A-IRB | LGD Modelling Collateral Method (Art. 169A/169B) **or** Foundation Collateral Method | Art. 191A Part 2 |

## Parameter Substitution LGD Choice (Art. 236)

Under IRB parameter substitution for guaranteed exposures:

- **F-IRB**: The covered portion uses the **supervisory LGD for a senior unsecured claim** on the guarantor. For non-FSE guarantors this is 40%; for FSE guarantors this is 45%.
- **A-IRB**: The covered portion uses the firm's **own LGD estimate** for a senior unsecured claim on the guarantor, subject to A-IRB LGD floors.

The choice of LGD for the covered portion depends on the approach used for the guarantor's exposure class, not the obligor's approach.

## Unfunded Credit Protection Transitional (Rule 4.11)

Rule 4.11 provides a **narrow contractual carve-out** for pre-existing unfunded credit protection during 1 January 2027 to 30 June 2028:

- Art. 213(1)(c)(i) normally requires that protection contracts do not allow the provider to unilaterally cancel **or change** the terms
- Rule 4.11 removes the words **"or change"** from Art. 213(1)(c)(i) for unfunded credit protection entered into **prior to 1 January 2027**
- Effect: legacy protection contracts that contain clauses allowing the provider to **change** (but not unilaterally cancel) the protection remain eligible during the transitional period under the new Basel 3.1 Art. 213 requirements

!!! warning "Previous Description Was Wrong"
    Rule 4.11 was previously described as a broad permission to continue using pre-Basel 3.1 CRR treatment for legacy unfunded protection. The actual rule is narrower — it only removes the "or change" wording from one sub-paragraph of the eligibility test. The conditions about "not restructured or materially changed" were fabricated and do not appear in Rule 4.11.

!!! note "Transitional Scope"
    Rule 4.11 applies to **unfunded credit protection only** (guarantees and credit derivatives). Funded credit protection (collateral) transitions immediately to Basel 3.1 rules on 1 January 2027. The transitional is exposure-specific — each protection arrangement is assessed individually.

## Key Scenarios

| Scenario ID | Description |
|-------------|-------------|
| CRR-D | Financial collateral with cash (0% haircut) |
| CRR-D | Government bond collateral with maturity bands |
| CRR-D | FX mismatch haircut (8%) |
| CRR-D | Overcollateralisation: RE at 1.4x ratio |
| CRR-D | Minimum threshold: RE below 30% of EAD (zeroed) |
| CRR-D | Maturity mismatch adjustment |
| CRR-D | Beneficial guarantee substitution |
| CRR-D | Non-beneficial guarantee (guarantor RW ≥ borrower RW) |
| CRR-D | Multi-level collateral allocation |

## Acceptance Tests

| Group | Scenarios | Tests | Pass Rate |
|-------|-----------|-------|-----------|
| CRR-D: Credit Risk Mitigation | D1–D6 | 9 | 100% |
