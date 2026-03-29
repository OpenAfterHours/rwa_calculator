# Framework Comparison

This page provides a comprehensive comparison between CRR (Basel 3.0) and Basel 3.1 frameworks.

## Overview

| Aspect | CRR (Basel 3.0) | Basel 3.1 |
|--------|-----------------|-----------|
| **Effective** | Until 31 Dec 2026 | From 1 Jan 2027 |
| **Philosophy** | Risk sensitivity | Comparability + floors |
| **IRB Benefit** | Unlimited | Floored at 72.5% of SA |
| **Supporting Factors** | SME + Infrastructure | None |
| **Scaling** | 1.06 multiplier | None |

## Exposure Class Restructuring

Basel 3.1 restructures SA exposure classes with an explicit priority waterfall
(PRA PS1/26 Art. 112, Table A2). The most significant structural change is that
**real estate** becomes a standalone exposure class, rather than being a sub-treatment
of secured corporate or retail exposures under CRR Art. 125/126.

**New priority waterfall (highest to lowest):**

1. Securitisation positions
2. CIU units/shares
3. Subordinated debt, equity and own funds instruments
4. Exposures associated with particularly high risk
5. Exposures in default
6. Eligible covered bonds
7. **Real estate exposures** (new standalone class)
8. International organisations
9. Multilateral development banks
10. Institutions
11. Central governments / central banks
12. Regional governments / local authorities
13. Public sector entities
14. Retail exposures
15. Corporates
16. Other items

Where an exposure meets multiple criteria, the highest-priority class applies.

## IRB Treatment

### Scaling Factor

=== "CRR"

    ```python
    # 6% uplift on all IRB RWA
    RWA = K × 12.5 × EAD × MA × 1.06
    ```

=== "Basel 3.1"

    ```python
    # No scaling factor
    RWA = K × 12.5 × EAD × MA
    ```

**Impact:** ~5.7% reduction in IRB RWA (before output floor)

### Output Floor

=== "CRR"

    No output floor. IRB RWA can be significantly below SA.

    ```
    Example:
    - SA RWA: £100m
    - IRB RWA: £30m
    - Final RWA: £30m (70% capital saving)
    ```

=== "Basel 3.1"

    72.5% floor limits IRB benefit.

    ```
    Example:
    - SA RWA: £100m
    - IRB RWA: £30m
    - Floor: £100m × 72.5% = £72.5m
    - Final RWA: £72.5m (27.5% capital saving only)
    ```

### PD Floors

| Exposure Class | CRR | Basel 3.1 |
|----------------|-----|-----------|
| Corporate | 0.03% | 0.05% |
| Large Corporate | 0.03% | 0.05% |
| Institution/Bank | 0.03% | 0.05% |
| Retail Mortgage | 0.03% | 0.05% |
| Retail QRRE (Transactor) | 0.03% | 0.03% |
| Retail QRRE (Revolver) | 0.03% | 0.10% |
| Retail Other | 0.03% | 0.05% |

### LGD Floors (A-IRB Only)

| Collateral Type | CRR | Basel 3.1 |
|-----------------|-----|-----------|
| Unsecured Senior | None | 25% |
| Unsecured Subordinated | None | 50% |
| Financial Collateral | None | 0% |
| Receivables | None | 10%* |
| Commercial RE | None | 10%* |
| Residential RE | None | 5%* |
| Other Physical | None | 15%* |

*Values reflect PRA PS1/26 implementation. BCBS standard values differ (Receivables: 15%, CRE: 10%, RRE: 10%, Other Physical: 20%).

### F-IRB Supervisory LGD

| Exposure Type | CRR | Basel 3.1 | Change |
|---------------|-----|-----------|--------|
| Corporate/Institution (Senior) | 45% | **40%** | -5pp |
| Corporate/Institution (Subordinated) | 75% | **75%** | - |
| Secured - Financial Collateral | 0% | **0%** | - |
| Secured - Receivables | 35% | **20%** | -15pp |
| Secured - CRE/RRE | 35% | **20%** | -15pp |
| Secured - Other Physical | 40% | **25%** | -15pp |

### IRB Approach Restrictions

A-IRB (own-LGD estimates) is removed for several exposure types:

| Exposure Type | CRR | Basel 3.1 |
|---------------|-----|-----------|
| Large Corporate (>£500m) | F-IRB or A-IRB | **F-IRB only** |
| Financial Sector Entities | F-IRB or A-IRB | **F-IRB only** |
| Bank/Institution | F-IRB or A-IRB | **F-IRB only** |
| Equity | IRB | **SA only** |

**IRB 10% RW floor for UK residential mortgages (PRA-specific):** Non-defaulted retail exposures
secured by UK residential property must have a minimum risk weight of **10%** under IRB,
regardless of model output (applied as post-model adjustment).

### Large Corporate Correlation Multiplier

Under Basel 3.1, large corporates (consolidated revenue > £500m) receive a **1.25x** correlation multiplier on their asset correlation (CRE31.5). This increases capital requirements for large corporate exposures treated under F-IRB.

### A-IRB CCF Floor

Under Basel 3.1, A-IRB own-estimate CCFs must be at least **50% of the SA CCF** for the same item type (CRE32.27). This constrains A-IRB benefit from low CCF estimates.

## Supporting Factors

### SME Supporting Factor

=== "CRR (Article 501)"

    **Eligibility:**
    - Turnover ≤ EUR 50m
    - Corporate, Retail, or Real Estate secured

    **Calculation:**
    ```python
    # Tiered approach
    threshold = EUR 2.5m  # GBP 2.2m

    if exposure <= threshold:
        factor = 0.7619  # 23.81% reduction
    else:
        factor = (threshold × 0.7619 + (exposure - threshold) × 0.85) / exposure
    ```

    | Exposure | Factor | RWA Reduction |
    |----------|--------|---------------|
    | £1m | 0.7619 | 23.81% |
    | £2.2m | 0.7619 | 23.81% |
    | £5m | 0.811 | 18.9% |
    | £10m | 0.831 | 16.9% |

=== "Basel 3.1"

    **SME Supporting Factor: REMOVED**

    No capital relief for SME exposures.

### Infrastructure Supporting Factor

=== "CRR"

    **Eligibility:**
    - Qualifying infrastructure project finance
    - Revenues in EUR/GBP or hedged

    **Calculation:**
    ```python
    factor = 0.75  # 25% reduction
    RWA_adjusted = RWA × 0.75
    ```

=== "Basel 3.1"

    **Infrastructure Factor: REMOVED**

    No capital relief for infrastructure projects.

## SA Risk Weights

### Corporate

| CQS | CRR | Basel 3.1 | Change |
|-----|-----|-----------|--------|
| CQS1 (AAA-AA-) | 20% | 20% | - |
| CQS2 (A+-A-) | 50% | 50% | - |
| CQS3 (BBB+-BBB-) | 100% | 75% | -25pp |
| CQS4 (BB+-BB-) | 100% | 100% | - |
| CQS5 (B+-B-) | 150% | **100%** | -50pp |
| CQS6 (CCC+/Below) | 150% | 150% | - |
| Unrated | 100% | 100% | - |

#### New Basel 3.1 Corporate Sub-Categories (CRE20.47-49)

| Sub-Category | Basel 3.1 RW | Criteria |
|-------------|-------------|----------|
| Investment Grade | **65%** | Publicly traded + investment grade rating |
| SME Corporate | **85%** | Turnover ≤ EUR 50m, unrated |

### Institution Exposures

Basel 3.1 replaces the CRR institution risk weight approach with two distinct methods:

**Rated institutions — ECRA (External Credit Risk Assessment Approach):**

| CQS | CRR | Basel 3.1 | Basel 3.1 (≤3m) | Change |
|-----|-----|-----------|-----------------|--------|
| CQS 1 | 20% | 20% | 20% | — |
| CQS 2 | 50% | **30%** | 20% | -20pp |
| CQS 3 | 50% | 50% | 20% | — |
| CQS 4 | 100% | 100% | 50% | — |
| CQS 5 | 100% | 100% | 50% | — |
| CQS 6 | 150% | 150% | 150% | — |

**Unrated institutions — SCRA (Standardised Credit Risk Assessment Approach):**

| Grade | Risk Weight (>3m) | Risk Weight (≤3m) | Criteria |
|-------|-------------------|-------------------|----------|
| A | 40% | 20% | CET1 ≥ 14%, Leverage ≥ 5% |
| B | 75% | 50% | CET1 ≥ 5.5%, Leverage ≥ 3% |
| C | 150% | 150% | Below minimum requirements |

Under CRR, unrated institutions use the sovereign-based approach. The SCRA represents
a fundamentally different methodology based on the institution's own capital adequacy.

**Sovereign floor:** Unrated institution risk weights cannot be lower than their sovereign's
risk weight.

### Residential Real Estate

| LTV | CRR | Basel 3.1 (Whole Loan) | Basel 3.1 (Income-Producing) |
|-----|-----|------------------------|------------------------------|
| ≤ 50% | 35% | **20%** | **30%** |
| 50-60% | 35% | **25%** | **35%** |
| 60-70% | 35% | **30%** | **45%** |
| 70-80% | 35% | **40%** | **60%** |
| 80-90% | 75% | **50%** | **75%** |
| 90-100% | 75% | **70%** | **105%** |
| > 100% | Cpty RW | Cpty RW | Cpty RW |

### Commercial Real Estate

| Scenario | CRR | Basel 3.1 |
|----------|-----|-----------|
| LTV ≤ 60%, Income-Producing | 100% | **70%** |
| LTV > 60%, Income-Producing | 100% | **110%** |

### ADC Exposures (CRE20.85)

| Type | CRR | Basel 3.1 |
|------|-----|-----------|
| Acquisition, Development & Construction | 100% | **150%** |

### Retail Exposures

| Type | CRR | Basel 3.1 | Change |
|------|-----|-----------|--------|
| Regulatory Retail QRRE | 75% | 75% | — |
| Regulatory Retail Transactor | 75% | **45%** | -30pp |
| Payroll / Pension Loans | 75% | **35%** | -40pp |
| Retail Other | 75% | 75% | — |

Transactor status requires full repayment each billing cycle. Payroll/pension loans are a
new Basel 3.1 category for loans repaid directly from salary or pension.

### Currency Mismatch Multiplier (CRE20.76)

!!! warning "Not Yet Implemented"
    The currency mismatch risk weight multiplier is not yet implemented in the calculator.

| Scenario | CRR | Basel 3.1 |
|----------|-----|-----------|
| Unhedged FX retail / residential RE | No adjustment | **1.5x RW multiplier** (max 150% RW) |

Applies when lending currency differs from borrower's income currency and the
exposure is not hedged. Distinct from the 8% FX collateral haircut in CRM.

### Subordinated Debt

| Type | CRR | Basel 3.1 |
|------|-----|-----------|
| Subordinated Debt | 100-150% | **150%** (flat) |

### Equity Exposures

| Type | CRR | Basel 3.1 (Fully Phased) | Change |
|------|-----|--------------------------|--------|
| Standard listed equities | 100% | **250%** | +150pp |
| Higher-risk (unlisted, < 5 yrs) | 250-400% | **400%** | Standardised |
| Speculative / venture capital | 400% | **400%** | — |

IRB is **removed** for equity under Basel 3.1 — SA only.

**Transitional phase-in schedule:**

| Year | Standard | Higher-Risk |
|------|----------|-------------|
| 2027 | 130% | 160% |
| 2028 | 160% | 220% |
| 2029 | 190% | 280% |
| 2030+ | 250% | 400% |

### Defaulted Exposures

| Scenario | CRR | Basel 3.1 |
|----------|-----|-----------|
| Unsecured, provisions ≥ 20% | 100% | 100% |
| Unsecured, provisions < 20% | 150% | 150% |
| Residential RE (not cash-flow dependent) | 100-150% | **100%** (flat) |

Provision-coverage-based differentiation (CRE20.87-90) is not currently implemented in the
SA calculator — defaulted treatment with provision coverage is handled through IRB. The flat
100% for defaulted residential RE (not cash-flow dependent) is a Basel 3.1 simplification.

### Regional Governments and Local Authorities

Basel 3.1 introduces a tiered approach (PRA PS1/26 Art. 115):

| Type | CRR | Basel 3.1 |
|------|-----|-----------|
| Scottish/Welsh/NI governments | Sovereign-based | **0%** (treated as UK sovereign) |
| UK local authorities (GBP) | Sovereign-based | **20%** |
| Rated RGLAs | Sovereign-based | Own ECAI rating (20-150%) |
| Unrated RGLAs | Sovereign-based | Based on sovereign CQS |

### Covered Bonds

| CQS | CRR | Basel 3.1 |
|-----|-----|-----------|
| CQS 1 | 10% | 10% |
| CQS 2 | 20% | 20% |
| CQS 3 | 20% | 20% |
| CQS 4-5 | 50% | 50% |
| CQS 6 | 100% | 100% |
| Unrated | Derived from issuer | Derived from issuer (20%→10%, 50%→25%, 100%→50%) |

## Credit Conversion Factors

| Item Type | CRR | Basel 3.1 |
|-----------|-----|-----------|
| Unconditionally Cancellable | 0% | **10%** |
| Other Commitments < 1yr | 20% | 40% |
| Other Commitments ≥ 1yr | 50% | 40% |
| Trade Letters of Credit | 20% | 20% |
| NIFs/RUFs | 50% | 50% |
| Direct Credit Substitutes | 100% | 100% |

## Slotting Risk Weights

### Project Finance

| Category | CRR (≥2.5yr) | CRR (<2.5yr) | Basel 3.1 (Pre-Op) | Basel 3.1 (Operational) |
|----------|--------------|--------------|---------------------|------------------------|
| Strong | 70% | 50% | **80%** | 70% |
| Good | 90% | 70% | **100%** | 90% |
| Satisfactory | 115% | 115% | **120%** | 115% |
| Weak | 250% | 250% | **350%** | 250% |
| Default | 0% | 0% | 0% (EL) | 0% (EL) |

### Other Specialised Lending (OF, CF, IPRE)

| Category | CRR (≥2.5yr) | CRR (<2.5yr) | Basel 3.1 |
|----------|--------------|--------------|-----------|
| Strong | 70% | 50% | 70% |
| Good | 90% | 70% | 90% |
| Satisfactory | 115% | 115% | 115% |
| Weak | 250% | 250% | 250% |
| Default | 0% | 0% | 0% (EL) |

### HVCRE

| Category | CRR (≥2.5yr) | CRR (<2.5yr) | Basel 3.1 |
|----------|--------------|--------------|-----------|
| Strong | 95% | 70% | 95% |
| Good | 120% | 95% | 120% |
| Satisfactory | 140% | 140% | 140% |
| Weak | 250% | 250% | 250% |
| Default | 0% | 0% | 0% (EL) |

**Note:** Under CRR, HVCRE has a separate risk weight table (Art. 153(5) Table 2) with higher weights than non-HVCRE.

## SA Specialised Lending (Art. 122A-122B)

!!! warning "Not Yet Implemented"
    SA specialised lending risk weights are described here for regulatory completeness
    but are not yet implemented in the calculator.

Basel 3.1 introduces explicit SA risk weights for specialised lending, separate from
the IRB slotting approach above:

| Type | CRR (SA) | Basel 3.1 (SA) |
|------|----------|----------------|
| Object Finance | Corporate RW | **100%** |
| Commodities Finance | Corporate RW | **100%** |
| Project Finance (pre-operational) | Corporate RW | **130%** |
| Project Finance (operational) | Corporate RW | **100%** |
| Project Finance (high-quality operational) | Corporate RW | **80%** |

Under CRR, specialised lending under SA simply uses the corporate risk weight.
Basel 3.1 provides differentiated weights that recognise the specific risk profile
of each type.

## Credit Risk Mitigation Changes

### Method Taxonomy

Basel 3.1 restructures CRM with clearer method names and explicit applicability rules
(PRA PS1/26 Art. 191A):

| Method | CRR Name | Applies To |
|--------|----------|-----------|
| Financial Collateral Simple | Same | SA only |
| Financial Collateral Comprehensive | Same | SA + IRB |
| **Foundation Collateral Method** | Various IRB collateral articles | F-IRB |
| **Parameter Substitution Method** | Art. 236 substitution | F-IRB (unfunded) |
| **LGD Adjustment Method** | Art. 183 | A-IRB (unfunded) |

### Haircut Changes

Significant increases for equities and long-dated bonds. Maturity bands expand from 3 to 5.

| Collateral Type | CRR | Basel 3.1 | Change |
|-----------------|-----|-----------|--------|
| Main index equities | 15% | **25%** | +10pp |
| Other listed equities | 25% | **35%** | +10pp |
| Govt bonds CQS 2-3 (10y+) | 6% | **12%** | +6pp |
| Corp bonds CQS 1 (10y+) | 8% | **12%** | +4pp |
| Corp bonds CQS 2-3 (5-10y / 10y+) | 12% | **15%** | +3pp |

CRR maturity bands: 0-1y, 1-5y, 5y+.
Basel 3.1 maturity bands: 0-1y, 1-3y, 3-5y, 5-10y, 10y+.

### Overcollateralisation (Foundation Collateral Method)

| Collateral Type | Overcoll. Ratio | Minimum EAD Coverage |
|-----------------|-----------------|---------------------|
| Financial | 1.0x | None |
| Receivables | 1.25x | None |
| RE / Other Physical | 1.4x | 30% of EAD |

### Unfunded Credit Protection

New requirement: all unfunded credit protection must include **"change of control"** provisions.
Transitional relief for contracts entered before 1 January 2027 until June 2028.

## Impact Analysis

### Low-Risk Portfolios (Strong IRB Models)

```
Scenario: High-quality corporate portfolio
- PD: 0.10%
- LGD: 40%
- SA RW equivalent: 80%

CRR:
- IRB K: ~2%
- IRB RW: ~25% (after 1.06)
- Capital saving vs SA: 69%

Basel 3.1:
- IRB K: ~1.9% (no scaling)
- IRB RW: ~24%
- Floor: 80% × 72.5% = 58%
- Final RW: 58%
- Capital saving vs SA: 28%
```

### SME Portfolio

```
Scenario: £5m SME exposure, 100% SA RW

CRR:
- SME Factor: 0.811
- Effective RW: 81.1%
- Saving: 18.9%

Basel 3.1:
- SME Factor: None
- Effective RW: 100%
- Saving: 0%
```

### Infrastructure Project

```
Scenario: Qualifying infrastructure, 100% SA RW

CRR:
- Infrastructure Factor: 0.75
- Effective RW: 75%
- Saving: 25%

Basel 3.1:
- Infrastructure Factor: None
- Effective RW: 100%
- Saving: 0%
```

## Configuration Comparison

=== "CRR"

    ```python
    from datetime import date
    from rwa_calc.contracts.config import CalculationConfig

    config = CalculationConfig.crr(
        reporting_date=date(2026, 12, 31),
    )

    # Internally sets:
    # - scaling_factor: 1.06
    # - output_floor: None
    # - pd_floor: 0.0003 (uniform)
    # - lgd_floors: None
    ```

=== "Basel 3.1"

    ```python
    from datetime import date
    from rwa_calc.contracts.config import CalculationConfig

    config = CalculationConfig.basel_3_1(
        reporting_date=date(2027, 1, 1),
    )

    # Internally sets:
    # - scaling_factor: 1.0 (removed)
    # - output_floor: 72.5%
    # - pd_floors: differentiated by class
    # - lgd_floors: by collateral type
    ```

## Summary of Capital Impact

| Exposure Type | CRR → Basel 3.1 Impact |
|---------------|------------------------|
| Low-risk IRB | **Increase** (output floor) |
| SME | **Increase** (factor removal) |
| Infrastructure | **Increase** (factor removal) |
| Equity | **Increase** (250%/400% from 100%) |
| Unhedged FX Retail/RE | **Increase** (1.5x multiplier) |
| High LTV Mortgages | **Decrease** (better SA RWs) |
| Low LTV Mortgages | **Decrease** (better SA RWs) |
| High-risk Corporate | **Decrease** (CQS5 reduction) |
| Retail Transactor | **Decrease** (45% from 75%) |
| Standard Corporate | Neutral |

## Transition Planning

### Key Dates

| Date | Event |
|------|-------|
| Sep 2024 | PRA PS1/26 published |
| 2025-2026 | Parallel running recommended |
| 1 Jan 2027 | Basel 3.1 effective |
| 2027-2032 | Output floor phase-in |

### Recommended Actions

1. **Impact Assessment**: Run calculations under both frameworks
2. **Data Quality**: Ensure LTV data available for SA RE
3. **Model Updates**: Review IRB models for floor compliance
4. **Process Changes**: Update reporting for dual calculation

## See Also

- [CRR Details](../user-guide/regulatory/crr.md) — current framework in depth
- [Basel 3.1 Details](../user-guide/regulatory/basel31.md) — future framework in depth
- [Reporting Differences](reporting-differences.md) — COREP template changes
- [Impact Analysis](impact-analysis.md) — comparison tooling and capital attribution
- [Technical Reference](technical-reference.md) — developer-facing parameter specification
- [Configuration Guide](../user-guide/configuration.md) — setting up both frameworks
