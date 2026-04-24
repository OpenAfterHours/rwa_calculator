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

## Collateral Haircuts (CRR Art. 224 / PRA PS1/26 Art. 224)

CRR uses 3 maturity bands for bond haircuts; Basel 3.1 expands to 5 bands with increased haircuts at longer tenors. All values below are at the 10-day liquidation period.

### Financial Collateral

| Collateral Type | CRR Haircut | Basel 3.1 Haircut |
|----------------|-------------|-------------------|
| Cash / Deposit | 0% | 0% |
| Gold | 15% | 20% |

### Government Bonds (by CQS and Residual Maturity — Art. 224 Table 1)

**CRR (3 maturity bands):**

| CQS | 0–1yr | 1–5yr | 5yr+ |
|-----|-------|-------|------|
| 1 | 0.5% | 2% | 4% |
| 2-3 | 1% | 3% | 6% |
| 4 | 15% | 15% | 15% |

**Basel 3.1 (5 maturity bands — PRA PS1/26 Art. 224 Table 1, 10-day liquidation period):**

| CQS | 0–1yr | 1–3yr | 3–5yr | 5–10yr | >10yr |
|-----|-------|-------|-------|--------|-------|
| 1 | 0.5% | 2% | 2% | 4% | 4% |
| 2-3 | 1% | 3% | 3% | 6% | 6% |
| 4 | 15% | 15% | 15% | 15% | 15% |

Key B31 change: the 5-band split re-groups the CRR 1–5yr and 5yr+ bands but **does not raise sovereign haircuts** for well-rated issuers. CQS 2–3 sovereigns remain at 6% even at the longest tenor; the CRR-era "5yr+ = 6%" simply splits into 5–10yr = 6% and >10yr = 6%. The cross-reference to the authoritative B31 spec is [Government Bond Haircuts (5-Band)](../basel31/credit-risk-mitigation.md#government-bond-haircuts-5-band).

**CQS eligibility (Art. 197):**

- CQS 1-4 government/central bank bonds are eligible as financial collateral (Art. 197(1)(b))
- CQS 5-6 government bonds are **ineligible** (Art. 197)
- CQS 1-3 institution/corporate bonds are eligible (Art. 197(1)(c)/(d)); CQS 4-6 are **ineligible**

### Corporate/Institution Bonds (by CQS and Residual Maturity — Art. 224 Table 1)

**CRR (3 maturity bands):**

| CQS | 0–1yr | 1–5yr | 5yr+ |
|-----|-------|-------|------|
| 1 | 1% | 4% | 8% |
| 2-3 | 2% | 6% | 12% |

**Basel 3.1 (5 maturity bands — PRA PS1/26 Art. 224 Table 1, 10-day liquidation period):**

| CQS | 0–1yr | 1–3yr | 3–5yr | 5–10yr | >10yr |
|-----|-------|-------|-------|--------|-------|
| 1 | 1% | 3% | 4% | 6% | 12% |
| 2-3 | 2% | 4% | 6% | 12% | 20% |

Key B31 changes: the 5-band split **raises the longest-tenor haircuts** materially while easing short-to-mid tenors. CQS 1 >10yr moves from the CRR 5yr+ flat 8% to **12%**; CQS 2–3 >10yr moves from 12% to **20%** (a +8pp uplift). By contrast, CQS 1 / 1–3yr eases from 4% to 3% and CQS 2–3 / 1–3yr eases from 6% to 4%. The cross-reference to the authoritative B31 spec is [Corporate and Institution Bond Haircuts (5-Band)](../basel31/credit-risk-mitigation.md#corporate-and-institution-bond-haircuts-5-band).

!!! note "Change log — B31 comparison table corrections (2026-04-21)"
    Prior versions of this CRR spec showed pre-correction B31 haircuts (CQS 2–3 / 10yr+ govt at 12%; corporate/institution CQS 2–3 / 5–10yr and 10yr+ both at 15%; CQS 1 / 1–3yr at 4%). These were drafted before the 17 Apr 2026 re-audit of PS1/26 Art. 224 Table 1. Values above now match the authoritative Basel 3.1 CRM spec and `ps126app1.pdf` page 203.

### Equity (Art. 224 Table 3)

| Type | CRR Haircut | Basel 3.1 Haircut |
|------|-------------|-------------------|
| Main index | 15% | 20% |
| Other listed | 25% | 30% |

### Non-Financial Collateral

Non-financial collateral does not use the supervisory volatility haircut framework (Art. 224). Instead, it is recognised through the **Foundation Collateral Method** (Art. 230-231) using LGDS values within the LGD* formula. See [F-IRB LGDS Values](#f-irb-lgds-values-art-230--art-161) below for the per-framework values.

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
    Art. 227 zero-haircut conditions are implemented. Institutions certify all 8 conditions
    (a)-(h) via the `qualifies_for_zero_haircut` Boolean field on collateral input data.
    The calculator validates collateral type eligibility: only cash/deposit and CQS ≤ 1
    sovereign bonds qualify. When conditions are met, H_c = 0%, H_fx = 0%.
    Ineligible types (corporate bonds, equity, gold) fall through to standard haircuts
    even when the flag is set.

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

### F-IRB LGDS Values (Art. 230 / Art. 161)

Under the Foundation Collateral Method, the collateral-adjusted LGD (LGD*) uses supervisory LGDS values that differ by framework:

| Collateral Type | CRR LGDS (Senior) | CRR LGDS (Sub.) | Basel 3.1 LGDS | Reference |
|----------------|-------------------|-----------------|----------------|-----------|
| Financial collateral | 0% | 0% | 0% | Art. 230 Table 5 / Art. 230(2) |
| Receivables | 35% | 65% | 20% | Art. 230 Table 5 / CRE32.9 |
| Residential / commercial RE | 35% | 65% | 20% | Art. 230 Table 5 / CRE32.10-11 |
| Other physical collateral | 40% | 70% | 25% | Art. 230 Table 5 / CRE32.12 |
| Covered bonds | 11.25% | — | 11.25% | Art. 161(1)(d) / Art. 161(1B) |
| Life insurance (Art. 232) | 40% | — | 40% | Art. 232(2)(b) |

!!! info "CRR Art. 230 Table 5 — Subordinated LGDS"
    CRR Art. 230 Table 5 provides separate LGDS columns for "senior exposures" and
    "subordinated exposures". For subordinated claims secured by receivables or real estate,
    LGDS is 65% (vs 35% senior). For other physical collateral, subordinated LGDS is 70%
    (vs 40% senior). Financial collateral remains 0% for both.

!!! info "B31 Art. 230(2) — Subordinated LGDS Distinction Removed"
    PRA PS1/26 Art. 230(2) replaces the CRR Table 5 with a simplified table containing a
    single LGDS per collateral type (0%/20%/20%/25%) with no subordinated distinction. Under
    Basel 3.1, the subordination effect is captured solely through the LGDU term (75%,
    Art. 161(1)(b)).

Unsecured LGD (LGDU) for the unsecured portion of the LGD* formula:

| Seniority | CRR LGDU | Basel 3.1 LGDU | Reference |
|-----------|----------|----------------|-----------|
| Senior unsecured (non-FSE) | 45% | 40% | Art. 161(1)(a) / Art. 161(1)(aa) |
| Senior unsecured (FSE) | 45% | 45% | Art. 161(1)(a) |
| Subordinated | 75% | 75% | Art. 161(1)(b) |

!!! warning "Not Yet Implemented — Subordinated LGDS"
    The code uses a single set of LGDS values per collateral type (35%/35%/40% CRR; 20%/20%/25%
    B31) regardless of seniority. The CRR Art. 230 Table 5 subordinated LGDS values (65%/65%/70%)
    are not applied. This means subordinated claims secured by non-financial collateral receive
    an understated LGDS. The subordination effect comes only through LGDU = 75%, not the elevated
    LGDS. See D4.13.

### LGD* Formula — Foundation Collateral Method (Art. 230)

The formula blends LGDU (unsecured) and LGDS (secured) across the secured and unsecured portions:

```
LGD* = LGDU × (EU / E(1+HE)) + LGDS × (ES / E(1+HE))
```

Where:
- `E(1+HE)` = exposure value grossed up by the exposure volatility haircut
- `ES` = haircut-adjusted collateral value, capped at `E(1+HE)`: `ES = min(C(1-HC-HFX), E(1+HE))`
- `EU` = unsecured portion: `EU = E(1+HE) - ES`
- `LGDU` = unsecured LGD (CRR: 45% uniform; B31: 40% non-FSE / 45% FSE per Art. 161(1))
- `LGDS` = secured LGD per framework (see F-IRB LGDS table above)
- `HC` = collateral haircut, `HE` = exposure haircut, `HFX` = FX mismatch haircut (8% if currencies differ)

Note: The simplified formula `LGD* = LGD × (E*/E)` where `E* = max(0, E(1+HE) - C(1-HC-HFX))` only works when LGDS = LGDU. For non-financial collateral (LGDS ≠ LGDU), the blended formula above is required.

### Mixed Collateral Pools (Art. 231)

When an exposure is secured by multiple collateral types, allocation is **sequential (waterfall)**, not pro-rata:

```
For each collateral type i (in chosen order):
  ES_i = min(C_i, E(1+HE) - sum(ES_k for k < i))
  EU = E(1+HE) - sum(ES_i)

Blended LGD* = sum(LGDS_i × ES_i / E(1+HE)) + LGDU × EU / E(1+HE)
```

The institution may choose the ordering (most favourable = lowest LGDS first). Typical waterfall: financial collateral first (LGDS=0%), then receivables (20%), then real estate (20%), then other physical (25%), with the remainder at LGDU.

Note: Pro-rata allocation gives different LGD* than sequential fill when total collateral < total exposure. Art. 231 requires sequential fill.

## Non-Financial Collateral Recognition (CRR Art. 230)

Non-financial collateral is recognised through the Foundation Collateral Method using the LGD* formula with LGDS values.

### Overcollateralisation Ratios

The code implements overcollateralisation ratios (1.25x receivables, 1.4x RE/physical) and 30% minimum thresholds for RE and other physical collateral. These ratios divide the haircut-adjusted collateral value before it enters the LGD* waterfall, effectively reducing the recognised secured portion.

| Category | OC Ratio | Min Threshold |
|----------|----------|---------------|
| Financial | 1.00 | 0% |
| Receivables | 1.25 | 0% |
| Real estate | 1.40 | 30% of EAD |
| Other physical | 1.40 | 30% of EAD |
| Life insurance | 1.00 | 0% |

Regulatory basis: These ratios appear in CRR Art. 230(2) (conditions for non-financial collateral recognition) and are preserved under PRA PS1/26. They are not the same as the supervisory volatility haircuts in Art. 224.

### Minimum Coverage Requirements

Art. 230 specifies conditions for collateral eligibility:
- The collateral must be properly valued and regularly revalued
- The collateral value must be sufficient to justify the LGDS applied
- Specific conditions apply per collateral type (e.g., real estate valuation requirements per Art. 229)

## Maturity Mismatch (CRR Art. 237-239)

CRR Section 5 of Chapter 4 covers maturity mismatches across **both funded
and unfunded** credit protection. Art. 238(1A) (carried into PRA Rulebook
unchanged) enumerates the in-scope CRM methods; Art. 237 sets the
eligibility gates; Art. 239 sets the per-method valuation formula.

!!! info "B31 alignment"
    PRA PS1/26 (effective 1 January 2027) carries Art. 237/238/239 forward
    unchanged in substance — each PS1/26 article carries the note "This
    rule corresponds to Article 237/238/239 of CRR as it applied
    immediately before revocation by the Treasury". The B31 spec
    [b31/credit-risk-mitigation.md#maturity-mismatch-art-237-239](../basel31/credit-risk-mitigation.md#maturity-mismatch-art-237-239)
    holds the authoritative restatement.

### Methods in Scope (CRR Art. 238(1A))

The CRR maturity-mismatch framework applies to credit protection recognised
under any of the following methods:

| Letter | Method | Type |
|--------|--------|------|
| (a) | On-balance sheet netting (Art. 219) | Funded |
| (b) | FCCM (excluding SFTs covered by a master netting agreement) | Funded |
| (c) | Foundation Collateral Method (Art. 230) | Funded |
| (d) | Other Funded Credit Protection Method (Art. 232) | Funded |
| (e) | Risk-Weight Substitution Method — SA / Slotting guarantees and CDS (Art. 235) | **Unfunded** |
| (f) | Parameter Substitution Method — F-IRB / A-IRB guarantees and CDS (Art. 236) | **Unfunded** |

The same eligibility gates and adjustment formulas therefore apply to
collateral *and* to guarantees/CDS — there is no separate maturity-mismatch
treatment for unfunded protection in CRR. **FCSM** (Art. 222) and the A-IRB
**own-LGD** treatment (Art. 183) are the only CRM methods that sit outside
this perimeter (FCSM is excluded by Art. 239(1); own-LGD captures maturity
mismatches inside the LGD model).

## Maturity Mismatch Eligibility (CRR Art. 237)

When a maturity mismatch exists (protection residual maturity < exposure
residual maturity), credit protection is only eligible if **all** of the
following conditions are met:

1. **Art. 237(1) — combined test:** if the protection has residual maturity
   < 3 months *and* protection maturity < underlying exposure maturity,
   *"that protection **does not qualify** as eligible credit protection"*
   (CRR Art. 237(1) verbatim, `docs/assets/crr.pdf` p. 232).
2. **Art. 237(2)(a) — original maturity ≥ 1 year:** *"Where there is a
   maturity mismatch the credit protection **shall not qualify** as
   eligible"* (CRR Art. 237(2) chapeau verbatim) where the original
   maturity of the protection is less than one year.
3. **Art. 237(2)(b) — not a 1-day M-floor exposure:** the same chapeau
   applies where the exposure is a short-term exposure specified as
   subject to a one-day floor rather than a one-year floor in respect of
   the maturity value M under Art. 162(3) (repos, SFTs with daily
   margining, short-term trade-finance IRB exposures).

If any condition fails, the protection value is zeroed (collateral value =
0 for the mismatched portion). These gates apply uniformly to funded **and**
unfunded protection — a guarantee or CDS with original maturity < 1 year is
ineligible for an exposure with residual maturity > 1 year, just as a
financial-collateral instrument with the same characteristics is.

!!! info "CRR → Basel 3.1 wording change (resolves D2.55)"
    CRR Art. 237 uses **outcome-voiced** language — the protection "does
    not qualify" / "shall not qualify" as eligible. PS1/26 Art. 237
    (effective 1 January 2027) re-casts the same gates in
    **obligation-voiced** form — *"an institution **shall not use** that
    protection as eligible credit protection"*. The near-final
    instrument appended to PS9/24 rendered this as *"may not use"*
    (potentially discretionary); the final PS1/26 instrument replaces
    *"may not"* with *"**shall not**"* in both Art. 237(1) and
    Art. 237(2) chapeau, removing any residual drafting ambiguity. See
    the comparison document at
    `docs/assets/comparison-of-the-final-rules.pdf` pp. 221–223 for the
    strikethrough / insert mark-up. The functional outcome is identical
    across CRR and both PS9/24-near-final and PS1/26-final drafts — the
    protection is simply not recognised — but the precision matters
    when cross-referencing the text of individual paragraphs.

## Maturity Mismatch Adjustment (CRR Art. 239)

Two parallel formulas — Art. 239(2) for funded methods (a)–(d) and
Art. 239(3) for unfunded methods (e)–(f). The multiplier
`(t − 0.25) / (T − 0.25)` is identical between the two; only the
protection input differs.

**Art. 239(2) — funded protection (methods (a)–(d)):**

```
CVAM = CVA × (t - 0.25) / (T - 0.25)
```

`CVAM` substitutes for `CVA` in the FCCM E* formula at Art. 223(5), or
flows through Art. 219(3) for on-balance sheet netting.

**Art. 239(3) — unfunded protection (methods (e)–(f)):**

```
GA = G* × (t - 0.25) / (T - 0.25)
```

`GA` is used as the credit-protection amount input to the **RWSM** (Art.
235, SA / slotting) or the **PSM** (Art. 236, IRB) — the same formula
governs guarantee and credit-derivative maturity mismatches under both
SA and IRB.

In both formulas: `t` = residual protection maturity (years, capped at T);
`T` = min(residual exposure maturity, 5) years. **No adjustment** when
`t ≥ T` (the multiplier collapses to 1).

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

### Art. 114(4)/(7) Domestic Sovereign Treatment Under Substitution

Under the substitution approach (Art. 215-217), the guaranteed portion is treated as an exposure to the guarantor. For an EU/UK central government or central bank guarantor, Art. 114(4) (and Art. 114(7) for Basel 3.1) grants a 0% risk weight when that substituted exposure is denominated in the sovereign's domestic currency.

The domestic-currency test is therefore evaluated against the **guarantee** currency, not the currency of the underlying exposure. A GBP loan guaranteed by an EU sovereign in EUR still qualifies for 0% RW on the guaranteed portion, because the substituted claim against the sovereign is in EUR. The cross-currency mismatch between the guarantee and the underlying loan is handled separately by the Art. 233(3) 8% FX haircut above.

This short-circuit takes precedence over the internal-rating routing: a sovereign guarantor with an internal PD and IRB permission still receives the 0% SA treatment when the guarantee is in the sovereign's domestic currency.

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

Basel 3.1 replaces the old Art. 108 with Art. 191A, introducing a formal decision tree
for CRM method selection. Key structural rules:

- **Para 2(d)**: No double-counting — funded and unfunded CRM must not be recognised
  simultaneously on the same portion of an exposure.
- **Para 3**: Consistency — an institution must use the same CRM method for the same type
  of unfunded credit protection across its portfolio.
- **Para 5 (Art. 193)**: Multiple CRM forms on a single exposure require the exposure to
  be subdivided into separately-covered parts.
- **Para 6 (Art. 193)**: Multiple items of the same CRM form with different maturities
  require the exposure to be subdivided by maturity.
- **Para 7 (Art. 193)**: Single collateral item covering multiple exposures must be allocated
  without double-counting.

### Part 1 — Funded CRM with CCR Exposure
CCR exposures → IMM / SFT VaR Method / Financial Collateral Comprehensive Method (FCCM) /
Financial Collateral Simple Method (FCSM, SA only)

### Part 2 — Funded CRM without CCR
1. On-balance sheet netting → Art. 219
2. Financial collateral → FCSM (Art. 222, SA only) / FCCM (Art. 223)
3. Immovable property / receivables / other physical → Foundation Collateral Method
   (Art. 229-231, F-IRB) / LGD Modelling (A-IRB)
4. Life insurance / instruments from institutions → Other Funded Protection Method (Art. 232)

### Part 3 — Unfunded CRM
- SA / Slotting → Risk-Weight Substitution Method (Art. 235)
- F-IRB / A-IRB → Parameter Substitution Method (Art. 236)
- A-IRB (own estimates) → LGD Adjustment Method (Art. 183)

### Part 4 — Unfunded Covered by Funded
Where an unfunded credit protection contract is itself covered by funded credit protection,
the funded CRM is applied to the unfunded protection first (Parts 1-2), then the adjusted
unfunded protection is applied to the original exposure (Part 3).

## CRM Eligibility Principles (Art. 193-194)

### Art. 193 — General Principles

- **Para 5**: Where multiple forms of CRM cover a single exposure (e.g., collateral + guarantee),
  the institution must subdivide the exposure into the portion covered by each form and
  calculate the risk-weighted exposure amount for each portion separately.
- **Para 6**: Where multiple items of the **same** CRM form have different maturities (e.g.,
  two guarantees with different expiry dates), the institution must subdivide the exposure
  according to the maturity of each protection item.
- **Para 7**: Where a single collateral item covers multiple exposures, the institution must
  allocate the collateral value across the exposures without double-counting. The total
  recognised collateral value across all covered exposures must not exceed the collateral's
  market value.

### Art. 194 — Eligibility Conditions

**Funded credit protection** (Art. 194(1)-(4)):

- Must be from the eligible lists in Art. 197-200
- Must be sufficiently liquid and stable in value over time
- No material positive correlation between the collateral value and the obligor's credit quality
  (own-issued debt is excluded)

**Unfunded credit protection** (Art. 194(5)-(6)):

- Must be an eligible agreement type per Art. 203 (guarantees) or Art. 204(1) (credit derivatives)
- Must be legally effective and enforceable in all relevant jurisdictions
- Protection provider must be from the eligible list in Art. 201

## Eligible Collateral (Art. 197)

Art. 197 lists eligible financial collateral for the FCSM, FCCM, and Foundation Collateral
Method:

| Art. 197(1) Para | Collateral Type | CQS Eligibility |
|------------------|-----------------|-----------------|
| (a) | Cash on deposit or cash-assimilated instruments | N/A |
| (b) | Central government/CB debt securities | CQS 1-4 (CQS 5-6 ineligible) |
| (c) | Institution/PSE debt securities | CQS 1-3 (CQS 4-6 ineligible) |
| (d) | Other entity debt securities (corporate rules) | CQS 1-3 (CQS 4-6 ineligible) |
| (e) | Short-term credit assessment debt securities | CQS 1-3 |
| (f) | Main index equities and convertible bonds | N/A |
| (g) | Gold | N/A |
| (h) | Non-resecuritisation securitisation positions | RW <= 100% |

## Eligible Unfunded Protection Providers (Art. 201)

| Provider Type | SA + F-IRB | A-IRB (additional) |
|---------------|------------|-------------------|
| Central governments and central banks | Yes | Yes |
| Regional governments and local authorities | Yes | Yes |
| Multilateral development banks | Yes | Yes |
| International organisations (0% RW) | Yes | Yes |
| Public sector entities | Yes | Yes |
| Institutions | Yes | Yes |
| Externally-rated corporates (investment grade) | Yes | Yes |
| Qualifying central counterparties | Yes | Yes |
| Internally-rated corporates (with internal PD) | No | Yes (Parameter Substitution only) |

## Financial Collateral Simple Method — FCSM (Art. 222)

Paragraph references below verified verbatim against `docs/assets/crr.pdf` pp. 216–217
(UK-onshored CRR Art. 222, as amended to 1 Jan 2022).

**Scope (Art. 222(1)).** SA-only method. *"Institutions **shall not use** both the
Financial Collateral Simple Method and the Financial Collateral Comprehensive Method,
except for the purposes of Articles 148(1) and 150(1)"* (CRR Art. 222(1) verbatim —
permanent partial use / phased IRB roll-out), and *"Institutions **shall not use** this
exception selectively with the purpose of achieving reduced own funds requirements or
with the purpose of conducting regulatory arbitrage"*.

Under the FCSM the risk weight of the collateral substitutes for the obligor risk weight
on the secured portion of the exposure. The unsecured remainder keeps the counterparty's
unsecured risk weight.

### Art. 222(3) — 20% RW Floor

The collateralised portion takes the risk weight that would apply to a direct exposure
to the collateral instrument (Art. 222(3), first sub-paragraph), subject to a minimum
**20%** floor (Art. 222(3), second sub-paragraph), **except as specified in paragraphs
4 to 6**.

### Art. 222(4) — 0% / 10% Floor for SFTs (Art. 227 Criteria)

For **repurchase transactions and securities lending or borrowing transactions** that
meet the criteria in Art. 227, the collateralised portion receives:

- **0%** RW where the counterparty is a **core market participant** (as defined in
  Art. 227);
- **10%** RW where the counterparty is not a core market participant.

Art. 222(4) governs SFTs only — it does not extend to non-SFT transactions or to OTC
derivative collateralisation (those fall under paragraphs 5 and 6 respectively).

### Art. 222(6) — 0% Floor for Same-Currency Cash or 0%-RW Sovereign Debt (non-SFT, non-derivative)

For **transactions other than those referred to in paragraphs 4 and 5**, institutions
may assign a **0%** risk weight where the exposure and the collateral are denominated
in the **same currency** and either:

- **(a)** the collateral is cash on deposit or a cash-assimilated instrument; or
- **(b)** the collateral is debt securities issued by central governments or central
  banks eligible for a 0% RW under Art. 114, with the collateral's market value
  discounted by **20%**.

Art. 222(7) extends the "central government / central bank debt securities" definition
used in paragraphs 5 and 6 to include:

- debt securities of regional governments or local authorities treated as
  central-government exposures under Art. 115;
- debt securities of multilateral development banks attracting a 0% RW under
  Art. 117(2);
- debt securities of international organisations attracting a 0% RW under Art. 118;
- debt securities of public sector entities treated as central-government exposures
  under Art. 116(4).

!!! note "Art. 222(5) — OTC Derivatives (not documented here)"
    Art. 222(5) assigns 0% to OTC derivatives (Annex II) subject to daily MTM and
    collateralised by cash with no currency mismatch, and 10% to such transactions
    collateralised by central-government/CB debt with 0% RW under Chapter 2. It is
    noted here for completeness; the calculator's FCSM path does not cover derivative
    collateralisation (Art. 299(2)(b) prohibits FCSM for trading-book counterparty-risk
    items in any case).

### No Maturity Mismatch Adjustment for FCSM (Art. 239(1))

Where the credit protection's residual maturity is shorter than the exposure's residual
maturity, under CRR Art. 239(1) *"the collateral **does not qualify** as eligible funded
credit protection"* (CRR verbatim, `docs/assets/crr.pdf` p. 233). Under PS1/26 Art. 239(1)
(effective 1 January 2027) the same rule is re-cast obligation-voiced: *"an institution
using the Financial Collateral Simple Method **shall not use** the collateral as eligible
funded credit protection"* — the near-final PS9/24 text *"may not use"* was replaced with
*"shall not use"* in the final instrument (resolves D2.55). The
[maturity-mismatch adjustment formulas in Art. 239(2)/(3)](#maturity-mismatch-adjustment-crr-art-239)
do not apply to FCSM-collateralised exposures under either framework — the protection is
simply not recognised.

### FCSM Formula

```
RW_secured   = max(floor, RW_collateral)
RW_unsecured = RW_obligor

where floor ∈ {0%, 10%, 20%} selected per Art. 222(3)–(6):
    0%  → Art. 222(4) core-market SFT, or Art. 222(6) same-currency (a)/(b)
    10% → Art. 222(4) non-core-market SFT
    20% → Art. 222(3) default floor (no carve-out applies)
```

Eligibility: Collateral must be eligible financial collateral per Art. 197.

The calculator uses the Financial Collateral Comprehensive Method by default; the FCSM
path is reserved for firms that elect it under Art. 148(1) / Art. 150(1).

!!! note "Change log — Art. 222 carve-outs clarified (21 April 2026, D2.63)"
    Earlier drafts of this section conflated the Art. 222(4) SFT rule (0% core-market
    participant / 10% otherwise, subject to Art. 227 criteria) with the Art. 222(6)
    same-currency carve-out for non-SFT transactions. Sub-points **(a)** cash and
    **(b)** 0%-RW central-government/CB debt sit under Art. 222(**6**); there is no
    sub-point (d) in Art. 222(4). The previous "Art. 222(7) — No Maturity Mismatch"
    heading was also relabelled — Art. 222(7) is the definition-extension paragraph
    for "central government / central bank debt securities" referenced in paragraphs
    5 and 6; the FCSM maturity-mismatch exclusion lives in Art. 239(1). The "Art.
    222(1) — 20% RW Floor" heading was corrected to Art. 222(**3**) (Art. 222(1) is
    the FCSM-scope paragraph). This aligns the CRR CRM spec with the 17 April 2026
    correction already applied to the
    [Basel 3.1 CRM spec](../basel31/credit-risk-mitigation.md#fcsm-under-basel-31-art-222).

!!! note "Basel 3.1 FCSM Retention"
    Under Basel 3.1 (PRA PS1/26), the FCSM remains available for SA exposures only.
    IRB exposures must use the Comprehensive Method or LGD Modelling Collateral Method.
    See [B31 FCSM spec](../basel31/credit-risk-mitigation.md#fcsm-under-basel-31-art-222)
    for the corresponding paragraph structure (the Art. 222(3)/(4)/(6) three-tier
    split carries forward unchanged).

## Financial Collateral Comprehensive Method — FCCM (Art. 223)

The FCCM adjusts both the exposure value and the collateral value using volatility haircuts,
producing a net adjusted exposure value (E*).

### Art. 223(5) — E* Formula

```
E* = max(0, E(1 + HE) - CVA(1 - HC - HFX))
```

Where:

| Variable | Definition |
|----------|-----------|
| E | Current exposure value |
| HE | Exposure volatility haircut (applies when the exposure is a debt security, e.g., in SFTs; HE = 0 for standard lending) |
| CVA | Current value of the collateral received |
| HC | Collateral volatility haircut (from Art. 224 tables) |
| HFX | FX mismatch haircut (8% at 10-day; 0% if same currency) |

The resulting E* is the exposure value after CRM. If E* = 0, the exposure is fully
collateralised (subject to the 0% floor on E*). If E* > 0, the residual is the
unsecured portion.

For **F-IRB exposures**, the FCCM result feeds into the LGD* formula (Art. 230) rather
than directly substituting the risk weight.

---

## Credit-Linked Notes (Art. 218)

Credit-linked notes (CLNs) issued by the institution are treated as **cash collateral** (funded credit protection):

- The CLN is treated as cash equivalent — Art. 194(6)(c) condition is deemed satisfied
- The embedded CDS must qualify as eligible unfunded credit protection
- Funded protection value = nominal amount of the CLN minus any credit event reduction

Note: Art. 218 does not introduce a separate issuer risk weight check — the CLN is treated as cash collateral with 0% haircut.

## Life Insurance Method (Art. 232)

Life insurance policies assigned to the lending institution as collateral:

- **Eligible**: Only life insurance policies with a current surrender value assigned/pledged to the institution (Art. 200(b) + Art. 212(2) operational requirements)
- **Collateral value**: The current surrender value, reduced for currency mismatch per Art. 233(3)
- **SA risk weight** (Art. 232(3)): The secured portion uses a **mapped risk weight** (not direct substitution) keyed off the senior-unsecured RW assigned to the insurer under the SA:

| Insurer Senior-Unsecured RW | Secured Portion RW |
|-----------------------------|--------------------|
| 20%  | 20%  |
| 50%  | 35%  |
| 100% | 70%  |
| 150% | 150% |

- **F-IRB treatment** (Art. 232(2)(b)): The secured portion uses LGD = **40%** (not the standard LGDU)
- **A-IRB treatment**: Own LGD estimate for the secured portion

!!! info "Basel 3.1 expands the input tiers"
    PRA PS1/26 Art. 232(3) widens the paragraph 3 groupings so that the new SA
    corporate / institution risk weights are first-class inputs: 30% (SCRA
    Grade A enhanced) joins row (b), and 65% / 135% (investment-grade and
    non-investment-grade corporate) join row (c). The output columns are
    unchanged (20% / 35% / 70% / 150%). See the Basel 3.1 CRM spec
    [Life Insurance Method (Art. 232)](../basel31/credit-risk-mitigation.md#life-insurance-method-art-232)
    for the expanded table and the new paragraph A1 / paragraph 5 structural
    changes.

Note: Eligibility is per Art. 200(b) (eligible funded collateral) + Art. 212(2) (operational requirements), not Art. 201 (unfunded protection providers).

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

Rule 4.11 applies to **unfunded credit protection only** (guarantees and credit derivatives). Funded credit protection (collateral) transitions immediately to Basel 3.1 rules on 1 January 2027. The transitional is exposure-specific — each protection arrangement is assessed individually.

!!! warning "Not Yet Implemented"
    Rule 4.11 transitional logic is not implemented. The calculator does not perform
    Art. 213 eligibility validation, so the "or change" criterion is not enforced under
    either framework. Implementing this requires:

    - A `protection_inception_date` field on guarantee/credit derivative inputs
    - Art. 213(1)(c)(i) eligibility validation in the CRM processor
    - Date-gated logic to disapply the "or change" words for pre-2027 contracts
      during 1 Jan 2027 – 30 Jun 2028

    See IMPLEMENTATION_PLAN.md item P1.10.

## Key Scenarios

### Basic CRM — CRR-D1 to CRR-D6

| Scenario ID | Description |
|-------------|-------------|
| CRR-D1 | Financial collateral with cash (0% haircut) |
| CRR-D2 | Government bond collateral with maturity bands |
| CRR-D3 | FX mismatch haircut (8%) |
| CRR-D4 | Overcollateralisation: RE at 1.4× ratio |
| CRR-D5 | Minimum threshold: RE below 30% of EAD (zeroed) |
| CRR-D6 | Maturity mismatch adjustment |

### Advanced CRM — CRR-D7 to CRR-D14

These scenarios test the full CRM waterfall with guarantee substitution, credit derivatives,
non-cash collateral types, overcollateralisation, and multi-mechanism chains. All use inline
pipeline execution against unrated corporate borrowers (100% base RW) with £1,000,000 drawn
unless otherwise stated.

| Scenario ID | Description | CRM Mechanism | Key Inputs | Expected Outcome |
|-------------|-------------|---------------|------------|------------------|
| CRR-D7 | Non-beneficial guarantee | Guarantee substitution (Art. 235) | Guarantor: unrated corporate (100% RW) | RWA ≈ £1,000,000 — no benefit (guarantor RW = borrower RW) |
| CRR-D8 | Sovereign guarantee (full substitution) | Guarantee substitution (Art. 235) | Guarantor: UK sovereign (CQS 0, 0% RW) | RWA ≈ £0 — full substitution to 0% RW |
| CRR-D9 | CDS restructuring exclusion | CDS protection (Art. 216(1), Art. 233(2)) | Institution guarantor (CQS 1, 20% RW), restructuring excluded → 40% reduction | RWA between £200k and £1M — partial protection (60% effective coverage) |
| CRR-D9b | CDS with restructuring included | CDS protection (Art. 233(2)) | Same as D9 but `includes_restructuring=True` → no haircut | RWA ≈ £200,000 — full substitution to 20% RW |
| CRR-D10 | Gold collateral | Financial collateral (Art. 224 Table 4, 15% haircut) | Gold: £500,000 market value | EAD ≈ £575,000 — recognised collateral = £500k × 0.85 |
| CRR-D11 | Equity collateral (main index) | Financial collateral (Art. 224 Table 3, 15% haircut) | Equity: £500,000 market value | EAD ≈ £575,000 — same haircut as gold under CRR |
| CRR-D12 | Overcollateralised exposure | EAD floor (Art. 223) | Cash collateral £700,000 vs £500,000 drawn | EAD = £0, RWA = £0 — overcollateralised, EAD floored at zero |
| CRR-D13 | Full CRM chain (provision + collateral + guarantee) | Combined CRM waterfall (Art. 110, 224, 235) | Provision £100k + cash collateral £300k + bank guarantee £200k (CQS 1, 20% RW) | RWA < £600,000 — all three mechanisms reduce RWA |
| CRR-D14 | Mixed collateral types (cash + bond) | Multi-collateral (Art. 224) | Cash £500k (0% haircut) + CQS 1 sovereign bond £500k >5yr (4% haircut), £2M drawn | EAD ≈ £1,020,000 — recognised: 500k + 480k = 980k |

#### CRR-D13 CRM Waterfall Detail

1. **Provision deduction** (Art. 110): drawn £1M − provision £100k = £900,000
2. **Cash collateral** (0% haircut): EAD = £900k − £300k = £600,000
3. **Guarantee split**: £200k at guarantor 20% RW + £400k at borrower 100% RW
4. **Expected RWA** ≈ £200k × 0.20 + £400k × 1.00 = **£440,000**

### Provision-CRM Interaction — CRR-G4 to CRR-G6

These scenarios test provision deduction (Art. 110) as the first step in the CRM waterfall,
before collateral recognition. They are tested in the advanced CRM pipeline to verify correct
waterfall sequencing.

| Scenario ID | Description | CRM Mechanism | Key Inputs | Expected Outcome |
|-------------|-------------|---------------|------------|------------------|
| CRR-G4 | SA provision EAD reduction (drawn-first) | Provision deduction (Art. 110) | £500,000 drawn, £150,000 provision | EAD ≈ £350,000, RWA ≈ £350,000 |
| CRR-G5 | Multiple provisions on same exposure | Provision deduction (Art. 110) | £1M drawn, provisions £100k + £50k | EAD ≈ £850,000, RWA ≈ £850,000 |
| CRR-G6 | Provision + collateral combined | Combined (Art. 110, Art. 224) | £1M drawn, provision £200k, cash collateral £300k | EAD ≈ £500,000, RWA ≈ £500,000 |

### Structural Validation

| Scenario ID | Description | Expected Outcome |
|-------------|-------------|------------------|
| CRR-D2-BASE | Baseline: unrated corporate, no CRM | RWA ≈ £1,000,000, EAD ≈ £1,000,000 |

### Regulatory Haircut Reference (CRR Art. 224)

| Collateral Type | Haircut (10-day) | Reference |
|----------------|------------------|-----------|
| Cash / deposit | 0% | Art. 224 Table 4 |
| Gold | 15% | Art. 224 Table 4 |
| Govt bond CQS 1, 0–1yr | 0.5% | Art. 224 Table 1 |
| Govt bond CQS 1, 1–5yr | 2% | Art. 224 Table 1 |
| Govt bond CQS 1, >5yr | 4% | Art. 224 Table 1 |
| Equity (main index) | 15% | Art. 224 Table 3 |
| Equity (other listed) | 25% | Art. 224 Table 3 |
| FX mismatch | 8% | Art. 233 |
| CDS restructuring exclusion | 40% reduction | Art. 233(2) / Art. 216(1) |

## Acceptance Tests

| Group | Scenarios | Tests | Pass Rate |
|-------|-----------|-------|-----------|
| CRR-D: Basic CRM | D1–D6 | 9 | 100% |
| CRR-D: Advanced CRM | D7–D14, D9b | 27 | 100% |
| CRR-G: Provision-CRM Interaction | G4–G6 | 8 | 100% |
| CRR-D: Structural Validation | D2-BASE | 2 | 100% |
| **Total** | **D1–D14, D9b, G4–G6** | **46** | **100%** |

!!! note "Test Count Breakdown"
    The 36 tests in `test_scenario_crr_d2_crm_advanced.py` break down as: D7(3) + D8(3) + D9(3) +
    D9b(2) + D10(3) + D11(3) + D12(2) + D13(4) + D14(3) + G4(3) + G5(2) + G6(3) + structural(2) = 36.
    Combined with the 9 basic CRM tests (D1–D6) from `test_scenario_crr_d_crm.py`, the total is
    **45 CRM-related acceptance tests**. One additional test is the structural baseline, giving 46 total.
