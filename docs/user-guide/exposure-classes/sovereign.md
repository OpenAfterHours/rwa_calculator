# Sovereign Exposures

**Sovereign exposures** are claims on governments, central banks, and certain public sector entities treated as sovereigns.

## Definition

Sovereign exposures include:

| Entity Type | Examples |
|-------------|----------|
| Central governments | UK HM Treasury, US Treasury |
| Central banks | Bank of England, ECB |
| Multilateral development banks (eligible) | IMF, World Bank, EIB |
| International organisations | BIS, EU institutions |
| Regional governments (treated as sovereign) | Devolved UK administrations |

## Risk Weights (SA)

### External Rating Approach

| CQS | S&P/Fitch | Moody's | Risk Weight |
|-----|-----------|---------|-------------|
| CQS 1 | AAA to AA- | Aaa to Aa3 | **0%** |
| CQS 2 | A+ to A- | A1 to A3 | **20%** |
| CQS 3 | BBB+ to BBB- | Baa1 to Baa3 | **50%** |
| CQS 4 | BB+ to BB- | Ba1 to Ba3 | **100%** |
| CQS 5 | B+ to B- | B1 to B3 | **100%** |
| CQS 6 | CCC+ and below | Caa1 and below | **150%** |
| Unrated | - | - | **100%** |

### Preferential Treatment

Certain sovereigns receive preferential risk weights:

| Sovereign | Treatment | Risk Weight |
|-----------|-----------|-------------|
| UK Government | Domestic sovereign | 0% |
| Other G10 | Reciprocal treatment | Per rating |
| Non-OECD Unrated | Default weight | 100% |

## IRB Treatment

### F-IRB Parameters

| Parameter | Value |
|-----------|-------|
| PD | Bank estimate (floor 0.03%) |
| LGD | Supervisory 45% |
| M | Effective maturity |

### A-IRB Parameters

| Parameter | Value |
|-----------|-------|
| PD | Bank estimate (floor 0.03% CRR / 0.05% Basel 3.1) |
| LGD | Bank estimate |
| EAD | Bank estimate |

### Correlation

Sovereign correlation uses the corporate formula:
```python
R = 0.12 × (1 - exp(-50 × PD)) / (1 - exp(-50)) +
    0.24 × [1 - (1 - exp(-50 × PD)) / (1 - exp(-50))]
```

## Domestic Sovereign

### UK Government Exposures

The UK Government receives 0% risk weight for:
- Treasury bonds (Gilts)
- National Savings products
- Loans to HM Treasury
- Exposures guaranteed by UK Government

### Treatment

```python
if counterparty.country == "UK" and counterparty.type == "SOVEREIGN":
    risk_weight = 0.00  # 0% RW
```

## Foreign Sovereigns

### G10 Sovereigns

| Country | Typical Rating | Typical RW |
|---------|----------------|------------|
| United States | AA+ | 0-20% |
| Germany | AAA | 0% |
| France | AA | 0-20% |
| Japan | A+ | 20% |

### Emerging Market Sovereigns

| Rating Category | Examples | Typical RW |
|-----------------|----------|------------|
| Investment Grade | China, India | 20-100% |
| Non-Investment Grade | Various | 100-150% |
| High Risk | Distressed | 150% |

## Central Bank Exposures

### Treatment

Central bank exposures receive the same treatment as their sovereign:

| Central Bank | Sovereign Link | Risk Weight |
|--------------|----------------|-------------|
| Bank of England | UK Government | 0% |
| European Central Bank | Per member state or EU | 0% |
| Federal Reserve | US Government | 0-20% |

### Reserves Held

Reserves held with central banks:
```python
if exposure.type == "CENTRAL_BANK_RESERVE":
    risk_weight = sovereign_risk_weight  # Same as sovereign
```

## Multilateral Development Banks

### Eligible MDBs (0% RW)

| Institution | Abbreviation |
|-------------|--------------|
| International Bank for Reconstruction and Development | IBRD |
| International Finance Corporation | IFC |
| Inter-American Development Bank | IADB |
| Asian Development Bank | ADB |
| African Development Bank | AfDB |
| European Bank for Reconstruction and Development | EBRD |
| European Investment Bank | EIB |
| European Investment Fund | EIF |
| Nordic Investment Bank | NIB |
| Council of Europe Development Bank | CEB |
| Islamic Development Bank | IsDB |
| Asian Infrastructure Investment Bank | AIIB |

### Other MDBs

Non-eligible MDBs treated as institutions:
```python
if mdb in ELIGIBLE_MDB_LIST:
    risk_weight = 0.00
else:
    # Treat as institution
    risk_weight = institution_risk_weight(cqs)
```

## CRM for Sovereign Exposures

### Sovereign Guarantees

Exposures guaranteed by eligible sovereigns use substitution:

```python
# Guaranteed portion at guarantor sovereign RW
if guarantee.type == "SOVEREIGN" and guarantee.cqs <= 3:
    guaranteed_rw = sovereign_risk_weight(guarantee.cqs)
```

### Sovereign Collateral

Government bonds as collateral receive low haircuts:

| Collateral (CQS 1 Sovereign) | Maturity | Haircut |
|------------------------------|----------|---------|
| Government bonds | ≤1 year | 0.5% |
| Government bonds | 1-5 years | 2% |
| Government bonds | >5 years | 4% |

## Calculation Example

**Exposure:**
- £100m UK Gilt holding
- UK Government (CQS 1)

**SA Calculation:**
```python
# Sovereign CQS 1 = 0% RW
Risk_Weight = 0%
EAD = £100,000,000
RWA = £100,000,000 × 0% = £0
```

**Foreign Sovereign Example:**
- £50m German Bund
- Germany (AAA, CQS 1)

```python
Risk_Weight = 0%
RWA = £50,000,000 × 0% = £0
```

**Lower-rated Sovereign:**
- £20m Brazil bonds
- Brazil (BB-, CQS 4)

```python
Risk_Weight = 100%
RWA = £20,000,000 × 100% = £20,000,000
```

## Regulatory References

| Topic | CRR Article | BCBS CRE |
|-------|-------------|----------|
| Sovereign definition | Art. 114 | CRE20.7-10 |
| Risk weights | Art. 114 | CRE20.11 |
| MDB treatment | Art. 117 | CRE20.12-14 |
| Central bank treatment | Art. 114(4) | CRE20.8 |

## Next Steps

- [Institution Exposures](institution.md)
- [Standardised Approach](../methodology/standardised-approach.md)
- [IRB Approach](../methodology/irb-approach.md)
