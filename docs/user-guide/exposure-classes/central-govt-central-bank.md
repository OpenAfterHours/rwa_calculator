# Central Government and Central Bank Exposures

**Central government and central bank exposures** are claims on governments, central banks, and certain public sector entities treated as sovereigns.

## Definition

Sovereign exposures include:

| Entity Type | Examples |
|-------------|----------|
| Central governments | UK HM Treasury, US Treasury |
| Central banks (`central_bank`) | Bank of England, Federal Reserve |
| The ECB (`central_bank_ecb`) | European Central Bank — unconditional 0%, Art. 114(3) |
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
per Art. 114(3). This provision is identical in both CRR and PRA PS1/26, so the treatment
is **not** regime-gated: it applies no currency test and no rating test, and it overrides
the Art. 114(2) Table 1 CQS ladder.

!!! important "Input convention — tag the ECB with `entity_type = "central_bank_ecb"`"
    The ECB is supranational, so it cannot be identified from `country_code` (it has no
    ISO entry, and using a member state's code would wrongly pull it into the Art. 114(7)
    EU-domestic-currency branch), and a plain `central_bank` cannot be told apart from the
    Bank of England or the Federal Reserve. Set `entity_type = "central_bank_ecb"` on the
    counterparty row — the same convention as `mdb_named` for Art. 117(2) named MDBs. Any
    other central bank keeps `entity_type = "central_bank"`.

    Do not confuse Art. 114(3) with **Art. 114(4)**, which gives 0% to the UK central
    government and the Bank of England *denominated and funded in sterling* — that branch
    is currency-conditional and does not reach a EUR-denominated ECB exposure.

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

The ladder below shows the precedence the engine actually applies. Note that the
**Art. 114(3) ECB branch comes first and is unconditional** — it is not a domestic-currency
treatment, so it does not belong under this heading, but it outranks everything here and is
shown for precedence. See [European Central Bank](#european-central-bank) above.

```python
if counterparty.entity_type == "central_bank_ecb":
    risk_weight = 0.00  # Art. 114(3) ECB — unconditional, both regimes, no currency test
elif counterparty.country_code == "GB" and exposure.currency == "GBP":
    risk_weight = 0.00  # Art. 114(4) UK domestic currency 0% RW
elif is_eu_member(counterparty.country_code) and exposure.currency == domestic_currency(counterparty.country_code):
    risk_weight = 0.00  # Art. 114(7) EU domestic currency 0% RW
    approach = "SA"     # Forced to standardised approach
elif counterparty.cqs is None and counterparty.sovereign_cqs is not None and is_basel_3_1:
    # PS1/26 Art. 114(2A): an unrated central bank takes its government's CQS.
    # Basel 3.1 only — CRR Art. 114 has no paragraph 2A.
    risk_weight = cqs_lookup(counterparty.sovereign_cqs)
else:
    risk_weight = cqs_lookup(counterparty.cqs)  # Standard CQS table; 100% when unrated
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
    under Art. 114(2) using the central government's credit assessment. CRR has no
    equivalent paragraph — its Art. 114 runs 1, 2, 3, 4 and 7 — so the read-across is
    gated to Basel 3.1 by the `central_bank_uses_sovereign_cqs` pack Feature and an
    unrated central bank stays at 100% under CRR.

    **Input requirement:** supply the government's credit quality step as
    `sovereign_cqs` on the central bank's counterparty row. Precedence is: the central
    bank's own `cqs` where it has one (Art. 114(2A) applies only where an assessment
    "is not available"), then `sovereign_cqs`, then the Art. 114(1) 100% fallback if
    neither is present — nothing is inferred when both are absent.

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
