"""
RWA Framework Reference Marimo Application.

Reference documentation for CRR and Basel 3.1 regulatory frameworks.

Usage:
    uv run marimo edit src/rwa_calc/ui/marimo/framework_reference.py
    uv run marimo run src/rwa_calc/ui/marimo/framework_reference.py

Features:
    - CRR (Basel 3.0) reference tables
    - Basel 3.1 (PRA PS9/24) reference tables
    - Risk weight tables
    - Supporting factor details
    - IRB parameters
"""

import marimo

__generated_with = "0.19.4"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo
    import polars as pl

    return mo, pl


@app.cell
def _(mo):
    mo.sidebar(
        [
            mo.md("# RWA Calculator"),
            mo.nav_menu(
                {
                    "/calculator": f"{mo.icon('calculator')} Calculator",
                    "/results": f"{mo.icon('table')} Results Explorer",
                    "/reference": f"{mo.icon('book')} Framework Reference",
                },
                orientation="vertical",
            ),
            mo.md("---"),
            mo.md("""
**Quick Links**
- [PRA PS9/24](https://www.bankofengland.co.uk/prudential-regulation/publication/2024/september/implementation-of-the-basel-3-1-standards-near-final-policy-statement-part-2)
- [UK CRR](https://www.legislation.gov.uk/eur/2013/575/contents)
- [BCBS Framework](https://www.bis.org/basel_framework/)
            """),
        ],
        footer=mo.md("*RWA Calculator v1.0*"),
    )
    return


@app.cell
def _(mo):
    return mo.md("""
# Framework Reference

Regulatory reference documentation for RWA calculations under CRR and Basel 3.1.
    """)


@app.cell
def _(mo):
    framework_tabs = mo.ui.tabs({
        "Overview": "overview",
        "CRR (Basel 3.0)": "crr",
        "Basel 3.1": "basel31",
        "Risk Weights": "rw",
        "IRB Parameters": "irb",
    })

    mo.output.replace(framework_tabs)
    return (framework_tabs,)


@app.cell
def _(framework_tabs, mo, pl):
    if framework_tabs.value == "overview":
        mo.output.replace(mo.md("""
## Framework Overview

### Timeline

| Framework | Status | Effective Period |
|-----------|--------|------------------|
| **CRR (Basel 3.0)** | Current | Until 31 December 2026 |
| **Basel 3.1** | Upcoming | From 1 January 2027 |

### Key Differences

| Feature | CRR | Basel 3.1 |
|---------|-----|-----------|
| **SME Supporting Factor** | 0.7619 (Art. 501) | Removed |
| **Infrastructure Factor** | 0.75 (Art. 501a) | Removed |
| **Output Floor** | None | 72.5% of SA RWA |
| **PD Floor** | 0.03% (all classes) | 0.03% - 0.10% (differentiated) |
| **LGD Floors** | Based on CRR rules | New floors by collateral type |
| **Credit Conversion Factors** | Regulatory CCFs | Revised CCFs |

### Regulatory Sources

- **UK CRR**: [legislation.gov.uk](https://www.legislation.gov.uk/eur/2013/575/contents)
- **PRA PS9/24**: [Bank of England](https://www.bankofengland.co.uk/prudential-regulation/publication/2024/september/implementation-of-the-basel-3-1-standards-near-final-policy-statement-part-2)
- **BCBS Framework**: [bis.org](https://www.bis.org/basel_framework/)
        """))

    elif framework_tabs.value == "crr":
        mo.output.replace(mo.md("""
## CRR (Basel 3.0) Framework

### Supporting Factors

#### SME Supporting Factor (Article 501)
Exposures to SMEs qualify for a reduction in capital requirements:

| Condition | Factor |
|-----------|--------|
| Total exposure ≤ €2.5m | 0.7619 |
| Total exposure > €2.5m | 0.7619 (on first €2.5m) |

**Eligibility Criteria:**
- Counterparty is an SME (annual turnover ≤ €50m)
- Total exposure to the SME group ≤ €1.5m

#### Infrastructure Supporting Factor (Article 501a)

| Condition | Factor |
|-----------|--------|
| Qualifying infrastructure exposure | 0.75 |

**Eligibility Criteria:**
- Project entity operates infrastructure
- Cash flows predictable
- Contractual arrangements provide security
- Debt repayment from project revenues

### Exposure Classes (Article 112)

| Class | Description |
|-------|-------------|
| Central Governments | Sovereigns, central banks |
| Regional/Local Authorities | Sub-national governments |
| Public Sector Entities | Government-related entities |
| Multilateral Development Banks | MDBs (special treatment) |
| International Organisations | IMF, BIS, etc. |
| Institutions | Banks, investment firms |
| Corporates | Non-financial corporates |
| Retail | SME and natural persons |
| Secured by Real Estate | Mortgage exposures |
| In Default | Defaulted exposures |
| High Risk | Venture capital, etc. |
| Covered Bonds | Covered bond exposures |
| Securitisation | Securitisation positions |
| CIUs | Collective investment undertakings |
| Equity | Equity holdings |
| Other Items | Residual exposures |
        """))

    elif framework_tabs.value == "basel31":
        mo.output.replace(mo.md("""
## Basel 3.1 Framework (PRA PS9/24)

### Key Changes from CRR

#### 1. Output Floor
- Floor = 72.5% of SA RWA
- Transitional period: 50% (2027) rising to 72.5% (2030)
- Applies to banks using IRB approach

#### 2. Removal of Supporting Factors
- SME supporting factor: **Removed**
- Infrastructure supporting factor: **Removed**

#### 3. Revised Standardised Approach

**Corporate Risk Weights:**

| Rating | Risk Weight |
|--------|-------------|
| AAA to AA- | 20% |
| A+ to A- | 50% |
| BBB+ to BBB- | 75% |
| BB+ to BB- | 100% |
| Below BB- | 150% |
| Unrated | 100% |

**SME Corporates:** 85% (if unrated, turnover ≤ €50m)

#### 4. Real Estate Exposures

**Residential (Income-Producing):**

| LTV | Risk Weight |
|-----|-------------|
| ≤ 50% | 30% |
| 50-60% | 35% |
| 60-80% | 45% |
| 80-90% | 60% |
| 90-100% | 75% |
| > 100% | 105% |

**Commercial:**

| LTV | Risk Weight |
|-----|-------------|
| ≤ 60% | 70% |
| > 60% | 110% |

#### 5. Off-Balance Sheet Items

| Category | CCF |
|----------|-----|
| Unconditionally cancellable commitments | 10% |
| Other commitments | 40% |
| Direct credit substitutes | 100% |
| Trade-related contingencies | 20% |
| Transaction-related contingencies | 50% |
        """))

    elif framework_tabs.value == "rw":
        # Risk weight tables
        sa_rw_table = pl.DataFrame({
            "Exposure Class": [
                "Central Governments (AAA-AA)",
                "Central Governments (A)",
                "Central Governments (BBB)",
                "Central Governments (BB)",
                "Central Governments (B)",
                "Central Governments (Below B)",
                "Institutions (AAA-AA)",
                "Institutions (A)",
                "Institutions (BBB)",
                "Institutions (BB)",
                "Institutions (Below BB)",
                "Corporates (AAA-AA)",
                "Corporates (A)",
                "Corporates (BBB)",
                "Corporates (BB)",
                "Corporates (Below BB)",
                "Corporates (Unrated)",
                "Retail",
                "Residential Mortgage (LTV ≤ 80%)",
                "Commercial Real Estate",
                "Defaulted",
            ],
            "CRR RW": [
                "0%", "20%", "50%", "100%", "100%", "150%",
                "20%", "50%", "50%", "100%", "150%",
                "20%", "50%", "100%", "100%", "150%", "100%",
                "75%", "35%", "100%", "150%",
            ],
            "Basel 3.1 RW": [
                "0%", "20%", "50%", "100%", "100%", "150%",
                "20%", "30%", "50%", "100%", "150%",
                "20%", "50%", "75%", "100%", "150%", "100%",
                "75%", "45%*", "70-110%*", "100-150%",
            ],
        })

        mo.output.replace(
            mo.vstack([
                mo.md("## Standardised Approach Risk Weights"),
                mo.md("*Note: Basel 3.1 values marked with * are dependent on LTV or other conditions*"),
                mo.ui.table(sa_rw_table, selection=None),
            ])
        )

    elif framework_tabs.value == "irb":
        mo.output.replace(mo.md("""
## IRB Parameters

### PD Floors

| Exposure Class | CRR Floor | Basel 3.1 Floor |
|----------------|-----------|-----------------|
| Corporates | 0.03% | 0.05% |
| Banks/Financial Institutions | 0.03% | 0.05% |
| Sovereigns | 0.03% | 0.03% |
| Retail - Mortgages | 0.03% | 0.05% |
| Retail - QRRE | 0.03% | 0.05% |
| Retail - Other | 0.03% | 0.10% |

### LGD Values (Foundation IRB)

| Collateral Type | CRR LGD | Basel 3.1 Floor |
|-----------------|---------|-----------------|
| Senior unsecured | 45% | 25% |
| Subordinated | 75% | 25% |
| Financial collateral | Varies | Varies |
| Receivables | 35% | 20% |
| Commercial/Residential RE | 35% | 20% |
| Other physical collateral | 40% | 25% |

### Maturity (M)

| IRB Approach | CRR | Basel 3.1 |
|--------------|-----|-----------|
| Foundation IRB | 2.5 years (fixed) | 2.5 years (fixed) |
| Advanced IRB | Bank estimate | Bank estimate |
| Floor | 1 year | 1 year |
| Cap | 5 years | 5 years |

### Correlation (R)

**Corporate Formula:**
```
R = 0.12 × (1 - EXP(-50 × PD)) / (1 - EXP(-50))
  + 0.24 × (1 - (1 - EXP(-50 × PD)) / (1 - EXP(-50)))
```

**SME Adjustment (CRR only):**
```
R_SME = R - 0.04 × (1 - (S - 5) / 45)
```
Where S = turnover in € millions (floored at 5, capped at 50)

**Basel 3.1 Note:** SME correlation adjustment is removed.

### Capital Requirement Formula

```
K = LGD × N[(1-R)^(-0.5) × G(PD) + (R/(1-R))^0.5 × G(0.999)]
    - PD × LGD
```

Where:
- N = Standard normal CDF
- G = Inverse standard normal CDF
- R = Asset correlation
- PD = Probability of default
- LGD = Loss given default
        """))
    return


if __name__ == "__main__":
    app.run()
