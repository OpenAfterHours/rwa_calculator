# Credit Risk Mitigation Specification

Collateral haircuts, overcollateralisation, FX mismatch, maturity mismatch, and guarantee substitution.

**Regulatory Reference:** CRR Articles 192-241

**Test Group:** CRR-D

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
| 1-2 | 1% | 4% | 6% |
| 3 | 2% | 6% | 8% |

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

Where `t` = residual collateral maturity, `T` = 5 years.

**No adjustment** when:

- Collateral residual maturity ≥ 5 years, or
- Exposure residual maturity ≤ 3 months

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
