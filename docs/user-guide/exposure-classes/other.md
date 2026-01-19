# Other Exposure Classes

This page covers exposure classes not detailed in previous sections: Equity, Defaulted, PSE, MDB, RGLA, and other specialized categories.

## Equity Exposures

### Definition

Equity exposures include:
- Direct equity holdings
- Investments in funds
- Private equity
- Venture capital investments
- Subordinated debt with equity characteristics

### SA Risk Weights

| Type | CRR | Basel 3.1 |
|------|-----|-----------|
| Exchange-traded equities | 100% | 100% |
| Other listed equities | 100% | 100% |
| Private equity / Venture capital | 150% | **400%** |
| Speculative investments | 150% | 400% |

### IRB Treatment

!!! warning "Basel 3.1"
    IRB approaches for equity are **removed** under Basel 3.1. Only SA is permitted.

**CRR IRB Options:**

| Approach | Description | Minimum RW |
|----------|-------------|------------|
| Simple | Fixed risk weights | 190-370% |
| PD/LGD | Use corporate formula | 200% |
| Internal models | VaR-based | 200% |

**Simple Risk Weight Approach:**

| Equity Type | Risk Weight |
|-------------|-------------|
| Exchange-traded | 190% |
| Other | 290% |
| Private equity | 370% |

### Calculation Example

**Exposure:**
- £10m listed equity portfolio
- Mix of exchange-traded and private equity

**CRR (Simple Approach):**
```python
# Exchange-traded: £7m
RWA_exchange = £7,000,000 × 190% = £13,300,000

# Private equity: £3m
RWA_private = £3,000,000 × 370% = £11,100,000

# Total
Total_RWA = £24,400,000
```

**Basel 3.1:**
```python
# Exchange-traded: £7m
RWA_exchange = £7,000,000 × 100% = £7,000,000

# Private equity: £3m
RWA_private = £3,000,000 × 400% = £12,000,000

# Total
Total_RWA = £19,000,000
```

## Defaulted Exposures

### Definition

An exposure is classified as defaulted when:
- Past due > 90 days on a material amount
- Unlikely to pay in full without recourse to collateral
- Subject to distressed restructuring
- Bankruptcy or insolvency proceedings initiated
- Similar credit quality deterioration

### SA Risk Weights

| Provision Coverage | CRR | Basel 3.1 |
|--------------------|-----|-----------|
| < 20% | **150%** | 150% |
| 20% - 50% | **100%** | 100% |
| ≥ 50% | **100%** | **50-100%** |

**Basel 3.1 High Coverage:**
- ≥50% specific provisions: 50% RW for secured portion
- Unsecured portion: 100% RW

### IRB Treatment

For defaulted exposures under IRB:
- PD = **100%**
- LGD = "best estimate LGD" (ELGD)
- Expected Loss = LGD × EAD

```python
# Defaulted exposure IRB
PD = 1.00  # 100%
LGD = best_estimate_lgd  # Bank's expectation of loss
EL = LGD × EAD

# K formula still applies but with PD = 100%
# Results in RWA reflecting unexpected loss only
```

### Calculation Example

**Exposure:**
- £5m defaulted corporate loan
- Specific provision: £1.5m (30% coverage)
- Collateral value: £2m

**SA Calculation:**
```python
# Net exposure
Net_EAD = £5,000,000 - £1,500,000 = £3,500,000

# Provision coverage 30% → 100% RW
Risk_Weight = 100%

RWA = £3,500,000 × 100% = £3,500,000
```

## Public Sector Entities (PSE)

### Definition

PSEs are non-commercial administrative bodies:
- Regional governments
- Local authorities
- Administrative bodies
- Enterprises owned by governments

### Treatment Options

| PSE Type | Treatment |
|----------|-----------|
| Central government-like | Sovereign treatment |
| Regional/Local government | Institution or sovereign treatment |
| Other PSE | Institution treatment |

### Risk Weights

Depends on treatment option elected:

| Option | Basis | Risk Weights |
|--------|-------|--------------|
| Sovereign | Parent sovereign rating | 0-150% |
| Institution | PSE's own rating | 20-150% |

**UK Regional Governments:**
- Scottish Government
- Welsh Government
- Northern Ireland Executive
- Typically treated as sovereign (0% RW)

### Calculation Example

**Exposure:**
- £50m loan to Transport for London
- Treated as PSE with institution option
- Rating: AA (CQS 1)

```python
# Institution treatment, CQS 1
Risk_Weight = 20%
RWA = £50,000,000 × 20% = £10,000,000
```

## Multilateral Development Banks (MDB)

### Eligible MDBs (0% RW)

| Institution | Countries/Region |
|-------------|------------------|
| World Bank (IBRD, IDA) | Global |
| European Investment Bank (EIB) | EU |
| Asian Development Bank (ADB) | Asia-Pacific |
| African Development Bank (AfDB) | Africa |
| Inter-American Development Bank (IADB) | Americas |
| European Bank for Reconstruction (EBRD) | Europe/Asia |
| Asian Infrastructure Investment Bank (AIIB) | Asia |
| Islamic Development Bank (IsDB) | Islamic countries |
| Nordic Investment Bank (NIB) | Nordic region |
| Council of Europe Development Bank (CEB) | Europe |

### Non-Eligible MDBs

Treated as institutions with applicable risk weight.

### Calculation Example

**Exposure:**
- £25m bond issued by World Bank

```python
# Eligible MDB = 0% RW
Risk_Weight = 0%
RWA = £25,000,000 × 0% = £0
```

## Regional Governments and Local Authorities (RGLA)

### Treatment

RGLAs can receive:
- Sovereign treatment (if explicitly guaranteed)
- PSE treatment (based on characteristics)
- Institution treatment (default)

### UK RGLAs

| Entity | Typical Treatment |
|--------|-------------------|
| Scottish Government | Sovereign-like |
| Welsh Government | Sovereign-like |
| English local authorities | PSE/Institution |
| Housing associations | Corporate/PSE |

## International Organisations

### 0% Risk Weight

| Organisation |
|--------------|
| European Union |
| International Monetary Fund (IMF) |
| Bank for International Settlements (BIS) |
| European Stability Mechanism (ESM) |

### Calculation Example

**Exposure:**
- £100m deposit with BIS

```python
# International organisation = 0% RW
Risk_Weight = 0%
RWA = £100,000,000 × 0% = £0
```

## Covered Bonds

### Definition

Debt securities secured by a dedicated pool of assets (cover pool):
- Residential mortgages
- Public sector exposures
- Ship mortgages

### Risk Weights

| CQS of Covered Bond | Risk Weight |
|---------------------|-------------|
| CQS 1 | 10% |
| CQS 2 | 20% |
| CQS 3 | 20% |
| CQS 4-6 | 50% |
| Unrated | 50% |

### Eligibility Requirements

- Issued by credit institution in EEA/equivalent
- Subject to special public supervision
- Cover pool meets quality requirements
- Overcollateralization of at least 5%

## Securitisation Positions

### Definition

Exposures to tranched credit risk:
- Asset-backed securities
- Mortgage-backed securities
- Collateralized loan obligations

### Treatment

Securitisation has dedicated rules (outside scope of this calculator):
- SEC-IRBA (IRB approach)
- SEC-SA (Standardised approach)
- SEC-ERBA (External ratings-based)

## Items Associated with High Risk

### Categories

| Type | Risk Weight |
|------|-------------|
| Private equity (Basel 3.1) | 400% |
| Speculative RE financing | 150% |
| Venture capital investments | 400% |
| Speculative unlisted equity | 400% |

## Other Items

### Tangible Assets

| Item | Risk Weight |
|------|-------------|
| Property, plant & equipment | 100% |
| Other tangible assets | 100% |

### Deferred Tax Assets

| Type | Treatment |
|------|-----------|
| DTAs from temporary differences | 250% RW or deduction |
| DTAs from tax loss carry-forward | Deduction |

### Cash Items in Collection

| Item | Risk Weight |
|------|-------------|
| Cash in collection | 20% |
| Items in process | 100% |

## Summary Table

| Exposure Class | SA RW Range | IRB Available |
|----------------|-------------|---------------|
| Equity (exchange) | 100% | No (Basel 3.1) |
| Equity (private) | 150-400% | No (Basel 3.1) |
| Defaulted | 50-150% | Yes |
| PSE | 0-150% | Yes |
| MDB (eligible) | 0% | N/A |
| RGLA | 0-150% | Yes |
| International Org | 0% | N/A |
| Covered Bonds | 10-50% | Varies |
| High Risk Items | 150-400% | Varies |

## Regulatory References

| Topic | CRR Article | BCBS CRE |
|-------|-------------|----------|
| Equity | Art. 133 | CRE20.60-65 |
| Defaulted | Art. 127 | CRE20.80-85 |
| PSE | Art. 115-116 | CRE20.15-20 |
| MDB | Art. 117 | CRE20.12-14 |
| RGLA | Art. 115 | CRE20.8-10 |
| Covered bonds | Art. 129 | CRE20.27-30 |
| High risk | Art. 128 | CRE20.90 |

## Next Steps

- [Exposure Classes Overview](index.md)
- [Standardised Approach](../methodology/standardised-approach.md)
- [Configuration Guide](../configuration.md)
