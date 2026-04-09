# Central Government and Central Bank Exposures

**Central government and central bank exposures** are claims on governments, central banks, and certain public sector entities treated as sovereigns.

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

Sovereign risk weights range from 0% (CQS 1) to 150% (CQS 6), with 100% for unrated. UK Government exposures in GBP always receive 0%.

> **Details:** See [SA Risk Weights](../../specifications/crr/sa-risk-weights.md) for the complete risk weight tables by CQS.

## IRB Treatment

Sovereign exposures use the corporate correlation formula. F-IRB uses supervisory LGD (45% senior); A-IRB uses bank estimates.

> **Details:** See [IRB Approach](../methodology/irb-approach.md) for the full formula, correlation, and maturity adjustment details. See [Key Differences](../../framework-comparison/key-differences.md#irb-approach-restrictions) for Basel 3.1 restrictions (sovereigns are mandatorily SA).

## Domestic Sovereign

### UK Domestic Currency Treatment (Art. 114(4))

Exposures to the **UK central government and central bank** denominated and funded
in **GBP** receive a **0% risk weight**, regardless of external credit rating or CQS.

This applies to:
- Treasury bonds (Gilts) denominated in GBP
- National Savings products
- Loans to HM Treasury in GBP
- Bank of England reserves in GBP

The override requires both:
1. Counterparty `country_code = "GB"` (UK sovereign or central bank)
2. Exposure `currency = "GBP"` (denominated in sterling)

Exposures to UK sovereign entities in **foreign currencies** (e.g. USD-denominated Gilts)
fall back to the standard CQS-based risk weight table.

### ECB Treatment (Art. 114(3))

Exposures to the **European Central Bank** receive a **0% risk weight** unconditionally,
per Art. 114(3). This provision is identical in both CRR and PRA PS1/26.

### EU Domestic Currency Treatment (Art. 114(7))

Exposures to **EU member state central governments and central banks** denominated in
that member state's **domestic currency** receive a **0% risk weight**, regardless of
external credit rating or CQS.

!!! warning "Regulatory Basis — Third-Country Reciprocity"
    In the UK-onshored CRR, Art. 114(4) was narrowed from the original EU CRR
    (which covered all member states) to apply only to the **UK central government
    and Bank of England in sterling**. Post-Brexit, the 0% treatment for EU member
    state domestic-currency sovereign exposures is provided by **Art. 114(7)** —
    the third-country reciprocity provision, which allows UK firms to apply 0%
    where the third country's supervisory regime is deemed equivalent. PRA PS1/26
    Art. 114(7) is not re-enacted in the PRA Rulebook but is preserved by
    cross-reference to CRR Art. 114(7) via PS1/26 Art. 114(1)(b).

This applies to all 27 EU member states:

- **Eurozone members** (AT, BE, CY, DE, EE, ES, FI, FR, GR, HR, IE, IT, LT, LU, LV,
  MT, NL, PT, SI, SK): domestic currency is **EUR**
- **Non-euro EU members**: BG (BGN), CZ (CZK), DK (DKK), HU (HUF), PL (PLN),
  RO (RON), SE (SEK)

Each member state's domestic currency must match — e.g., a Polish sovereign exposure
in EUR does **not** qualify (EUR is not Poland's domestic currency), but a Polish
sovereign exposure in PLN does.

EU domestic sovereign exposures are also **forced to the Standardised Approach (SA)**,
even if the firm has IRB permissions for the CGCB exposure class. This ensures the
regulatory 0% RW is applied rather than an internal model estimate.

### Treatment

```python
if counterparty.country_code == "GB" and exposure.currency == "GBP":
    risk_weight = 0.00  # Art. 114(4) UK domestic currency 0% RW
elif is_eu_member(counterparty.country_code) and exposure.currency == domestic_currency(counterparty.country_code):
    risk_weight = 0.00  # Art. 114(7) EU domestic currency 0% RW
    approach = "SA"     # Forced to standardised approach
else:
    risk_weight = cqs_lookup(counterparty.cqs)  # Standard CQS table
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

| Central Bank | Sovereign Link | Risk Weight | Basis |
|--------------|----------------|-------------|-------|
| Bank of England | UK Government | 0% | Art. 114(4) — domestic currency |
| European Central Bank | N/A | 0% | Art. 114(3) — unconditional |
| Federal Reserve | US Government | 0-20% | Art. 114(2) — sovereign CQS |

!!! info "Basel 3.1 — Unrated Central Banks (Art. 114(2A))"
    PRA PS1/26 introduces Art. 114(2A): where a central bank has **no ECAI rating**
    but its **central government** does, the central bank exposure shall be treated
    under Art. 114(2) using the central government's credit assessment. This codifies
    what was previously implicit practice. CRR has no equivalent paragraph.

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

Government bonds as collateral receive low haircuts (0.5%–4% for CQS 1 depending on residual maturity).

> **Details:** See [Credit Risk Mitigation](../methodology/crm.md) for the complete haircut tables.

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
| Risk weights (ECAI) | Art. 114(2) | CRE20.11 |
| ECB 0% RW | Art. 114(3) | — |
| UK domestic currency 0% RW | Art. 114(4) | CRE20.9 |
| Third-country domestic currency | Art. 114(7) | CRE20.9 |
| Central bank = sovereign | Art. 114; PS1/26 Art. 114(2A) | CRE20.8 |
| MDB treatment | Art. 117 | CRE20.12-14 |

## Next Steps

- [Institution Exposures](institution.md)
- [Standardised Approach](../methodology/standardised-approach.md)
- [IRB Approach](../methodology/irb-approach.md)
