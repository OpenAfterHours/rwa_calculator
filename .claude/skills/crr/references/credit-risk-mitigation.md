# CRR Credit Risk Mitigation

Quick-reference for collateral haircuts, overcollateralisation, and guarantee substitution.

**Regulatory Reference:** CRR Articles 192-241

---

## Financial Collateral Haircuts (Art. 224)

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

## FX Mismatch Haircut (Art. 233)

When collateral currency differs from exposure currency: **8%** additional haircut.

## Overcollateralisation Ratios (Art. 230)

| Collateral Type | Required Ratio | Minimum Coverage |
|----------------|---------------|-----------------|
| Financial | 1.0x | No minimum |
| Receivables | 1.25x | No minimum |
| Real estate | 1.4x | 30% of EAD |
| Other physical | 1.4x | 30% of EAD |

```
effectively_secured = adjusted_collateral_value / overcollateralisation_ratio
```

If minimum threshold is not met, non-financial collateral value is zeroed.

## Maturity Mismatch Adjustment (Art. 238)

When collateral maturity < exposure maturity:

```
adjustment_factor = (t - 0.25) / (T - 0.25)
```

Where t = residual collateral maturity, T = min(residual exposure maturity, 5) years.

- Collateral maturity >= exposure maturity: no adjustment
- Collateral maturity < 3 months: protection disallowed (value zeroed)

## Multi-Level Collateral Allocation

1. **Exposure level** — collateral pledged directly against an exposure
2. **Facility level** — shared pro-rata across the facility's exposures
3. **Counterparty level** — shared pro-rata across all counterparty exposures

Financial and non-financial collateral tracked separately.

## Guarantee Substitution (Art. 213-217)

The guarantor's risk weight replaces the borrower's risk weight for the guaranteed
portion, but only when the guarantor RW < borrower RW (beneficial substitution).

Blended RW for partial guarantees:

```
RW_blended = (unguaranteed x borrower_RW + guaranteed x guarantor_RW) / EAD
```

---

> **Full detail:** `docs/specifications/crr/credit-risk-mitigation.md`
