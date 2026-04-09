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

**Eligibility Criteria (Art. 501):**
- Counterparty turnover ≤ EUR 50m (GBP 44m)
- Exposure classified as Corporate, Retail, or Secured by Real Estate

!!! warning "Implementation Scope"
    CRR Art. 501 applies the supporting factor to all SME exposures regardless of exposure
    class. However, the calculator applies the factor only to `CORPORATE_SME` exposures (via
    the `is_sme` flag). Retail-origin entities that fail the retail qualification test are
    reclassified to `CORPORATE_SME` and receive the factor (tested by CRR-F4). Retail-qualifying
    SMEs that remain in `RETAIL_OTHER` or `RETAIL_MORTGAGE` do not currently receive the
    Art. 501 discount — their 75% risk weight already provides favourable treatment. See the
    [supporting factors specification](../../specifications/crr/supporting-factors.md) for
    details.

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
| CQS 2 | 50% |
| CQS 3 | 50% |
| CQS 4 | 100% |
| CQS 5 | 100% |
| CQS 6 | 150% |
| Unrated | 40% (Art. 121 sovereign-derived) |

### Corporate Exposures (SA)

| CQS | Risk Weight |
|-----|-------------|
| CQS 1 | 20% |
| CQS 2 | 50% |
| CQS 3 | 100% |
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

CRR Art. 111 assigns CCFs to off-balance sheet items based on the four risk categories
defined in **Annex I**. The maturity of undrawn commitments determines whether they fall
into medium risk (50%) or medium/low risk (20%).

| Annex I Category | CCF | Key Items |
|-----------------|-----|-----------|
| Full Risk (FR) | 100% | Guarantees with credit-substitute character, credit derivatives, acceptances, irrevocable standby LCs (credit substitute) |
| Full Risk — Commitments (FRC) | 100% | Certain-drawdown commitments: repos, factoring, forward deposits, outright forward purchases, partly-paid shares (Annex I para 2) |
| Medium Risk (MR) | 50% | Undrawn credit facilities with original maturity **> 1 year**; NIFs; RUFs (Annex I para 3) |
| Medium/Low Risk (MLR) | 20% | Undrawn credit facilities with original maturity **≤ 1 year** (not unconditionally cancellable); documentary credits; trade-related LCs; warranties; performance bonds (Annex I para 4) |
| Low Risk (LR) | 0% | Unconditionally cancellable commitments (Annex I para 5) |

!!! info "Maturity Distinction for Undrawn Commitments"
    The same undrawn credit facility receives different CCFs depending on its original
    maturity: **> 1 year → 50%** (MR), **≤ 1 year → 20%** (MLR),
    **unconditionally cancellable → 0%** (LR). Basel 3.1 removes this maturity split,
    replacing it with a flat 40% for all non-cancellable commitments
    (see [key differences](../../framework-comparison/key-differences.md#credit-conversion-factors)).

!!! tip "Full detail"
    See the [CCF specification](../../specifications/crr/credit-conversion-factors.md)
    for F-IRB CCFs (Art. 166), Basel 3.1 Table A1 comparison, and acceptance test scenarios.

## F-IRB Supervisory LGD

### Unsecured Exposures (Art. 161(1))

| Category | LGD | Reference |
|----------|-----|-----------|
| Senior unsecured | 45% | Art. 161(1)(a) |
| Subordinated unsecured | 75% | Art. 161(1)(b) |
| Covered bonds (Art. 129(4)/(5) eligible) | 11.25% | Art. 161(1)(d) |
| Senior purchased corporate receivables | 45% | Art. 161(1)(e) |
| Subordinated purchased corporate receivables | 100% | Art. 161(1)(f) |
| Dilution risk of purchased receivables | 75% | Art. 161(1)(g) |

!!! warning "Not Yet Implemented — Purchased Receivables"
    Art. 161(1)(e)/(f)/(g) purchased receivables and dilution risk LGD values are not
    implemented in code. These exposures currently receive the standard unsecured LGD
    (45% senior / 75% subordinated).

### Secured Exposures — LGDS (Art. 230 Table 5)

For collateralised exposures under the Foundation Collateral Method, the secured
portion receives a reduced LGDS value:

| Collateral Type | LGDS (Senior) | LGDS (Subordinated) | Reference |
|-----------------|---------------|---------------------|-----------|
| Financial collateral | 0% | 0% | Art. 230 Table 5 |
| Receivables | 35% | 65% | Art. 230 Table 5 |
| Residential / commercial RE | 35% | 65% | Art. 230 Table 5 |
| Other physical collateral | 40% | 70% | Art. 230 Table 5 |

!!! info "CRE and RRE Combined"
    CRR Art. 230 Table 5 does not differentiate between residential and commercial
    real estate — both receive 35% LGDS (senior). Basel 3.1 reduces both to 20%
    (see [key differences](../../framework-comparison/key-differences.md#f-irb-lgd)).

!!! tip "Full detail"
    See the [F-IRB specification](../../specifications/crr/firb-calculation.md) for
    overcollateralisation thresholds (C\*/C\*\*), Basel 3.1 FSE distinction
    (Art. 161(1)(a) 45% vs Art. 161(1)(aa) 40%), and acceptance test scenarios.

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

## Slotting Risk Weights (Art. 153(5))

UK CRR Art. 153(5) defines a single risk weight table (Table 1) with maturity-based splits,
covering all specialised lending types (PF, OF, CF, IPRE).

### Table 1 (PF, OF, CF, IPRE)

| Category | Remaining Maturity ≥ 2.5yr | Remaining Maturity < 2.5yr |
|----------|---------------------------|---------------------------|
| Strong | 70% | 50% |
| Good | 90% | 70% |
| Satisfactory | 115% | 115% |
| Weak | 250% | 250% |
| Default | 0% | 0% |

!!! warning "No HVCRE Distinction in UK CRR"
    The UK onshored CRR does **not** contain a separate HVCRE table. The term "high volatility
    commercial real estate" does not appear in the UK CRR text. The original EU CRR had a
    separate Table 2 with elevated HVCRE weights, but this was not retained in UK onshoring.
    All specialised lending under UK CRR uses Table 1 above. HVCRE is introduced as a distinct
    sub-type by PRA PS1/26 (Basel 3.1) — see [Basel 3.1 guide](basel31.md#specialised-lending).
    The calculator applies EU CRR Table 2 weights for `is_hvcre=True` CRR exposures (code
    divergence D3.22).

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

## Omitted Provisions

The following CRR articles were omitted from UK onshored CRR by SI 2021/1078
(effective 1 January 2022) and moved to the PRA Rulebook (CRR Part) or removed
entirely. They are **not active** under current UK CRR:

| Article | Subject | Status |
|---------|---------|--------|
| Art. 128 | Items associated with particularly high risk (150%) | Omitted; re-introduced under Basel 3.1 (PRA PS1/26) |
| Art. 132 | CIU treatment | Omitted; moved to PRA Rulebook (CRR Part) |
| Art. 152 | IRB treatment of CIU exposures | Omitted; moved to PRA Rulebook (CRR Part) |
| Art. 153(5) Table 2 | HVCRE slotting risk weights | Not retained in UK onshoring; HVCRE introduced by PRA PS1/26 Table A |
| Art. 158 | Expected loss — treatment by exposure type | Omitted; EL rules moved to PRA Rulebook (CRR Part); reinstated with modifications in PS1/26 |

!!! note
    Art. 128 exposures (e.g., speculative RE financing) should fall through to their
    standard exposure class under current UK CRR — e.g., equity at 100% (Art. 133(2))
    or corporate at the applicable CQS weight. Under Basel 3.1, Art. 128 is re-introduced
    with a flat 150% risk weight. See [Basel 3.1](basel31.md) for details.

## Regulatory References

| Topic | Article |
|-------|---------|
| Exposure classes | Art. 112 |
| Risk weight assignment | Art. 113-134 |
| IRB approach | Art. 142-191 |
| Credit risk mitigation | Art. 192-241 |
| SME supporting factor | Art. 501 |
| CCFs | Art. 111, Annex I |

## Next Steps

- [Basel 3.1](basel31.md) - Future framework
- [Framework Comparison](../../framework-comparison/index.md) - CRR vs Basel 3.1
- [Calculation Methodology](../methodology/index.md) - Detailed calculations
