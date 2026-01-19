# CRR (Basel 3.0)

The **Capital Requirements Regulation (CRR)** is the current regulatory framework for UK credit risk capital requirements. It implements Basel 3.0 standards and remains in effect until 31 December 2026.

## Legal Basis

| Document | Reference |
|----------|-----------|
| Primary Legislation | UK CRR (EU 575/2013 as onshored) |
| PRA Rules | PRA Rulebook - CRR Firms |
| Key Articles | Articles 111-191 (Credit Risk) |

## Key Features

### 1.06 Scaling Factor

All IRB RWA is multiplied by 1.06 (a 6% increase):

```
RWA_IRB = K × 12.5 × EAD × MA × 1.06
```

!!! note "CRR Article 153"
    The 1.06 scaling factor was introduced to provide a buffer during the transition to IRB approaches. It is removed under Basel 3.1.

### SME Supporting Factor

The SME Supporting Factor reduces RWA for qualifying SME exposures.

**Eligibility Criteria:**
- Counterparty turnover ≤ EUR 50m (GBP 44m)
- Exposure classified as Corporate, Retail, or Secured by Real Estate

**Tiered Calculation (CRR2 Article 501):**

```
Factor = [min(E, threshold) × 0.7619 + max(E - threshold, 0) × 0.85] / E
```

Where:
- E = Total exposure to the counterparty
- Threshold = EUR 2.5m (GBP 2.2m)

| Exposure Amount | Factor Applied |
|-----------------|----------------|
| ≤ EUR 2.5m | 0.7619 (23.81% reduction) |
| > EUR 2.5m | Tiered blend |

**Example:**

For a GBP 5m exposure:
```
Factor = [2.2m × 0.7619 + 2.8m × 0.85] / 5.0m
       = [1.676m + 2.38m] / 5.0m
       = 0.811 (18.9% reduction)
```

### Infrastructure Supporting Factor

A 0.75 factor (25% reduction) applies to qualifying infrastructure project finance:

**Eligibility Criteria:**
- Project finance exposure
- Exposure to an infrastructure project entity
- Revenues predominantly in EUR/GBP or hedged

```
RWA_adjusted = RWA × 0.75
```

### Uniform PD Floor

All IRB exposures have a minimum PD of **0.03%** (3 basis points):

```
PD_effective = max(PD_estimated, 0.0003)
```

### No Output Floor

CRR does not apply an output floor. IRB RWA can be significantly lower than SA equivalent.

## Risk Weight Tables

### Sovereign Exposures (SA)

| CQS | Risk Weight |
|-----|-------------|
| CQS 1 | 0% |
| CQS 2 | 20% |
| CQS 3 | 50% |
| CQS 4 | 100% |
| CQS 5 | 100% |
| CQS 6 | 150% |
| Unrated | 100% |

### Institution Exposures (SA)

| CQS | Risk Weight |
|-----|-------------|
| CQS 1 | 20% |
| CQS 2 | 30% (UK deviation from 50%) |
| CQS 3 | 50% |
| CQS 4 | 100% |
| CQS 5 | 100% |
| CQS 6 | 150% |
| Unrated | See due diligence approach |

### Corporate Exposures (SA)

| CQS | Risk Weight |
|-----|-------------|
| CQS 1 | 20% |
| CQS 2 | 50% |
| CQS 3 | 75% |
| CQS 4 | 100% |
| CQS 5 | 150% |
| CQS 6 | 150% |
| Unrated | 100% |

### Retail Exposures (SA)

| Type | Risk Weight |
|------|-------------|
| Retail - Residential Mortgage (LTV ≤ 80%) | 35% |
| Retail - Residential Mortgage (LTV > 80%) | Risk-weight varies |
| Retail - QRRE | 75% |
| Retail - Other | 75% |

### Defaulted Exposures (SA)

| Provision Coverage | Risk Weight |
|-------------------|-------------|
| < 20% | 150% |
| ≥ 20% | 100% |

## Credit Conversion Factors (CCF)

| Item Type | CCF | Reference |
|-----------|-----|-----------|
| Unconditionally cancellable commitments | 0% | Art. 111(1)(a) |
| Short-term trade letters of credit | 20% | Art. 111(1)(b) |
| Undrawn credit facilities | 20% | Art. 111(1)(c) |
| Note issuance facilities | 50% | Art. 111(1)(d) |
| Underwriting facilities | 50% | Art. 111(1)(e) |
| Direct credit substitutes | 100% | Art. 111(1)(f) |
| Acceptances | 100% | Art. 111(1)(g) |

## F-IRB Supervisory LGD

| Exposure Type | Senior Unsecured | Subordinated |
|---------------|------------------|--------------|
| Corporate/Institution | 45% | 75% |
| Secured - Financial Collateral | 0% | N/A |
| Secured - Receivables | 35% | N/A |
| Secured - CRE/RRE | 35% | N/A |
| Secured - Other | 40% | N/A |

## CRM Haircuts

### Financial Collateral Haircuts

| Collateral Type | Haircut |
|-----------------|---------|
| Cash | 0% |
| Government bonds (≤1y residual) | 0.5% |
| Government bonds (1-5y) | 2% |
| Government bonds (>5y) | 4% |
| Corporate bonds AAA/AA (≤1y) | 1% |
| Corporate bonds AAA/AA (1-5y) | 4% |
| Corporate bonds AAA/AA (>5y) | 8% |
| Main index equities | 15% |
| Other equities | 25% |
| **Currency mismatch** | **+8%** |

### Maturity Mismatch Formula

When collateral maturity < exposure maturity:

```
CRM_adjusted = CRM × (t - 0.25) / (T - 0.25)
```

Where:
- t = Residual maturity of collateral (years, min 0.25)
- T = Residual maturity of exposure (years, min 0.25)

## Slotting Risk Weights

| Category | Strong | Good | Satisfactory | Weak |
|----------|--------|------|--------------|------|
| Project Finance | 70% | 90% | 115% | 250% |
| Object Finance | 70% | 90% | 115% | 250% |
| Commodities Finance | 70% | 90% | 115% | 250% |
| IPRE | 70% | 90% | 115% | 250% |
| HVCRE | 95% | 120% | 140% | 250% |

## IRB Formulas

### Capital Requirement (K)

```python
K = LGD × N[(1-R)^(-0.5) × G(PD) + (R/(1-R))^0.5 × G(0.999)] - LGD × PD
```

Where:
- N() = Standard normal cumulative distribution
- G() = Inverse standard normal distribution
- R = Asset correlation

### Asset Correlation (Corporate)

```python
R = 0.12 × (1 - exp(-50 × PD)) / (1 - exp(-50)) +
    0.24 × [1 - (1 - exp(-50 × PD)) / (1 - exp(-50))]
```

With SME size adjustment:
```python
R_sme = R - 0.04 × (1 - (S - 5) / 45)
```

Where S = Annual turnover (EUR millions, capped at 50)

### Maturity Adjustment

```python
b = (0.11852 - 0.05478 × ln(PD))^2

MA = (1 + (M - 2.5) × b) / (1 - 1.5 × b)
```

Where M = Effective maturity (years, 1-5)

## Configuration Example

```python
from datetime import date
from decimal import Decimal
from rwa_calc.contracts.config import CalculationConfig

config = CalculationConfig.crr(
    reporting_date=date(2026, 12, 31),

    # SME Supporting Factor
    apply_sme_supporting_factor=True,

    # Infrastructure Factor
    apply_infrastructure_factor=True,

    # EUR/GBP rate for threshold conversion
    eur_gbp_rate=Decimal("0.88"),
)
```

## Regulatory References

| Topic | Article |
|-------|---------|
| Exposure classes | Art. 112 |
| Risk weight assignment | Art. 113-134 |
| IRB approach | Art. 142-191 |
| Credit risk mitigation | Art. 192-241 |
| SME supporting factor | Art. 501 |
| CCFs | Art. 111 |

## Next Steps

- [Basel 3.1](basel31.md) - Future framework
- [Framework Comparison](comparison.md) - CRR vs Basel 3.1
- [Calculation Methodology](../methodology/index.md) - Detailed calculations
