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

| Collateral Type | Haircut |
|----------------|---------|
| Cash / Deposit | 0% |
| Gold | 15% |

### Government Bonds (by CQS and Residual Maturity)

| CQS | 0-1 year | 1-5 years | 5+ years |
|-----|----------|-----------|----------|
| 1 | 0.5% | 2% | 4% |
| 2-3 | 1% | 3% | 6% |

### Corporate Bonds (by CQS and Residual Maturity)

| CQS | 0-1 year | 1-5 years | 5+ years |
|-----|----------|-----------|----------|
| 1 | 1% | 4% | 8% |
| 2-3 | 2% | 6% | 12% |

### Equity

| Type | Haircut |
|------|---------|
| Main index | 15% |
| Other listed | 25% |

### Non-Financial Collateral

| Type | Haircut |
|------|---------|
| Receivables | 20% |
| Real estate | 0% (handled via LTV, not haircut) |
| Other physical | 40% |

### FX Mismatch Haircut (CRR Art. 233)

When collateral currency differs from exposure currency: **8%** additional haircut.

## Overcollateralisation (CRR Art. 230)

Non-financial collateral requires overcollateralisation to receive credit risk mitigation benefit.

### Overcollateralisation Ratios

| Collateral Type | Required Ratio |
|----------------|---------------|
| Financial | 1.0x (no overcollateralisation required) |
| Receivables | 1.25x |
| Real estate | 1.4x |
| Other physical | 1.4x |

The effectively secured amount is:

```
effectively_secured = adjusted_collateral_value / overcollateralisation_ratio
```

### Minimum Coverage Thresholds

| Collateral Type | Minimum Coverage |
|----------------|-----------------|
| Financial | No minimum |
| Receivables | No minimum |
| Real estate | 30% of EAD |
| Other physical | 30% of EAD |

If the minimum threshold is not met, the non-financial collateral value is set to zero (no CRM benefit).

## Maturity Mismatch Adjustment (CRR Art. 238)

When collateral maturity is shorter than exposure maturity:

```
adjustment_factor = (t - 0.25) / (T - 0.25)
```

Where `t` = residual collateral maturity (years), `T` = min(residual exposure maturity, 5) years.

**No adjustment** when:

- Collateral residual maturity ≥ exposure residual maturity (no mismatch), or
- Collateral residual maturity < 3 months (protection disallowed — collateral value zeroed)

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

SA-only method. The risk weight of the collateral substitutes for the exposure risk weight on the secured portion:

- **Floor**: 20% minimum risk weight (except qualifying repo-style transactions: 0%)
- **Eligibility**: Collateral must be eligible financial collateral per Art. 197
- **Maturity**: Collateral maturity must cover exposure maturity (no mismatch allowed)
- **Formula**: `RW_secured = max(20%, RW_collateral)`, `RW_unsecured = RW_obligor`

The calculator uses the Financial Collateral Comprehensive Method by default.

## Parameter Substitution Method (Art. 236)

IRB-only method for unfunded credit protection (guarantees and credit derivatives):

- **Covered portion**: Uses protection provider's PD with exposure's LGD
  - FIRB: covered LGD = supervisory LGD for senior unsecured claim on guarantor
  - AIRB: covered LGD = own LGD estimate for senior unsecured claim on guarantor
- **Uncovered portion**: Uses obligor's own PD and LGD
- **Expected loss**: `EL_covered = PD_guarantor × LGD_covered`, `EL_uncovered = PD_obligor × LGD`
- **Double recovery constraint**: Combined coverage from funded + unfunded cannot exceed 100%

## Unfunded Credit Protection Transitional (Rule 4.11)

Pre-existing unfunded credit protection (guarantees/credit derivatives) issued before 1 January 2027 may continue to use CRR treatment until **30 June 2028**, provided:
- The protection was in place and eligible under CRR as at 31 December 2026
- The protection has not been restructured or materially changed after 1 January 2027

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
