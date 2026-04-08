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

CRR assigns a flat 100% SA risk weight to all equity under Art. 133(2), with higher weights under IRB Simple (Art. 155: 290% exchange-traded, 370% PE/VC). Basel 3.1 removes IRB equity approaches and significantly increases SA weights to 250% (standard listed, Art. 133(3)) and 400% (higher risk: unlisted held <5 years, PE/VC, Art. 133(5)), with a transitional phase-in from 2027.

!!! warning "Basel 3.1"
    IRB approaches for equity are **removed** under Basel 3.1. Only SA is permitted.

> **Details:** See [Key Differences — Equity Exposures](../../framework-comparison/key-differences.md#equity-exposures) for the complete risk weight tables and transitional schedule.

### Calculation Example

**Exposure:**
- £10m listed equity portfolio
- Mix of exchange-traded and private equity

**CRR SA (Art. 133):**
```python
# Exchange-traded: £7m (flat 100%)
RWA_exchange = £7,000,000 × 100% = £7,000,000

# Private equity: £3m (flat 100%)
RWA_private = £3,000,000 × 100% = £3,000,000

# Total
Total_RWA = £10,000,000
```

**Basel 3.1 SA (Art. 133, fully phased from 2030):**
```python
# Exchange-traded: £7m (standard listed: 250%)
RWA_exchange = £7,000,000 × 250% = £17,500,000

# Private equity: £3m (higher risk: 400%)
RWA_private = £3,000,000 × 400% = £12,000,000

# Total
Total_RWA = £29,500,000
```

!!! info "Transitional weights (2027–2029)"
    Standard equity weights phase in from 160% (2027) to 250% (2030+), and higher-risk
    from 220% (2027) to 400% (2030+). See [Key Differences](../../framework-comparison/key-differences.md#equity-exposures) for the full schedule.

## Defaulted Exposures

### Definition

An exposure is classified as defaulted when:
- Past due > 90 days on a material amount
- Unlikely to pay in full without recourse to collateral
- Subject to distressed restructuring
- Bankruptcy or insolvency proceedings initiated
- Similar credit quality deterioration

### SA Risk Weights

Defaulted exposures receive 100%–150% depending on provision coverage. Basel 3.1 introduces a 50% RW for the secured portion of exposures with ≥50% specific provisions.

### IRB Treatment

Under IRB, defaulted exposures use PD = 100% and "best estimate LGD" (ELGD). The K formula still applies, producing RWA reflecting unexpected loss only.

> **Details:** See [Key Differences — Defaulted Exposures](../../framework-comparison/key-differences.md#defaulted-exposures) for the full CRR vs Basel 3.1 comparison.

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

Covered bond risk weights range from 10% (CQS 1) to 50% (CQS 4-6 / unrated). Eligibility requires the issuer to be a regulated credit institution with special public supervision, qualifying cover pool, and at least 5% overcollateralisation.

> **Details:** See [Key Differences — Covered Bonds](../../framework-comparison/key-differences.md#covered-bonds) for the full CQS table.

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

!!! warning "Art. 128 Omitted from UK CRR — Active Under Basel 3.1 Only"
    Art. 128 was **omitted from UK CRR** by SI 2021/1078, reg. 6(3)(a), effective
    1 January 2022. Under current UK CRR, there is no separate high-risk exposure
    class — these exposures are classified under their standard counterparty class
    (e.g., equity at 100% per Art. 133(2), or corporate at the applicable CQS weight).

    Art. 128 is **re-introduced under Basel 3.1** (PRA PS1/26, effective 1 January 2027),
    but with paragraph 2 left blank (the original EU CRR list of specific categories
    is not carried forward). Institutions must assess high risk per Art. 128(3):
    (a) high risk of loss from obligor default; (b) impossible to adequately assess
    whether (a) applies.

Under Basel 3.1 Art. 128(1), exposures assessed as particularly high risk receive
a flat **150%** risk weight.

!!! note "Exposure Class Waterfall"
    Under Art. 112 Table A2, equity (priority 3) takes precedence over high-risk
    items (priority 4). Private equity, venture capital, and speculative unlisted
    equity are classified as **equity** under Art. 133 (250% standard / 400% higher
    risk), not as high-risk items. Art. 128 applies to non-equity exposures such
    as speculative immovable property financing.

### Art. 128 High-Risk Items (Basel 3.1 only)

| Type | Risk Weight | Reference |
|------|-------------|-----------|
| Speculative immovable property financing | 150% | Art. 128(1) |
| Other PRA-designated high-risk items | 150% | Art. 128(1), (3) |

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
| Equity (exchange) | 100–250% | No (Basel 3.1) |
| Equity (private/VC) | 100–400% | No (Basel 3.1) |
| Defaulted | 50-150% | Yes |
| PSE | 0-150% | Yes |
| MDB (eligible) | 0% | N/A |
| RGLA | 0-150% | Yes |
| International Org | 0% | N/A |
| Covered Bonds | 10-50% | Varies |
| High Risk Items (B31 only) | 150% | No |

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
