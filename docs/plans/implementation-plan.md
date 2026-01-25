# Implementation Plan

This document provides the detailed implementation plan including acceptance test scenarios, contract definitions, and implementation order.

## Overview

The implementation follows a **test-first approach** with phases:

1. **Phase 1**: User Acceptance Tests - Define expected inputs and outputs
2. **Phase 2**: Process Contracts - Establish interfaces between components
3. **Phase 3**: Implementation - Build components in dependency order
4. **Phase 4**: Acceptance Testing - Validate against expected outputs

**Regulatory Framework Prioritisation**:
1. **Phase A: CRR (Basel 3.0)** - Current UK implementation (effective until 31 Dec 2026)
2. **Phase B: Basel 3.1** - Future UK implementation (effective from 1 Jan 2027 per PRA PS9/24)

---

## CRR Acceptance Test Scenarios

Each scenario defines **specific inputs** and **expected outputs** with hand-calculated values based on current CRR rules (EU 575/2013 as onshored into UK law).

### Scenario Group CRR-A: Standardised Approach (SA)

| ID | Description | Key Inputs | Expected RWA | Regulatory Basis |
|----|-------------|------------|--------------|------------------|
| CRR-A1 | UK Sovereign exposure | £1m loan to UK Govt, CQS1 | £0 (0% RW) | CRR Art. 114 |
| CRR-A2 | Unrated corporate | £1m loan, no rating, no SME | £1m (100% RW) | CRR Art. 122 |
| CRR-A3 | Rated corporate CQS2 | £1m loan, A-rated | £500k (50% RW) | CRR Art. 122 |
| CRR-A4 | Institution ECRA CQS2 | £1m loan to UK bank, A-rated | £300k (30% RW) | CRR Art. 120 + UK deviation |
| CRR-A5 | Residential mortgage ≤80% LTV | £500k loan, 75% LTV | £175k (35% RW) | CRR Art. 125 |
| CRR-A6 | Residential mortgage >80% LTV | £850k loan, 85% LTV | £425k (50% avg RW) | CRR Art. 125 |
| CRR-A7 | Commercial real estate ≤50% LTV | £600k loan, 50% LTV | £300k (50% RW) | CRR Art. 126 |
| CRR-A8 | Off-balance sheet commitment | £1m undrawn (>1yr), 50% CCF | £500k EAD | CRR Art. 111 |
| CRR-A9 | Retail exposure | £50k loan to individual | £37.5k (75% RW) | CRR Art. 123 |
| CRR-A10 | SME with supporting factor | £1m loan, SME <€50m turnover | £761.9k (100% × 0.7619) | CRR Art. 501 |
| CRR-A11 | SME Retail with supporting factor | SME retail exposure | Retail RW × 0.7619 | CRR Art. 501 |
| CRR-A12 | Large Corporate (no supporting factor) | Turnover > €50m | 100% RW, no factor | CRR Art. 122 |

### Scenario Group CRR-B: Foundation IRB (F-IRB)

**Note**: F-IRB only applies to wholesale exposures (corporate, institution, sovereign). Retail exposures must use A-IRB or Standardised Approach.

| ID | Description | Key Inputs | Expected RWA | Notes |
|----|-------------|------------|--------------|-------|
| CRR-B1 | Corporate unsecured - low PD | PD=0.10%, LGD=45%, M=2.5y, EAD=£25m | £7.86m | CRR Art. 153, 161-163 |
| CRR-B2 | Corporate unsecured - high PD | PD=5.00%, LGD=45%, M=3.0y, EAD=£5m | £8.26m | CRR Art. 153, 161-162 |
| CRR-B3 | Subordinated exposure | PD=1.00%, LGD=75%, M=4.0y, EAD=£2m | £3.93m | CRR Art. 153, 161 |
| CRR-B4 | SME Corporate - firm size adj | PD=1.50%, LGD=45%, M=2.5y, T=€25m | Reduced R | CRR Art. 153(4), 161 |
| CRR-B5 | SME Corporate - both adjustments | PD=2.00%, LGD=45%, M=3.0y, T=€15m | R adj + SF 0.7619 | CRR Art. 153(4), 501 |
| CRR-B6 | Corporate at SME threshold | PD=1.00%, LGD=45%, M=2.5y, T=€50m | No firm size adj | CRR Art. 153, 161 |
| CRR-B7 | Long maturity exposure | PD=0.80%, LGD=45%, M=7y (capped 5y) | Maturity capped | CRR Art. 153, 162 |

### Scenario Group CRR-C: Advanced IRB (A-IRB)

| ID | Description | Key Inputs | Expected RWA | Notes |
|----|-------------|------------|--------------|-------|
| CRR-C1 | Corporate own estimates | PD=1%, LGD=35%, M=2.5y | Bank-estimated | CRR Art. 143 |
| CRR-C2 | Retail own estimates | PD=0.3%, LGD=15%, EAD=£100k | Retail formula | CRR Art. 154 |
| CRR-C3 | Specialised lending A-IRB | PD=1.5%, LGD=25% | Project finance | CRR Art. 153 |

**Note**: CRR A-IRB has NO LGD floors (unlike Basel 3.1 which has 25% unsecured floor).

### Scenario Group CRR-D: Credit Risk Mitigation (CRM)

| ID | Description | Key Inputs | Expected RWA | Notes |
|----|-------------|------------|--------------|-------|
| CRR-D1 | Cash collateral (SA) | £1m exposure, £500k cash | £500k EAD | CRR Art. 207 |
| CRR-D2 | Govt bond collateral | £1m exp, £600k gilts (5y) | Haircut applied | CRR Art. 224 |
| CRR-D3 | Equity collateral (main index) | £1m exp, £400k listed equity | 15% haircut | CRR Art. 224 |
| CRR-D4 | Guarantee substitution | £1m corp, £600k bank guarantee | Split RW | CRR Art. 213 |
| CRR-D5 | Maturity mismatch | £1m exp 5y, £500k collateral 2y | Adjusted value | CRR Art. 238 |
| CRR-D6 | Currency mismatch | £1m GBP exp, €500k collateral | 8% FX haircut | CRR Art. 224 |

### Scenario Group CRR-E: Specialised Lending (Slotting)

| ID | Description | Key Inputs | Expected RWA | Notes |
|----|-------------|------------|--------------|-------|
| CRR-E1 | Project finance - Strong | £10m, Strong category | £7m (70% RW) | CRR Art. 153(5) |
| CRR-E2 | Project finance - Good | £10m, Good category | £7m (70% RW) | Same as Strong |
| CRR-E3 | IPRE - Weak | £5m, Weak category | £5.75m (115% RW) | CRR Art. 153(5) |
| CRR-E4 | HVCRE - Strong | £5m, High volatility CRE | £3.5m (70% RW) | CRR Art. 153(5) |

**CRR Slotting Risk Weights:**

| Category | Non-HVCRE | HVCRE |
|----------|-----------|-------|
| Strong | 70% | 70% |
| Good | 70% | 70% |
| Satisfactory | 115% | 115% |
| Weak | 250% | 250% |
| Default | 0% (EL) | 0% (EL) |

### Scenario Group CRR-F: Supporting Factors

| ID | Description | Key Inputs | Expected RWA | Notes |
|----|-------------|------------|--------------|-------|
| CRR-F1 | SME Tier 1 only | Small exposure (£2m ≤ £2.2m) | 0.7619 factor | CRR Art. 501 |
| CRR-F2 | SME blended tiers | Medium exposure (£4m) | Blended factor | CRR Art. 501 |
| CRR-F3 | SME Tier 2 dominant | Large exposure (£10m) | ~0.85 factor | CRR Art. 501 |
| CRR-F4 | SME retail with Tier 1 | £500k retail | 0.7619 factor | CRR Art. 501 |
| CRR-F5 | Infrastructure supporting factor | Qualifying infrastructure | 0.75 factor | CRR Art. 501a |
| CRR-F6 | Large corporate - no factor | Turnover > £44m | No factor | CRR Art. 501 |
| CRR-F7 | At exposure threshold | £2.2m exactly | 0.7619 factor | CRR Art. 501 |

**CRR SME Supporting Factor - Tiered Approach (CRR2 Art. 501):**
- **Tier 1**: Exposures up to €2.5m (£2.2m): factor of 0.7619 (23.81% RWA reduction)
- **Tier 2**: Exposures above €2.5m (£2.2m): factor of 0.85 (15% RWA reduction)
- **Formula**: `factor = [min(E, threshold) × 0.7619 + max(E - threshold, 0) × 0.85] / E`

### Scenario Group CRR-G: Provisions & Impairments

| ID | Description | Key Inputs | Expected RWA | Notes |
|----|-------------|------------|--------------|-------|
| CRR-G1 | SA with specific provision | £1m exposure, £50k provision | £950k net | CRR Art. 110 |
| CRR-G2 | IRB EL shortfall | EL > provisions | T2 deduction | CRR Art. 159 |
| CRR-G3 | IRB EL excess | Provisions > EL | T2 credit (capped) | CRR Art. 62(d) |

### Scenario Group CRR-H: Complex/Combined

| ID | Description | Key Inputs | Expected RWA | Notes |
|----|-------------|------------|--------------|-------|
| CRR-H1 | Facility with multiple loans | £5m facility, 3 loans | Aggregate | Hierarchy test |
| CRR-H2 | Counterparty group | Parent + 2 subs | Rating inheritance | Org hierarchy |
| CRR-H3 | SME chain with factor | SME corp + supporting factor | 0.7619 applied | CRR Art. 501 |
| CRR-H4 | Full CRM chain | Exp + coll + guar + prov | All CRM steps | Integration |

---

## Basel 3.1 Acceptance Test Scenarios

These scenarios test the Basel 3.1 implementation per PRA PS9/24, effective 1 Jan 2027.

### Scenario Group B31-A: Standardised Approach (SA)

| ID | Description | Key Inputs | Expected RWA | Regulatory Basis |
|----|-------------|------------|--------------|------------------|
| B31-A1 | UK Sovereign exposure | £1m loan to UK Govt, CQS1 | £0 (0% RW) | CRE20.7 |
| B31-A2 | Unrated corporate | £1m loan, no rating | £1m (100% RW) | CRE20.26 |
| B31-A3 | Rated corporate CQS2 | £1m loan, A-rated | £500k (50% RW) | CRE20.25 |
| B31-A4 | Institution ECRA CQS2 | £1m loan to UK bank | £300k (30% RW) | UK deviation |
| B31-A5 | Residential mortgage 60% LTV | £500k loan | £100k (20% RW) | CRE20.71 |
| B31-A6 | Residential mortgage 85% LTV | £850k loan | £297.5k (35% RW) | CRE20.71 |
| B31-A10 | SME (no supporting factor) | £1m loan, SME | £1m (100% RW) | No factor in B3.1 |

### Scenario Group B31-F: Output Floor

| ID | Description | Key Inputs | Expected RWA | Notes |
|----|-------------|------------|--------------|-------|
| B31-F1 | Floor binding | IRB=£50m, SA=£100m | £72.5m | 72.5% floor |
| B31-F2 | Floor not binding | IRB=£80m, SA=£100m | £80m | IRB > floor |
| B31-F3 | Transitional 2027 | Year 2027, 50% floor | Phased floor | PRA PS9/24 |

**Output Floor Phase-In:**

| Year | Floor % |
|------|---------|
| 2027 | 50% |
| 2028 | 55% |
| 2029 | 60% |
| 2030 | 65% |
| 2031 | 70% |
| 2032+ | 72.5% |

---

## Key CRR Implementation Details

1. **1.06 Scaling Factor**: Applies to ALL IRB RWA under CRR (removed in Basel 3.1)
   ```
   CRR:      RWA = K × 12.5 × 1.06 × EAD × MA
   Basel 3.1: RWA = K × 12.5 × EAD × MA
   ```

2. **SME Firm Size Adjustment**: `R_adjusted = R - 0.04 × (1 - (max(S, 5) - 5) / 45)` for turnover < EUR 50m

3. **PD Floor**: Single 0.03% floor for all exposure classes (Basel 3.1 has differentiated floors)

4. **F-IRB LGDs**: 45% unsecured senior, 75% subordinated

5. **Maturity**: Floor 1 year, Cap 5 years

---

## Test Data Fixtures

Test datasets cover all key regulatory scenarios:

```
tests/fixtures/
├── counterparty/
│   ├── sovereign.py              # UK Govt, US Govt, Brazil, Argentina, etc.
│   ├── institution.py            # Banks (Barclays, HSBC, JPMorgan), CCPs
│   ├── corporate.py              # Large corp, SME, unrated, org hierarchy groups
│   ├── retail.py                 # Individuals, mortgages, SME retail, lending groups
│   └── specialised_lending.py    # Project finance, IPRE, HVCRE, object finance
├── exposures/
│   ├── facilities.py             # RCFs, term facilities, mortgages, hierarchy test
│   ├── loans.py                  # Drawn exposures for all acceptance scenarios
│   ├── contingents.py            # Off-balance sheet (LCs, guarantees, commitments)
│   └── facility_mapping.py       # Facility-to-loan/contingent relationships
├── collateral/
│   └── collateral.py             # Cash, bonds, equity, real estate, receivables
├── guarantee/
│   └── guarantee.py              # Sovereign, bank, corporate guarantees
├── provision/
│   └── provision.py              # SCRA/GCRA, IFRS9 stages 1-3
├── ratings/
│   └── ratings.py                # External (S&P/Moody's) and internal ratings
└── mapping/
    ├── org_mapping.py            # Parent-subsidiary relationships
    └── lending_mapping.py        # Retail lending group connections
```

---

## CRR Regulatory Parameters

### SA Risk Weights

#### Sovereigns (Art. 114)

| CQS | Risk Weight |
|-----|-------------|
| 1 | 0% |
| 2 | 20% |
| 3 | 50% |
| 4-5 | 100% |
| 6 | 150% |
| Unrated | 100% |

#### Institutions (Art. 120-121) - ECRA

| CQS | Risk Weight | UK Deviation |
|-----|-------------|--------------|
| 1 | 20% | 20% |
| 2 | 50% | **30%** |
| 3 | 50% | 50% |
| 4-5 | 100% | 100% |
| 6 | 150% | 150% |
| Unrated | 40% | 40% |

#### Corporates (Art. 122)

| CQS | Risk Weight |
|-----|-------------|
| 1 | 20% |
| 2 | 50% |
| 3-4 | 100% |
| 5-6 | 150% |
| Unrated | 100% |

#### Real Estate (Art. 125-126)

**Residential (Art. 125):**
- LTV ≤80%: 35%
- LTV >80%: Split treatment (35% on 80%, 75% on excess)

**Commercial (Art. 126):**
- LTV ≤50%: 50% (where rental income >1.5x interest)
- Otherwise: 100%

### CCFs (Art. 111)

| Category | CCF |
|----------|-----|
| Full risk | 100% |
| Medium risk | 50% |
| Medium-low risk | 20% |
| Low risk | 0% |

### Supervisory Haircuts (Art. 224)

| Collateral Type | Haircut |
|-----------------|---------|
| Cash | 0% |
| CQS 1 govt bonds ≤1y | 0.5% |
| CQS 1 govt bonds 1-5y | 2% |
| CQS 1 govt bonds >5y | 4% |
| Main index equity | 15% |
| Other equity | 25% |
| Currency mismatch | +8% |

### F-IRB LGDs

| Collateral Type | LGD |
|-----------------|-----|
| Unsecured senior | 45% |
| Subordinated | 75% |
| Financial collateral | 0% |
| Receivables | 35% |
| Commercial/residential RE | 35% |

---

## Next Steps

### Upcoming Work

**Fixture Completion** (to enable remaining acceptance tests):
- [ ] IRB exposures with PD values (for CRR-B, CRR-C)
- [ ] CRM scenario exposures with collateral/guarantees (for CRR-D)
- [ ] Specialised lending exposures with slotting categories (for CRR-E)
- [ ] Supporting factor scenario exposures (for CRR-F)
- [ ] Provision scenario exposures with EL data (for CRR-G)
- [ ] Complex/combined scenario exposures (for CRR-H)

**Basel 3.1 Extension**:
- [ ] Basel 3.1 expected outputs
- [ ] Basel 3.1 acceptance tests
- [ ] Updated risk weight tables
- [ ] Output floor phase-in validation

---

## Related Documentation

- [Development Roadmap](roadmap.md) - Current status and phase tracking
- [Testing Guide](../development/testing.md) - How to run tests
- [Framework Comparison](../user-guide/regulatory/comparison.md) - CRR vs Basel 3.1 differences
