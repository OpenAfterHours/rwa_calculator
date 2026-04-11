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

CRR assigns a flat 100% SA risk weight to all equity under Art. 133(2), with higher weights under IRB Simple (Art. 155: 290% exchange-traded, 370% other). Basel 3.1 removes IRB equity approaches and significantly increases SA weights to 250% (standard, Art. 133(3)) and 400% (higher risk: unlisted + business < 5 years, Art. 133(4)), with a transitional phase-in from 2027.

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

# Private equity: £3m (higher risk — unlisted, business < 5yr: 400%)
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

PSEs are non-commercial administrative bodies responsible to, or owned by, central
governments, regional governments, or local authorities (CRR Art. 4(1)(8)):

- Transport authorities (e.g., Transport for London)
- Water and utility boards
- Public health bodies (e.g., NHS trusts)
- Government-owned enterprises
- Administrative bodies exercising public functions

!!! note "PSE vs RGLA"
    Regional governments and local authorities themselves are classified as **RGLA**
    (Art. 115), not PSE. PSEs are entities *subordinate to* or *owned by* governments,
    not the governments themselves.

### Treatment Methods (CRR Art. 116)

| Method | Condition | Table | Basis |
|--------|-----------|-------|-------|
| Sovereign-derived | No own ECAI rating | Table 2 (Art. 116(1)) | Sovereign CQS |
| Own-rating | Has own ECAI rating | Table 2A (Art. 116(2)) | PSE's own CQS |

!!! note "Art. 116(4) left blank"
    PRA PS1/26 leaves Art. 116(4) blank — there is no "institution-equivalent" PSE
    sub-treatment under UK rules. All UK PSEs use Tables 2/2A.

### Risk Weight Tables

**Table 2 — Sovereign-Derived (Art. 116(1))**

Used when the PSE has no own ECAI rating — look up the sovereign's CQS:

| Sovereign CQS | PSE Risk Weight |
|---------------|----------------|
| 1 | 20% |
| 2 | 50% |
| 3 | 100% |
| 4 | 100% |
| 5 | 100% |
| 6 | 150% |
| Unrated | 100% |

**Table 2A — Own-Rating (Art. 116(2))**

Used when the PSE has its own ECAI rating:

| CQS | Risk Weight |
|-----|-------------|
| 1 | 20% |
| 2 | 50% |
| 3 | 50% |
| 4 | 100% |
| 5 | 100% |
| 6 | 150% |

!!! info "Key difference: CQS 3"
    Under sovereign-derived treatment (Table 2), CQS 3 receives **100%**. Under
    own-rating treatment (Table 2A), CQS 3 receives **50%**. Having an own ECAI
    rating can materially reduce RWA at CQS 3.

### Short-Term Preferential Treatment (Art. 116(3))

PSE exposures with original effective maturity **≤ 3 months** receive a flat **20%**
risk weight regardless of CQS. No domestic currency condition is required for PSEs
(unlike RGLAs under Art. 115(5)).

### Basel 3.1 Changes

!!! info "CRR vs Basel 3.1"
    PSE risk weight tables are **unchanged** under Basel 3.1 — Tables 2/2A and the
    short-term 20% preferential continue to apply. The key structural change is:

    - **Art. 147A(1):** PSEs receiving 0% SA risk weight are mandatorily SA — no IRB
      permission is available.
    - All other PSEs remain eligible for IRB (mapped to sovereign or institution class
      depending on `entity_type`).

> **Details:** See [SA Risk Weights — PSE](../../specifications/crr/sa-risk-weights.md#pse-exposures-crr-art-116) for the full specification including test scenarios.

### Calculation Examples

**Example 1 — Sovereign-derived (UK PSE):**
```python
# £50m loan to Transport for London (no own ECAI rating)
# UK sovereign CQS = 1 → Table 2 row 1
Risk_Weight = 20%
RWA = £50,000,000 × 20% = £10,000,000
```

**Example 2 — Own-rating:**
```python
# £30m bond issued by a rated European PSE (own CQS 3)
# Table 2A, CQS 3
Risk_Weight = 50%
RWA = £30,000,000 × 50% = £15,000,000
# Note: if sovereign-derived, CQS 3 would give 100% (Table 2)
```

**Example 3 — Short-term:**
```python
# £20m 60-day deposit with a UK PSE (any CQS)
# Art. 116(3): maturity ≤ 3 months → flat 20%
Risk_Weight = 20%
RWA = £20,000,000 × 20% = £4,000,000
```

## Multilateral Development Banks (Art. 117)

### Named MDBs at 0% (Art. 117(2))

The following 16 MDBs receive a **0% risk weight** unconditionally. Set `entity_type = "mdb_named"`
in the counterparty data for these institutions.

| # | Institution | Abbreviation |
|---|-------------|--------------|
| a | International Bank for Reconstruction and Development | IBRD |
| b | International Finance Corporation | IFC |
| c | Inter-American Development Bank | IDB |
| d | Asian Development Bank | ADB |
| e | African Development Bank | AfDB |
| f | Council of Europe Development Bank | CEB |
| g | Nordic Investment Bank | NIB |
| h | Caribbean Development Bank | CDB |
| i | European Bank for Reconstruction and Development | EBRD |
| j | European Investment Bank | EIB |
| k | European Investment Fund | EIF |
| l | Multilateral Investment Guarantee Agency | MIGA |
| m | International Finance Facility for Immunisation | IFFIm |
| n | Islamic Development Bank | IsDB |
| o | International Development Association | IDA |
| p | Asian Infrastructure Investment Bank | AIIB |

!!! info "CRR2 additions"
    Items (o) IDA and (p) AIIB were added by CRR2 (Regulation (EU) 2019/876). The list is
    unchanged in PRA PS1/26 Art. 117(2).

### Other MDBs — Table 2B (Art. 117(1))

MDBs not on the 0% list use **Table 2B** risk weights based on their external credit assessment.
Set `entity_type = "mdb"` in the counterparty data for these institutions.

| CQS | Risk Weight |
|-----|-------------|
| 1   | 20%         |
| 2   | 30%         |
| 3   | 50%         |
| 4   | 100%        |
| 5   | 100%        |
| 6   | 150%        |
| Unrated | 50%     |

!!! warning "Table 2B differs from institution tables"
    MDB Table 2B has CQS 2 = 30% and unrated = 50%, compared to institution Table 3 (CQS 2 = 50%,
    unrated = 40% sovereign-derived). Do not use institution risk weights for non-named MDBs.

Art. 117(1) also names four MDBs that are **not** on the 0% list and therefore use Table 2B:
Inter-American Investment Corporation, Black Sea Trade and Development Bank, Central American
Bank for Economic Integration, and CAF — Development Bank of Latin America.

### Calculation Examples

**Named MDB (0% RW):**

- £25m bond issued by IBRD (World Bank)

```python
# entity_type = "mdb_named" → 0% RW (Art. 117(2))
risk_weight = 0.00
rwa = 25_000_000 * 0.00  # = £0
```

**Non-named MDB (Table 2B):**

- £10m loan to a CQS 3 rated development bank not on the Art. 117(2) list

```python
# entity_type = "mdb" → Table 2B lookup
risk_weight = 0.50  # CQS 3 = 50%
rwa = 10_000_000 * 0.50  # = £5,000,000
```

## Regional Governments and Local Authorities (RGLA)

### Definition

RGLAs are sub-national government entities (CRR Art. 115):

- Devolved administrations (Scotland, Wales, Northern Ireland)
- County, district, unitary, and metropolitan councils
- City of London Corporation
- Combined authorities and mayors' offices

### Treatment Methods (CRR Art. 115)

| Method | Condition | Table | Basis |
|--------|-----------|-------|-------|
| Sovereign-derived | No own ECAI rating | Table 1A (Art. 115(1)(a)) | Sovereign CQS |
| Own-rating | Has own ECAI rating | Table 1B (Art. 115(1)(b)) | RGLA's own CQS |

### Risk Weight Tables

**Table 1A — Sovereign-Derived (Art. 115(1)(a))**

Used when the RGLA has no own ECAI rating — look up the sovereign's CQS:

| Sovereign CQS | RGLA Risk Weight |
|---------------|-----------------|
| 1 | 20% |
| 2 | 50% |
| 3 | 100% |
| 4 | 100% |
| 5 | 100% |
| 6 | 150% |
| Unrated | 100% |

**Table 1B — Own-Rating (Art. 115(1)(b))**

Used when the RGLA has its own ECAI rating:

| CQS | Risk Weight |
|-----|-------------|
| 1 | 20% |
| 2 | 50% |
| 3 | 50% |
| 4 | 100% |
| 5 | 100% |
| 6 | 150% |
| Unrated | 100% |

!!! info "Key difference: CQS 3"
    As with PSEs, CQS 3 receives **100%** under sovereign-derived (Table 1A)
    but only **50%** under own-rating (Table 1B).

### UK-Specific PRA Designations

UK RGLAs benefit from PRA-specific treatments that override the CQS tables above:

| Entity Type | Risk Weight | Basis |
|-------------|-------------|-------|
| UK devolved administrations (Scotland, Wales, NI) | **0%** | PRA designation (sovereign-equivalent) |
| UK local authorities (GBP exposures) | **20%** | PRA designation |
| Domestic-currency RGLA exposures | **20%** | Art. 115(5) |

!!! note "Practical effect for UK banks"
    Most UK RGLA exposures receive 0% (devolved administrations) or 20% (local
    authorities). The CQS-based Tables 1A/1B primarily apply to **foreign** RGLA
    exposures.

### Basel 3.1 Changes

!!! info "CRR vs Basel 3.1"
    RGLA risk weight tables are **unchanged** under Basel 3.1 — Tables 1A/1B,
    the domestic-currency 20%, and UK PRA designations all continue to apply.
    Key structural changes:

    - **Art. 147A(1):** RGLAs receiving 0% SA risk weight (e.g., UK devolved
      administrations) are mandatorily SA — no IRB permission is available.
    - All other RGLAs remain eligible for IRB (mapped to sovereign or institution
      class depending on `entity_type`).

> **Details:** See [SA Risk Weights — RGLA](../../specifications/crr/sa-risk-weights.md#rgla-exposures-crr-art-115) for the full specification. See [Key Differences](../../framework-comparison/key-differences.md#regional-governments-and-local-authorities) for the CRR vs Basel 3.1 comparison.

### Calculation Examples

**Example 1 — UK devolved administration:**
```python
# £100m exposure to Scottish Government
# PRA designation: sovereign-equivalent
Risk_Weight = 0%
RWA = £100,000,000 × 0% = £0
```

**Example 2 — UK local authority:**
```python
# £25m loan to Manchester City Council (GBP)
# PRA designation: UK local authority → 20%
Risk_Weight = 20%
RWA = £25,000,000 × 20% = £5,000,000
```

**Example 3 — Foreign RGLA (sovereign-derived):**
```python
# £15m bond issued by a German Länder (no own ECAI)
# Germany sovereign CQS = 1 → Table 1A row 1
Risk_Weight = 20%
RWA = £15,000,000 × 20% = £3,000,000
```

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

Covered bond risk weights range from 10% (CQS 1) to 100% (CQS 6) for rated bonds (Art. 129(4), Table 6A). Unrated covered bonds are derived from the issuing institution's senior unsecured RW via Art. 129(5), producing values from 10% to 100%. Eligibility requires the issuer to be a regulated credit institution with special public supervision, qualifying cover pool, and investor transparency requirements (Art. 129(7)).

> **Details:** See [Key Differences — Covered Bonds](../../framework-comparison/key-differences.md#covered-bonds-art-129) for the full CQS table.

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
| PSE | 0–150% | Yes (SA-only if 0% RW under B31) |
| MDB (named, Art. 117(2)) | 0% | N/A |
| MDB (other, Table 2B) | 20–150% | N/A |
| RGLA | 0–150% | Yes (SA-only if 0% RW under B31) |
| International Org | 0% | N/A |
| Covered Bonds | 10–100% | Varies |
| High Risk Items (B31 only) | 150% | No |

## Regulatory References

| Topic | CRR Article | BCBS CRE |
|-------|-------------|----------|
| Equity | Art. 133 | CRE20.60-65 |
| Defaulted | Art. 127 | CRE20.80-85 |
| PSE | Art. 116 | CRE20.15-20 |
| MDB | Art. 117 | CRE20.12-14 |
| RGLA | Art. 115 | CRE20.8-10 |
| Covered bonds | Art. 129 | CRE20.27-30 |
| High risk | Art. 128 | CRE20.90 |

## Next Steps

- [Exposure Classes Overview](index.md)
- [Standardised Approach](../methodology/standardised-approach.md)
- [Configuration Guide](../configuration.md)
