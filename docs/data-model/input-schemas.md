---
verified: "2026-09-05 @ 0.3.32"
---

# Input Data Schemas

This page documents the authoritative schemas for all input data files required by the RWA calculator. These schemas are defined in `src/rwa_calc/data/schemas.py` and represent the single source of truth.

## Quick Reference

| Data Category | File(s) | Required | Purpose |
|---------------|---------|----------|---------|
| [Counterparty](#counterparty-schema) | `counterparty/counterparties.parquet` | Yes | Borrower/obligor information |
| [Facility](#facility-schema) | `exposures/facilities.parquet` | Yes | Committed credit limits |
| [Loan](#loan-schema) | `exposures/loans.parquet` | Yes | Drawn exposures |
| [Contingent](#contingent-schema) | `exposures/contingents.parquet` | No | Off-balance sheet items |
| [Collateral](#collateral-schema) | `collateral/collateral.parquet` | No | Security/collateral |
| [Guarantee](#guarantee-schema) | `guarantee/guarantee.parquet` | No | Credit protection |
| [Provision](#provision-schema) | `provision/provision.parquet` | No | IFRS 9 provisions |
| [Rating](#rating-schema) | `ratings/ratings.parquet` | No | Credit ratings |
| [FX Rates](#fx-rates-schema) | `fx_rates/fx_rates.parquet` | No | Currency conversion rates |
| [Specialised Lending](#specialised-lending-schema) | `ratings/specialised_lending.parquet` | No | Slotting approach data |
| [SFT Trade](#sft-input-schemas-fccm) | `ccr/sft_trades.parquet` | No | FCCM SFT EAD (CCR — Art. 220–223) |
| [SFT Collateral](#sft-input-schemas-fccm) | `ccr/sft_collateral.parquet` | No | Optional collateral for FCCM SFTs |
| [Equity Exposure](#equity-exposure-schema) | N/A | No | Equity holdings |
| [CIU Holdings](#ciu-holdings-schema) | N/A | No | Per-fund holdings for CIU look-through (Art. 132) |
| [Model Permissions](#model-permissions-schema) | `config/model_permissions.parquet` | No | Per-model IRB approach permissions |

**Mapping Files:**

| Mapping | File | Purpose |
|---------|------|---------|
| [Facility Mapping](#facility-mapping-schema) | `exposures/facility_mapping.parquet` | Facility-to-loan hierarchy |
| [Org Mapping](#org-mapping-schema) | `mapping/org_mapping.parquet` | Organisation hierarchy (rating inheritance) |
| [Lending Mapping](#lending-mapping-schema) | `mapping/lending_mapping.parquet` | Lending groups (retail threshold aggregation) |
| [Reporting Entity](#multi-entity-reporting-schemas) | `config/reporting_entities.parquet` | Reporting-hierarchy registry (individual / sub-consolidated / consolidated submissions) |
| [Book-Entity Mapping](#multi-entity-reporting-schemas) | `mapping/book_entity_mapping.parquet` | Booking book &rarr; reporting entity, for scoped runs |

---

## Counterparty Schema

**Purpose:** Defines borrower/obligor information used for exposure classification, risk weight determination, and hierarchy resolution.

**File:** `counterparty/counterparties.parquet`

| Column | Type | Required | Description |
|--------|------|----------|-------------|
| `counterparty_reference` | `String` | Yes | Unique identifier for the counterparty |
| `counterparty_name` | `String` | No | Legal name of the counterparty |
| `entity_type` | `String` | Yes | **Single source of truth** for exposure class (see valid values below). An unrecognised value raises **DQ006**; a **null** value is filed under the residual `other` class (100% SA, any rating unused) and raises warning **CLS013** naming the counterparty (the fallback class is unchanged: the true class, and so the direction of error, is unknown) |
| `country_code` | `String` | No | ISO 3166-1 alpha-2 country code |
| `annual_revenue` | `Float64` | No | Annual revenue in GBP. The SME size test (CRR EUR 50m; Basel 3.1 not more than GBP 44m) and the Basel 3.1 Art. 147(4C) large-corporate test read the **group** figure: the max of this value and every `org_mapping` ancestor's (a parent's value is taken as its consolidated accounts). Under Basel 3.1 a corporate with no revenue anywhere in its group is not an SME (CLS015) |
| `total_assets` | `Float64` | No | Total assets in GBP. LFSE threshold: EUR 70bn on the entity's own figure under CRR Art. 142(1)(4); GBP 79bn under PS1/26 Glossary p. 78, taken at the highest level of consolidation (max over the entity and its `org_mapping` ancestors). CRR only: the SME balance-sheet fallback (EUR 43m, group figure) when no turnover is known |
| `default_status` | `Boolean` | No | Whether counterparty is in default |
| `sector_code` | `String` | No | Industry sector code (SIC-based) |
| `apply_fi_scalar` | `Boolean` | No | User flag: True = apply 1.25x FI correlation scalar (CRR Art. 153(2)) |
| `is_managed_as_retail` | `Boolean` | No | Retail pool-management attestation. **Basel 3.1**: a non-SME natural person is *regulatory* retail only when True (PS1/26 Art. 123A(1)(b)(iii)); otherwise it stays in the retail class (Art. 123(1)(a)) as non-regulatory retail at 100% (Art. 123(3)(c)). An omitted flag loads as False. An explicit False also keeps a natural person out of the IRB retail class (Art. 147(5)(c)). **CRR**: SME managed on pooled retail basis (75% RW per CRR Art. 123); not read for natural persons |
| `is_natural_person` | `Boolean` | No | True for individuals (natural persons). Required to qualify a counterparty for the SA retail exposure class (CRR Art. 123 / PS1/26 Art. 123 — the class is restricted to "natural persons or to a small or medium-sized enterprise"). Also drives the Basel 3.1 retail RE classification gates (PS1/26 Art. 124E(1) primary-residence exception, Art. 124H natural-person CRE branch) |
| `is_social_housing` | `Boolean` | No | True for social-housing providers. Under CRR Art. 123(d), exposures to a "social housing provider, or [a] non-profit association regulated by law" are eligible for retail-class treatment without the natural-person test. Under Basel 3.1 the same population qualifies for the Art. 124E(1) materially-dependent exception so the loan-splitter treats it as non-income-producing residential RE (PRA PS1/26) |
| `is_financial_sector_entity` | `Boolean` | No | True for financial sector entities (FSEs) as defined in CRR Art. 119(5) — credit institutions, investment firms, financial institutions, insurance and reinsurance undertakings, and similar regulated/unregulated entities. Used in conjunction with `apply_fi_scalar` and `total_assets` for the LFSE 1.25x correlation gate (Art. 142(1)(4) — "large financial sector entity") |
| `is_ccp_client_cleared` | `Boolean` | No | True when the counterparty is a CCP whose exposures arise from client-cleared trades — drives the QCCP 4% RW (vs 2% proprietary) under CRR Art. 306 / PS1/26 Art. 306 |
| `borrower_income_currency` | `String` | No | ISO 4217 currency in which the borrower earns income (or, for RRE indexation, the currency in which the borrower's repayment cashflows are denominated). Drives **PRA PS1/26 Art. 123B** (Basel 3.1): when the *lending* currency (the loan's denomination — `original_currency` once FX conversion has run, never the reporting currency) differs from it on an unhedged retail / residential RE exposure, the RW is multiplied by 1.5 (capped at 150%). **Null** takes the Art. 123B(3) fallback: the 1.5x applies unless the lending currency equals the obligor's domestic currency (`local_currency`, else the domestic currency of `country_code`), and warning **SA010** counts the rows. Also read by the **PS1/26 Art. 124(2)(c)** RRE primary-residence carve-out — only available where the exposure currency matches the currency of the borrower's repayment cashflows |
| `local_currency` | `String` | No | Counterparty's domestic currency (ISO 4217). Two use sites: (1) **CRR Art. 114(4) sovereign domestic-currency carve-out** — exposures to a central government or central bank denominated **and** funded in that sovereign's own domestic currency may receive a 0% RW regardless of CQS (compared to `currency` on the loan/facility row); (2) the PS1/26 Art. 123B(3) fallback when `borrower_income_currency` is null — the 1.5x currency-mismatch multiplier is waived where the lending currency equals `local_currency` (when absent, the domestic currency of `country_code` is used: GB → GBP, EU member states from the pack; any other or null country cannot establish the exception, so the multiplier applies). Distinct from `borrower_income_currency`, which is the obligor's actual income currency |
| `sovereign_cqs` | `Int32` | No | External CQS for the counterparty's **sovereign** (i.e. the central government of the country in `country_code`). Counterparty-level — distinct from the row-level `external_cqs` derived on each exposure (which captures the obligor's own rating, not its sovereign). Primary use site is the SA sovereign risk weight table (CRR Art. 114(2) / PS1/26 Art. 114(2) — exposures to central governments and central banks rated by a nominated ECAI). Drives the **domestic-currency preferential treatment** (CRR Art. 114(4): exposures to the sovereign and central bank denominated and funded in the domestic currency may receive 0% RW), the **third-country preferential treatment** (CRR Art. 114(5)–(6): same treatment for non-EU/UK sovereigns where the third country applies an equivalent supervisory regime). Also feeds the **sovereign-derived institution floor** (CRR Art. 119(2) — institution RW must not be more favourable than its home sovereign's RW; PS1/26 Art. 121(1) Table 5 derives unrated-institution SCRA grades from the home sovereign's CQS), and SCRA derivations |
| `institution_cqs` | `Int8` | No | External CQS for the counterparty when treated as an **institution** — counterparty-level field, distinct from the row-level `external_cqs` derived on each exposure. Used by ECRA institution risk weights (CRR Art. 120 Table 3 / PS1/26 Art. 120 Table 3). Under ECRA, rated institutions take a CQS-driven RW; unrated institutions fall through to SCRA (PS1/26 Art. 121, where unrated grades may themselves be derived from the home sovereign via Art. 121(1) Table 5). When both `sovereign_cqs` and `institution_cqs` are populated, the sovereign floor at Art. 119(2) caps the institution treatment |
| `scra_grade` | `String` | No | SCRA grade for unrated institutions: `"A"`, `"A_ENHANCED"`, `"B"`, `"C"` (Basel 3.1 CRE20.16-21 / PRA PS1/26 Art. 121). Use `"A_ENHANCED"` when the counterparty satisfies the Art. 121(5) quantitative thresholds (CET1 ratio &ge; 14% **and** leverage ratio &ge; 5%) — yields a 30% RW (>3m) vs the standard Grade A 40% (>3m) / 20% (&le;3m) weights. |
| `is_investment_grade` | `Boolean` | No | Publicly traded + investment grade → 65% SA RW (Basel 3.1 CRE20.47) |

### Entity Type: The Single Source of Truth

The `entity_type` field is the **authoritative source** for determining both SA and IRB exposure classes. Each entity type maps to specific exposure classes for each approach. This design ensures consistent classification across the calculation pipeline.

**Valid `entity_type` values:**

| Entity Type | SA Exposure Class | IRB Exposure Class | Regulatory Reference |
|-------------|-------------------|--------------------|-----------------------|
| **Sovereign Class** |
| `sovereign` | CENTRAL_GOVT_CENTRAL_BANK | CENTRAL_GOVT_CENTRAL_BANK | CRR Art. 112(a) |
| `central_bank` | CENTRAL_GOVT_CENTRAL_BANK | CENTRAL_GOVT_CENTRAL_BANK | CRR Art. 112(a) |
| **RGLA Class** (Regional Governments/Local Authorities) |
| `rgla_sovereign` | RGLA | CENTRAL_GOVT_CENTRAL_BANK | CRR Art. 115 - has taxing powers/govt guarantee |
| `rgla_institution` | RGLA | INSTITUTION | CRR Art. 115 - no sovereign equivalence |
| **PSE Class** (Public Sector Entities) |
| `pse_sovereign` | PSE | CENTRAL_GOVT_CENTRAL_BANK | CRR Art. 116 - govt guaranteed |
| `pse_institution` | PSE | INSTITUTION | CRR Art. 116 - commercial PSE |
| **MDB/International Org Class** |
| `mdb` | MDB | INSTITUTION (CRR only) | CRR Art. 147(4)(c) — an MDB not carrying a 0% Art. 117 RW is assigned to the **institutions** IRB class, and SA prices it from the institution tables (Art. 117(1)). Not applicable under PS1/26 Art. 147(3)(f), where every MDB is quasi-sovereign and SA uses the dedicated Table 2B (Art. 117(1)(a)) |
| `mdb_named` | MDB | CENTRAL_GOVT_CENTRAL_BANK | CRR Art. 117(2) / PS1/26 Art. 117(2) — named MDBs on the eligible list (e.g. IBRD, IFC, EIB, EBRD) qualify for **0% RW**. Use `mdb` for non-named MDBs that fall back to the institution / Table 2B treatment |
| `international_org` | MDB | CENTRAL_GOVT_CENTRAL_BANK | CRR Art. 118 — international organisations (e.g. IMF, BIS); 0% RW |
| **Institution Class** |
| `institution` | INSTITUTION | INSTITUTION | CRR Art. 112(d) |
| `bank` | INSTITUTION | INSTITUTION | CRR Art. 112(d) |
| `ccp` | INSTITUTION | INSTITUTION | CRR Art. 300-311 (CCP treatment) |
| `financial_institution` | INSTITUTION | INSTITUTION | CRR Art. 112(d) |
| **Covered Bond Class** |
| `covered_bond` | COVERED_BOND | COVERED_BOND | CRR Art. 129 / PS1/26 Art. 129 — eligible covered bonds. Rated: CQS lookup against Table 6A (CRR) / Table 7 (B31). Unrated: derived from issuing institution's senior unsecured RW per Art. 129(5). B31 adds new due-diligence requirement (Art. 129(4A)) and expands the unrated derivation table from 4 to 7 entries |
| **Corporate Class** |
| `corporate` | CORPORATE | CORPORATE | CRR Art. 112(g) |
| `company` | CORPORATE | CORPORATE | CRR Art. 112(g) |
| **Retail Class** |
| `individual` | RETAIL_OTHER | RETAIL_OTHER | CRR Art. 112(h) |
| `retail` | RETAIL_OTHER | RETAIL_OTHER | CRR Art. 112(h) |
| **Specialised Lending Class** |
| `specialised_lending` | SPECIALISED_LENDING | SPECIALISED_LENDING | CRR Art. 147(8) |
| **Equity Class** |
| `equity` | EQUITY | EQUITY | CRR Art. 133 |
| **High-Risk Class (Basel 3.1 only — see warning below)** |
| `high_risk` | HIGH_RISK | HIGH_RISK | PS1/26 Art. 128 — generic "items associated with particularly high risk"; **150% RW**. Assessment criteria per Art. 128(3): high risk of loss from obligor default; impossible to assess on standard data |
| `high_risk_venture_capital` | HIGH_RISK | HIGH_RISK | PS1/26 Art. 128 — venture capital exposures held outside the equity exposure class (priority 3 equity takes precedence; this bucket is for non-equity VC exposures only). 150% RW |
| `high_risk_private_equity` | HIGH_RISK | HIGH_RISK | PS1/26 Art. 128 — private-equity exposures held outside the equity exposure class. 150% RW |
| `high_risk_speculative_re` | HIGH_RISK | HIGH_RISK | PS1/26 Art. 128 — speculative immovable property financing (e.g. land acquisition with uncertain end use). 150% RW. Distinct from ADC (Art. 124K) which has its own loan-splitter treatment |
| **Other Items Class (CRR Art. 134 / PS1/26 Art. 134)** |
| `other_cash` | OTHER | OTHER | CRR Art. 134(3) / PS1/26 Art. 134(3) — cash in hand and equivalent items; **0% RW** |
| `other_gold` | OTHER | OTHER | CRR Art. 134(4) / PS1/26 Art. 134(4) — gold bullion held in own vaults or on an allocated basis (backed by bullion liabilities); **0% RW** |
| `other_items_in_collection` | OTHER | OTHER | CRR Art. 134(3) / PS1/26 Art. 134(3) — cash items in the process of collection; **20% RW** |
| `other_tangible` | OTHER | OTHER | CRR Art. 134(1)/(2) / PS1/26 Art. 134(1)/(2) — other tangible assets, prepayments, and accrued income (where the counterparty cannot be identified); **100% RW** |
| `other_residual_lease` | OTHER | OTHER | CRR Art. 134(7) / PS1/26 Art. 134(7) — residual value of leasing exposures (i.e. the portion not captured as a lease receivable on the obligor); **100% RW**. For the receivable leg see [Lease exposures](#lease-exposures-the-drawn_amount-convention) |

!!! warning "Art. 128 (high-risk items) is omitted from current UK CRR"
    Art. 128 was **omitted from UK onshored CRR by SI 2021/1078** (the Capital Requirements Regulation (Amendment) Regulations 2021). The high-risk exposure class is therefore a **dead letter under current UK CRR (pre-2027)** — exposures tagged with any `high_risk*` `entity_type` will fall through to other classes under a CRR-mode run. The class is **re-introduced under PRA PS1/26 Art. 128** with effect 1 January 2027. Use the `high_risk*` entity types only when running in Basel 3.1 mode, or accept that the row will be reclassified under CRR. See [SA risk weights spec - High-risk exposures](../specifications/crr/sa-risk-weights.md#high-risk-exposures-art-128).

### Why SA and IRB Classes Can Differ

For certain entity types, the regulatory treatment differs between SA and IRB approaches:

- **RGLA/PSE with sovereign treatment**: Under SA, these use dedicated RGLA/PSE risk weight tables. Under IRB, those with government guarantees or taxing powers use the central govt/central bank IRB formula.
- **RGLA/PSE with institution treatment**: Under SA, these use RGLA/PSE tables. Under IRB, commercial PSEs without sovereign backing use the institution IRB formula.
- **MDB/International Orgs**: Under SA, named MDBs (Art. 117(2)) receive 0% RW; other MDBs use institution tables (CRR) or dedicated Table 2B (Basel 3.1). Under IRB, they use the central govt/central bank formula.

### Additional Classification Flags

| Column | Purpose | When Used |
|--------|---------|-----------|
| `apply_fi_scalar` | Directly controls whether FI scalar (1.25x correlation) applies | Financial sector entities with this flag set to True get FI scalar under IRB (CRR Art. 153(2)) |
| `is_managed_as_retail` | SME managed on pooled retail basis | Can use 75% RW under SA (CRR Art. 123) |

### Financial Sector Entity (FSE) and FI Scalar

The **1.25x correlation multiplier** (Art. 153(2)) applies to **large financial sector entities (LFSEs)** and **unregulated financial sector entities**. The LFSE total-assets threshold differs by framework:

| Framework | LFSE threshold | Citation |
| --- | --- | --- |
| CRR | Total assets ≥ **EUR 70 billion** | CRR Art. 142(1)(4) |
| Basel 3.1 | Total assets ≥ **GBP 79 billion** | PS1/26 Glossary p. 78 (Note: "corresponds to Article 142(1)(4) of CRR") |

**How it works in the calculator:** the classifier derives `requires_fi_scalar` for a counterparty flagged `is_financial_sector_entity = True` whose total assets meet the framework threshold — the entity's own `total_assets` under CRR (Art. 142(1)(4)(a): "calculated on an individual or consolidated basis"), the **group** figure (max over the entity and its `org_mapping` ancestors) under Basel 3.1 (glossary: "taken at the highest level of consolidation at which audited financial statements are available"). `apply_fi_scalar = True` remains an authoritative override (an unregulated FSE, or an LFSE whose size data is incomplete); it can never suppress a derived True. A flagged FSE whose asset figure is null and that carries no election raises CLS009.

!!! warning "Two distinct thresholds — do not conflate"
    - **LFSE total-assets threshold** (EUR 70bn CRR / GBP 79bn B31) → 1.25x correlation multiplier (Art. 153(2), both CRR and Basel 3.1). Applies to the asset correlation coefficient R, not to the capital requirement directly.
    - **GBP 440m annual revenue** → F-IRB only approach restriction (Art. 147A(1)(e), Basel 3.1 only). Does not affect correlation.

    These thresholds serve entirely different purposes and apply to different entity populations. See [Key Differences](../framework-comparison/key-differences.md#financial-sector-correlation-multiplier) for details.

**Example:**

```python
import polars as pl

counterparties = pl.DataFrame({
    "counterparty_reference": ["CORP_001", "CORP_002", "SOV_001", "BANK_001", "PSE_001"],
    "counterparty_name": ["Acme Corp Ltd", "Beta Industries PLC", "UK Treasury", "Major Bank PLC", "Local Council"],
    "entity_type": ["corporate", "corporate", "sovereign", "bank", "pse_sovereign"],
    "country_code": ["GB", "GB", "GB", "GB", "GB"],
    "annual_revenue": [25_000_000.0, 500_000_000.0, None, None, None],
    "total_assets": [30_000_000.0, 600_000_000.0, None, 80_000_000_000.0, 500_000_000.0],
    "default_status": [False, False, False, False, False],
    "sector_code": ["62.01", "28.11", None, "64.19", None],
    "apply_fi_scalar": [False, False, False, False, False],
    "is_managed_as_retail": [False, False, False, False, False],
})
```

### Classification Algorithm Summary

The classifier (`engine/classify/`) processes counterparties through these steps:

1. **Entity Type Mapping**: Maps `entity_type` to both SA and IRB exposure classes
2. **SME Classification**: Checks if `annual_revenue < EUR 50m` for corporates
3. **Retail Threshold**: Aggregates exposures by lending group against retail threshold (EUR 1m CRR / GBP 880k Basel 3.1)
4. **Default Identification**: Checks `default_status` for defaulted treatment
5. **FI Scalar Determination**: Identifies large/unregulated FSEs for 1.25x correlation
6. **Approach Assignment**: Assigns SA/F-IRB/A-IRB/Slotting based on IRB permissions

See [Classification](../features/classification.md) for the complete classification algorithm.

---

## Facility Schema

**Purpose:** Defines committed credit facilities (parent nodes in exposure hierarchy). Facilities represent credit limits; actual drawings are captured in the Loan schema.

**File:** `exposures/facilities.parquet`

| Column | Type | Required | Description |
|--------|------|----------|-------------|
| `facility_reference` | `String` | Yes | Unique identifier for the facility |
| `product_type` | `String` | No | Product classification |
| `book_code` | `String` | No | Portfolio/book classification |
| `counterparty_reference` | `String` | Yes | Link to counterparty |
| `value_date` | `Date` | No | Facility start date |
| `maturity_date` | `Date` | No | Final maturity date — used to derive `M` for IRB unless `effective_maturity` is populated |
| `facility_termination_date` | `Date` | No | Bank's contractual right-to-terminate date — overrides `maturity_date` for IRB `M` derivation when shorter (Art. 162(2)(g)) |
| `currency` | `String` | No | ISO 4217 currency code — the currency the `limit` is advised in. Undrawn headroom is netted in it: every mapped loan / contingent amount is first converted into it at the run's `fx_rates` (`amount × rate(child → reporting) / rate(facility → reporting)`). An amount the run has no rate for is **not** netted, and **HIE005** names the facility and the currency. With `apply_fx_conversion=False` amounts are netted as supplied |
| `limit` | `Float64` | No | The limit **offered to and accepted by the obligor** — the extent of the commitment (CRR Art. 4(1)(56): "determined by the advised limit"). Undrawn headroom = `limit` − mapped utilisation. A null limit on a facility that is not an MOF umbrella generates no undrawn exposure and raises **HIE006** (on an umbrella a null limit means "uncapped above the sub-limits") |
| `committed` | `Boolean` | No | Whether the unused headroom is a commitment the bank cannot cancel unconditionally (default `True`). `True`: a commitment priced at its own `risk_type`. `False`: an **accepted, unconditionally cancellable (UCC) commitment** — its `facility_undrawn` row is still generated, and is priced in the UCC bucket `LR` whatever `risk_type` says (CRR Annex I 4(a) 0%; PS1/26 Table A1 row (7) 10%; a non-`LR` `risk_type` raises **HIE004**). PS1/26's glossary defines a commitment as an arrangement "offered by the institution and accepted by the obligor", expressly including one that "may be ... unconditionally cancelled by the institution at any time without prior notice". **An internal limit that was never offered to and accepted by the obligor is not a commitment at all** and must not be supplied as headroom: set `limit` to the accepted amount, or 0. On an MOF sub-facility the sub's own flag governs its waterfall row; an uncommitted sub-line takes headroom only from an uncommitted or uncapped umbrella (see [Hierarchy & Classification](../specifications/common/hierarchy-classification.md#multi-option-facility-mof-waterfall-allocation)). Loans and contingents mapped to the facility always flow as their own exposure rows |
| `lgd` | `Float64` | No | Internal LGD estimate (A-IRB) |
| `lgd_unsecured` | `Float64` | No | A-IRB unsecured LGD estimate, applied to the residual EAD after eligible collateral (CRR Art. 181) |
| `beel` | `Float64` | No | Best estimate expected loss |
| `has_sufficient_collateral_data` | `Boolean` | No | A-IRB attestation that the firm has data quality sufficient to recognise own-estimate collateral effects under Art. 181(1)(f). When `False`, the LGD floor framework treats the row as if no collateral data is available |
| `is_revolving` | `Boolean` | No | Revolving vs term facility (default `False`) |
| `is_qrre_transactor` | `Boolean` | No | QRRE transactor flag. Drives the Basel 3.1 SA 45% weight (Art. 123(3)(a)) and the IRB 0.05% PD floor (Art. 163(1)(c)). True iff the revolving account has been repaid in full at each scheduled repayment date for the previous 12 months, OR the overdraft has not been drawn for the previous 12 months (PRA Glossary p. 9). Per Art. 154(4), accounts with less than 12 months of repayment history must be flagged False. Assessed upstream — not validated by the calculator. See [Transactor Exposure](../appendix/glossary.md#transactor-exposure). |
| `seniority` | `String` | No | `senior` (default) or `subordinated` (affects F-IRB LGD) |
| `risk_type` | `String` | No | Off-balance sheet risk category (see below) |
| `underlying_risk_type` | `String` | No | Underlying-exposure risk type used by the CRM substitution path when the facility's own `risk_type` would otherwise mask the protection's true category |
| `obs_product` | `String` | No | Concrete off-balance-sheet product key — the route to a bucket when `risk_type` is blank (see [Concrete product keys](#concrete-product-keys-obs_product)). An explicit `risk_type` always wins |
| `ccf_modelled` | `Float64` | No | A-IRB modelled CCF (0.0-1.5) |
| `ead_modelled` | `Float64` | No | Basel 3.1 A-IRB own estimate of EAD (PS1/26 Art. 166D(3)/(4)) — when populated on a **revolving loan commitment** (`is_revolving` and `is_obs_commitment`, not a flagged purchased-receivables commitment) it replaces the `drawn_amount + ccf x undrawn_amount` derivation, floored by Art. 166D(5)(b)/(c). Ignored on every other row and under CRR |
| `is_short_term_trade_lc` | `Boolean` | No | Short-term self-liquidating trade finance arising from the movement of goods (CRR Art. 166(8)(b) F-IRB 20% CCF; PS1/26 Art. 120(2A)/121(4) six-month SA window; Art. 162(3) one-day M floor). A drawn loan inherits the flag **only from its own parent facility** (`facility_mappings`), never from another facility of the same counterparty |
| `is_obs_commitment` | `Boolean` | No | `True` (facility default) for a commitment / credit line, `False` for an issued item. Selects CRR F-IRB Art. 166(8)(d) 75% vs the Art. 166(10) issued-item scale, the Basel 3.1 Table A1 Row 5 vs Row 3 residual, and Basel 3.1 A-IRB own-estimate eligibility (Art. 166D(1)(a): revolving loan **commitments** only) |
| `is_uk_residential_mortgage_commitment` | `Boolean` | No | Basel 3.1 Table A1 Row 4(b) 50% UK residential mortgage commitment. **Tri-state, no default**: `True` / `False` are honoured; null is derived (see [UK residential mortgage commitments](#uk-residential-mortgage-commitments)). No effect under CRR |
| `is_purchased_receivable_commitment` | `Boolean` | No | Undrawn purchase commitment for revolving purchased receivables (with `is_revolving`). Basel 3.1 **IRB rows only**: PS1/26 Art. 166A(5) fixes 40% (10% for an `LR` unconditionally cancellable one), no own estimate. SA rows keep their Table A1 bucket (factoring with recourse is `FRC` 100%). No effect under CRR. Default `False` |
| `is_payroll_loan` | `Boolean` | No | Payroll-deduction / pension lending — qualifies for the Basel 3.1 35% retail RW (PS1/26 Art. 123(2)) |
| `is_buy_to_let` | `Boolean` | No | Buy-to-let property lending — excluded from SME supporting factor (CRR Art. 501) |
| `has_one_day_maturity_floor` | `Boolean` | No | Set True for exposures eligible for the Art. 162(3) one-day `M` floor (daily-margined SFTs / derivatives / margin lending, and the qualifying short-term exposures). The one day **replaces the one-year minimum**: `M = max(residual maturity, 1/365)` where the residual is under one year; otherwise the standard chain applies. Self-liquidating trade flagged `is_short_term_trade_lc` derives it automatically (CRR residual up to one year; Basel 3.1 less than one year) |
| `is_sft` | `Boolean` | No | Securities Financing Transaction — selects the F-IRB **0.5-year** repo-style supervisory maturity (`M`) under CRR **Art. 162(1)** (a fixed value, not a floor; deleted under Basel 3.1) |
| `effective_maturity` | `Float64` | No | Explicit numeric `M` override (years) per CRR Art. 162(3) / PS1/26. When populated it supersedes the `maturity_date`-derived `M` and bypasses the 1-year floor — firm-owned judgement for short-term carve-outs |
| `intragroup_entity_reference` | `String` | No | Non-null tags this facility as an intragroup claim on the named reporting entity (an `entity_reference` in the [Reporting Entity registry](#multi-entity-reporting-schemas)). Null (default) = external counterparty. Eliminated on a `consolidated` / `sub_consolidated` run, retained on `individual` — see [Multi-Entity Reporting](../features/multi-entity-reporting.md) |
| `is_under_irb_rollout` | `Boolean` | No | CRR Art. 148: True if this SA-treated exposure is covered by the firm's approved sequential-implementation (roll-out) plan to move to IRB. A reporting-only flag — it changes no RWA/EAD; it splits the SA coverage in COREP C 08.07 / OF 08.07 into col 0040 (% subject to a roll-out plan) and col 0030 (% permanent partial use, Art. 150). Default False (permanent partial use) |

**Valid `product_type` values:**

| Value | Description |
|-------|-------------|
| `rcf` | Revolving credit facility |
| `term_loan` | Term loan facility |
| `mortgage` | Mortgage facility |
| `overdraft` | Overdraft facility |
| `credit_card` | Credit card facility |
| `trade_finance` | Trade finance facility |
| `guarantee` | Guarantee facility |
| `project_finance` | Project finance |

**Valid `seniority` values:**

| Value | F-IRB LGD | Description |
|-------|-----------|-------------|
| `senior` | 45% | Senior unsecured claims |
| `subordinated` | 75% | Subordinated claims |

**Valid `risk_type` values (CRR Art. 111 Annex I / PRA PS1/26 Art. 111 Table A1):**

| Code | Full Value | CRR SA | CRR F-IRB | Basel 3.1 SA / F-IRB | Use for |
|------|------------|--------|-----------|----------------------|---------|
| `FR` | `full_risk` | 100% | 100% | 100% (Row 1) | Issued credit substitutes: financial guarantees, acceptances, endorsements, credit derivatives, **credit-substitute** standby LCs |
| `FRC` | `full_risk_commitment` | 100% | 100% | 100% (Row 2) | Commitments with certain drawdown / with recourse: factoring and invoice discounting with recourse, forward purchases and deposits, repos, partly-paid shares |
| `MR` | `medium_risk` | 50% | 75% commitment / 50% issued | 50% (Row 4(a)) | NIFs and RUFs only |
| `MR_ISSUED` | `medium_risk_issued` | 50% | 50% | 50% (Row 3) | Other issued items that are not credit substitutes. Under CRR also documentary credits not secured by the shipment, shipping guarantees, customs and tax bonds (Annex I 2(a), 2(b)(i)) — which Basel 3.1 puts in Row 6 at 20%, so prefer `obs_product` for those |
| `OC` | `other_commit` | 50% (> 1y original maturity) / 20% (≤ 1y) | 75% | 40% (Row 5) | **Every ordinary committed undrawn facility** (revolvers, term-loan drawdowns, overdrafts that are not unconditionally cancellable) |
| `MLR` | `medium_low_risk` | 20% | 75% commitment / 20% issued | 20% (Row 6) | Issued trade / performance items: warranties, tender and performance bonds, advance payment and retention guarantees, **non-credit-substitute** standby LCs, self-liquidating (shipment-secured) documentary credits |
| `LR` | `low_risk` | 0% | 0% | 10% (Row 7) | Unconditionally cancellable commitments |

!!! warning "Book commitments as `OC`, not `MR` / `MLR`"
    The CRR habit of encoding an undrawn facility as `MR` (> 1 year) or `MLR`
    (≤ 1 year) prices wrongly under Basel 3.1: an `MLR` commitment takes Row 6's
    20% instead of Row 5's 40% (understated) and an `MR` commitment Row 4's 50%
    instead of 40%. `OC` gets both regimes right — the engine applies the CRR
    original-maturity split itself. A standby LC is `FR` when it is a credit
    substitute (100% in both regimes) and `MLR` when it is not (20%) — never `MR`.

A blank `risk_type` with no resolvable `obs_product` raises **DQ016** and takes the
regime's residual: CRR Annex I 1(k) 100%; Basel 3.1 Row 5 40% for a commitment or
Row 3 50% for an issued item.

**Engine-only risk types are not lending categories.** `CCR_DERIVATIVE`, `CCR_SFT`,
`CCR_DEFAULT_FUND` and `SETTLEMENT_FAILED_TRADE` tag the rows the counterparty-credit-risk stages
mint for SA-CCR netting sets, FCCM SFT netting sets, CCP default-fund contributions and failed
trades. On a facilities / contingents row (`risk_type` or `underlying_risk_type`) each raises one
**`DQ023` ERROR** per value. What happens to the row then depends on the tag:

- **`CCR_DERIVATIVE` / `CCR_SFT` are disregarded.** The hierarchy stage rewrites the value to
  `DQ023:<value>`, so no counterparty-credit-risk routing (the Basel 3.1 `standardised_ccr`
  approach label, the repo-style CRR F-IRB maturity and its sub-1-year floor waiver, the QCCP
  sovereign-floor exemption, the C 07.00 CCR rows) keys on it, while the CCF stays the residual an
  unrecognised risk type receives (CRR Annex I 1(k) 100%; PS1/26 Table A1 Row 3 50% / Row 5 40%) —
  the same CCF the tag received before. `obs_product` is not consulted: an explicit risk type
  outranks it. None of the removed treatments raised capital, so no number can fall.
- **`CCR_DEFAULT_FUND` / `SETTLEMENT_FAILED_TRADE` are honoured.** They select the 1250% own-funds
  conversion, the weight such a row carried before; disregarding them would cut its SA RWA (and
  the Basel 3.1 output floor's SA-equivalent) by up to 92%.

A derivative's or SFT's exposure value comes from the CCR methods or the FCCM, never from a CCF on
a nominal amount (CRR Art. 111(2); PS1/26 Art. 111(2) / (2A)): book them in the CCR / SFT inputs,
or flag a repo-style loan with `is_sft`.

**F-IRB short-term trade LCs (CRR Art. 166(8)(b)):** short-term letters of credit
arising from the movement of goods keep a 20% CCF under CRR F-IRB. Flag them with
`is_short_term_trade_lc = True` on an issued-item bucket (`MLR`, or `MR_ISSUED` for a
documentary credit not secured by its shipment). Basel 3.1 has no separate F-IRB
carve-out — F-IRB uses the SA Table A1 factor (Art. 166C).

| Column | Type | Required | Description |
|--------|------|----------|-------------|
| `is_short_term_trade_lc` | `Boolean` | No | True for short-term trade LCs for goods movement (CRR Art. 166(8)(b) — retains 20% CCF under F-IRB) |

### Concrete product keys (`obs_product`)

When `risk_type` is blank the engine resolves it from `obs_product` through the
regime's own map — the two regimes classify some products differently:

| `obs_product` | CRR | Basel 3.1 |
|---------------|-----|-----------|
| `ACCEPTANCE`, `FINANCIAL_GUARANTEE`, `AVAL`, `ENDORSEMENT`, `STANDBY_LC_CREDIT_SUBSTITUTE` | `FR` 100% | `FR` 100% |
| `FACTORING_FACILITY`, `INVOICE_DISCOUNT_FACILITY` | `FRC` 100% | `FRC` 100% |
| `DOCUMENTARY_CREDIT` | `MR_ISSUED` 50% (Annex I 2(a)) | `MLR` 20% (Row 6(a)) |
| `SHIPPING_GUARANTEE`, `CUSTOMS_BOND`, `TAX_BOND` | `MR_ISSUED` 50% (Annex I 2(b)(i)) | `MLR` 20% (Row 6(d)) |
| `DOCUMENTARY_CREDIT_SHIPMENT_SECURED`, `TRADE_LC` | `MLR` 20% (Annex I 3(a)(i)) | `MLR` 20% |
| `PERFORMANCE_BOND`, `WARRANTY`, `TENDER_BOND`, `BID_BOND`, `ADVANCE_PAYMENT_GUARANTEE`, `RETENTION_GUARANTEE`, `STANDBY_LC_NON_CREDIT_SUBSTITUTE` | `MLR` 20% | `MLR` 20% |

Keys are case-insensitive and these synonyms are accepted: `bankers_acceptance`,
`sblc_financial` / `standby_lc_financial`, `factoring`, `invoice_discounting`,
`doc_credit`, `self_liquidating_dc`, `perf_bond`, `sblc_performance` /
`standby_lc_performance`. An unknown key raises **DQ006**.

### UK residential mortgage commitments

PS1/26 Table A1 Row 4(b) gives 50% to "UK residential mortgage commitments that are
not subject to a conversion factor of 10% or 100%" (Row 5 "any other commitment" is
40%). `is_uk_residential_mortgage_commitment` is tri-state:

- `True` — Row 4(b) 50% (a 10% or 100% row is left alone);
- `False` — never Row 4(b);
- null (not stated) — **derived** under Basel 3.1: Row 4(b) when the row is a
  commitment (`is_obs_commitment`), classified `retail_mortgage`, secured on
  residential property (allocated residential collateral, or a linked property of
  `property_type = residential`), to a `GB` obligor in a `GBP` denomination.

The data model has no property location, so "UK" is evidenced by the obligor's
country and the denomination; nothing else is derived. Set the flag `True` for a UK
mortgage to a non-GB obligor and `False` for a GB obligor's mortgage on non-UK
property. A contingent is an issued item by default and is never derived.

**A-IRB Modelled CCF:** For A-IRB exposures, provide the bank's own modelled CCF estimate (0.0 to 1.5) in `ccf_modelled`. Retail IRB CCFs can exceed 100% due to additional drawdown behaviour. Where it is admissible it takes precedence over the risk_type lookup:

- **CRR:** within the Art. 166(8) product scope — commitments (`is_obs_commitment`) and short-term trade LCs, never `FR` / `FRC`; issued items take the Art. 166(10) factor.
- **Basel 3.1 (PS1/26 Art. 166D(1)):** only for **revolving loan commitments** — `is_revolving` **and** `is_obs_commitment`, with an SA factor below 100% — floored at 50% of the SA factor. Every other item, including an issued LC or guarantee booked under a revolving facility, takes the SA Table A1 factor. A flagged revolving purchased-receivables commitment takes the fixed Art. 166A(5) 40% / 10%.

**Example:**

```python
from datetime import date
import polars as pl

facilities = pl.DataFrame({
    "facility_reference": ["FAC_001", "FAC_002"],
    "product_type": ["rcf", "term_loan"],
    "book_code": ["CORP_LENDING", "CORP_LENDING"],
    "counterparty_reference": ["CORP_001", "CORP_002"],
    "value_date": [date(2024, 1, 15), date(2023, 6, 1)],
    "maturity_date": [date(2029, 1, 15), date(2028, 6, 1)],
    "currency": ["GBP", "GBP"],
    "limit": [10_000_000.0, 5_000_000.0],
    "committed": [True, True],
    "lgd": [None, None],  # Supervisory LGD used for F-IRB
    "beel": [None, None],
    "is_revolving": [True, False],
    "seniority": ["senior", "senior"],
    "risk_type": ["OC", "OC"],  # Other commitments - committed undrawn
    "ccf_modelled": [None, None],  # No modelled CCF (use regulatory)
})
```

---

## Loan Schema

**Purpose:** Defines drawn loan exposures (leaf nodes in exposure hierarchy). Loans represent actual credit usage under facilities.

**File:** `exposures/loans.parquet`

| Column | Type | Required | Description |
|--------|------|----------|-------------|
| `loan_reference` | `String` | Yes | Unique identifier for the loan — unique across **every exposure table**, not only this one (see [Exposure reference uniqueness](#exposure-reference-uniqueness)) |
| `product_type` | `String` | No | Product classification. A `MORTGAGE` / `HOME_LOAN` label makes a natural person's loan a retail mortgage only with evidence of security — a linked `real_estate` collateral row (with or without a `market_value`), or an LTV; without either a Standardised-Approach loan takes its counterparty's class and a `RE005` warning is raised (CRR Art. 125(1); PS1/26 Glossary, *real estate exposure*) |
| `book_code` | `String` | No | Portfolio/book classification |
| `counterparty_reference` | `String` | Yes | Link to counterparty |
| `value_date` | `Date` | No | Loan origination date |
| `maturity_date` | `Date` | No | Loan maturity date. On a **deposit** row (negative `drawn_amount` under a `netting_agreement_reference`) it is the earliest date the deposit can be withdrawn — notice, break or term date — which is the netted protection's maturity (CRR/PS1-26 Art. 238(1)). A deposit with **no** `maturity_date` is repayable on demand: residual maturity 0, so against a later-maturing loan the Art. 237(1) three-month gate removes the netting relief and a **CRM024** warning names the agreement. An on-demand loan (null `maturity_date`) still nets in full against an on-demand deposit |
| `currency` | `String` | No | ISO 4217 currency code |
| `drawn_amount` | `Float64` | No | Outstanding principal balance (default `0.0`). For a **finance lease** this must arrive already discounted — see [Lease exposures](#lease-exposures-the-drawn_amount-convention) below |
| `interest` | `Float64` | No | Accrued interest (adds to on-balance-sheet EAD) |
| `lgd` | `Float64` | No | Internal LGD estimate (A-IRB) |
| `lgd_unsecured` | `Float64` | No | A-IRB unsecured LGD estimate, applied to the residual EAD after eligible collateral (CRR Art. 181) |
| `beel` | `Float64` | No | Best estimate expected loss |
| `has_sufficient_collateral_data` | `Boolean` | No | A-IRB collateral data-quality attestation per Art. 181(1)(f). See Facility schema |
| `seniority` | `String` | No | `senior` (default) or `subordinated` (affects F-IRB LGD) |
| `ltv` | `Float64` | No | Loan-level LTV for a loan whose property data lives on the loan row. Used when no linked collateral supplies `property_ltv` (a linked collateral LTV wins), including when a collateral file exists that does not link to the loan |
| `is_qualifying_re` | `Boolean` | No | Loan-level twin of the collateral `is_qualifying_re`, for a loan whose property data lives on the loan row; a linked collateral value wins. Under CRR the Art. 126 50% on commercial property needs an explicit `True` (the Art. 126(2) conditions and the PRA Credit Risk Part rule 4.1 / 4.1A loss condition attested); null takes Art. 124(1) 100% |
| `is_payroll_loan` | `Boolean` | No | Payroll-deduction / pension lending — qualifies for the Basel 3.1 35% retail RW (PS1/26 Art. 123(2)) |
| `is_buy_to_let` | `Boolean` | No | Buy-to-let property lending — excluded from SME supporting factor (CRR Art. 501) |
| `has_one_day_maturity_floor` | `Boolean` | No | Eligible for the Art. 162(3) one-day `M` minimum in lieu of the standard one-year minimum (`M = max(residual, 1/365)` for a residual under one year) |
| `is_sft` | `Boolean` | No | Securities Financing Transaction — see Facility schema |
| `effective_maturity` | `Float64` | No | Explicit numeric `M` override (years) per CRR Art. 162(3) / PS1/26. Bypasses the 1-year floor when populated |
| `netting_agreement_reference` | `String` | No | CRR Art. 195/219 on-balance-sheet netting set. A non-null reference is the sole signal that the loan participates in a netting agreement, and the reference alone defines the **netting perimeter**: exposures net against each other **iff they share the same reference**, across facilities *and* across counterparties. The cross-counterparty limb is gated by the rulepack Feature `on_bs_netting_perimeter_is_agreement` (enabled under both regimes); disabled, the pool and the beneficiary match are additionally keyed on `counterparty_reference`. Sharing one reference across counterparties is the firm's Art. 205(a) attestation that set-off is enforceable against every party under it, and raises the **CRM016** audit warning naming the agreement and the number of counterparties it netted across. A row with a null `counterparty_reference` still nets under the agreement and adds a null clause to that warning, while the loader raises **DQ001** for the null reference separately. Enabling the perimeter reduces own-funds RWA without reducing the Basel 3.1 output-floor basis. See [Credit Risk Mitigation — On-Balance Sheet Netting](../user-guide/methodology/crm.md#on-balance-sheet-netting-crr-art-195-art-219) |
| `due_diligence_performed` | `Boolean` | No | Basel 3.1 Art. 110A: True if the firm has performed the prescribed due-diligence assessment of the obligor. Required for the SA RW override below to apply. Absence raises diagnostic warning **SA004** under B3.1 |
| `due_diligence_override_rw` | `Float64` | No | Basel 3.1 Art. 110A SA RW override (decimal, e.g. `1.50` for 150%). Applied as `max(calculated_rw, override_rw)` — the override can only **increase** the regulatory RW, never decrease it. CRR-only runs ignore this column |
| `intragroup_entity_reference` | `String` | No | Intragroup tag — see Facility schema and [Multi-Entity Reporting](../features/multi-entity-reporting.md) |
| `is_under_irb_rollout` | `Boolean` | No | CRR Art. 148 IRB roll-out-plan flag — see Facility schema. Reporting-only (COREP C 08.07 / OF 08.07 col 0040); default False |

**Note:** Loans do not have CCF fields (`risk_type`, `ccf_modelled`, `is_short_term_trade_lc`) because CCF only applies to off-balance sheet items. For drawn loans, EAD = `drawn_amount` + `interest` directly. A loan drawn under a facility (via `facility_mappings`) inherits that facility's `is_short_term_trade_lc`; a loan of the same counterparty under any other facility, or under none, does not — the trade conditions of PS1/26 Art. 121(4) ("arose from the movement of goods") and Art. 162(3) are properties of the transaction, not the counterparty.

#### Lease exposures — the `drawn_amount` convention

For a finance-lease receivable, the regulatory exposure value is the **discounted
minimum lease payments**. Minimum lease payments are the payments over the lease term
that the lessee is (or can be required to be) obliged to make, plus any bargain option
whose exercise is reasonably certain.

This is a **feed-side convention: `drawn_amount` must arrive already discounted.** The
engine has no lease product type, no minimum-lease-payment schedule input and no
discount-rate input, so it cannot perform the discounting and does not validate that it
was performed. Supplying an undiscounted gross lease investment overstates the exposure
value and therefore the RWA.

| Regime | Approach | Provision |
|--------|----------|-----------|
| CRR | IRB | Art. 166(4) — "The exposure value for leases shall be the discounted minimum lease payments" |
| CRR | SA | Art. 134(7) — same rule, same wording |
| PS1/26 | IRB | Art. 166A(4) — "An institution shall set the exposure value for leases as the discounted minimum lease payments" (Art. 166 itself is left blank) |
| PS1/26 | SA | Art. 134(7) — same rule, same wording |

The requirement is therefore **regime- and approach-invariant**: it binds SA and IRB
rows identically under both frameworks.

!!! tip "An IFRS 16 / IAS 17 finance-lease receivable already satisfies this"
    A lessor's net investment in a finance lease, measured at amortised cost, *is* the
    discounted minimum lease payments — so a standard accounting feed needs no
    adjustment. The exposure to check is a feed that reports the **gross** investment
    (undiscounted rentals) or that adds unearned finance income back onto the balance.

!!! warning "There is no lease flag, and that is deliberate"
    No schema field asserts "this row is a discounted lease". A Boolean that the engine
    never reads would look like a compliance attestation while guaranteeing nothing, and
    the consistency check that would justify one (discount rate vs undiscounted flows)
    cannot be written until those inputs exist. If you want lease rows tagged for your
    own reporting, use the free-text `product_type` (e.g. `finance_lease`) — the engine
    does not consult it for lease purposes. Avoid values containing `MORTGAGE` or
    `INFRASTRUCTURE`, or equal to `DEVELOPMENT_FINANCE` / `CONSTRUCTION_LOAN`: the
    classifier does read `product_type` for those unrelated signals.

Two adjacent lease mechanics are separate from this convention:

- **Residual value** of a leased asset is its own exposure, carried by
  `entity_type = "other_residual_lease"` on the counterparty and risk-weighted at
  1/t × 100% (CRR / PS1/26 Art. 134(7)). See [Counterparty Schema](#counterparty-schema).
- **The leased asset as collateral** (CRR Art. 199(7)/211) is supplied as an ordinary
  non-financial collateral row with `is_lease_collateral_attested = True`. See
  [Collateral Schema](#collateral-schema).

A third-party obligation to cover the residual value, recognisable as unfunded credit
protection where it meets Art. 201 and Art. 213, is **not implemented** — the last
sentence of each provision above is out of scope and tracked separately.

**Example:**

```python
from datetime import date
import polars as pl

loans = pl.DataFrame({
    "loan_reference": ["LOAN_001", "LOAN_002", "LOAN_003"],
    "product_type": ["rcf_drawing", "term_loan", "term_loan"],
    "book_code": ["CORP_LENDING", "CORP_LENDING", "CORP_LENDING"],
    "counterparty_reference": ["CORP_001", "CORP_001", "CORP_002"],
    "value_date": [date(2024, 3, 1), date(2024, 4, 15), date(2023, 6, 1)],
    "maturity_date": [date(2029, 1, 15), date(2029, 1, 15), date(2028, 6, 1)],
    "currency": ["GBP", "GBP", "GBP"],
    "drawn_amount": [2_000_000.0, 1_500_000.0, 5_000_000.0],
    "interest": [10_000.0, 7_500.0, 25_000.0],  # Accrued interest
    "lgd": [None, None, None],
    "beel": [None, None, None],
    "seniority": ["senior", "senior", "senior"],
    "is_buy_to_let": [False, False, False],
    "netting_agreement_reference": [None, None, None],
})
```

---

## Contingent Schema

**Purpose:** Defines off-balance sheet commitments that require Credit Conversion Factor (CCF) application.

**File:** `exposures/contingents.parquet`

| Column | Type | Required | Description |
|--------|------|----------|-------------|
| `contingent_reference` | `String` | Yes | Unique identifier |
| `product_type` | `String` | No | Product classification |
| `book_code` | `String` | No | Portfolio/book classification |
| `counterparty_reference` | `String` | Yes | Link to counterparty |
| `value_date` | `Date` | No | Contract start date |
| `maturity_date` | `Date` | No | Contract expiry date |
| `currency` | `String` | No | ISO 4217 currency code |
| `nominal_amount` | `Float64` | No | Notional/nominal amount (default `0.0`) |
| `lgd` | `Float64` | No | Internal LGD estimate (A-IRB) |
| `lgd_unsecured` | `Float64` | No | A-IRB unsecured LGD estimate, applied to the residual EAD after eligible collateral (CRR Art. 181) |
| `beel` | `Float64` | No | Best estimate expected loss |
| `has_sufficient_collateral_data` | `Boolean` | No | A-IRB collateral data-quality attestation per Art. 181(1)(f). See Facility schema |
| `seniority` | `String` | No | `senior` (default) or `subordinated` |
| `risk_type` | `String` | No | Off-balance sheet risk category (see Facility schema) |
| `underlying_risk_type` | `String` | No | Underlying-exposure risk type for CRM substitution (see Facility schema) |
| `obs_product` | `String` | No | Concrete off-balance-sheet product key (see [Concrete product keys](#concrete-product-keys-obs_product)) |
| `ccf_modelled` | `Float64` | No | A-IRB modelled CCF (0.0-1.5). Under Basel 3.1 an issued contingent is never eligible (Art. 166D(1)(b)) |
| `ead_modelled` | `Float64` | No | Basel 3.1 A-IRB own estimate of EAD — revolving loan commitments only (PS1/26 Art. 166D(3)/(4); see Facility schema). Ignored on an issued contingent (`is_obs_commitment = False`) and under CRR |
| `is_short_term_trade_lc` | `Boolean` | No | Short-term trade LC for goods movement (CRR Art. 166(8)(b)) |
| `is_obs_commitment` | `Boolean` | No | Default `False` — a contingent is an issued item. Set `True` for a commitment booked as a contingent (e.g. a NIF / RUF: CRR F-IRB Art. 166(8)(d) 75%; or a mortgage offer). A contingent on a commitment `risk_type` (`MR`, `OC`) left `False` raises **DQ017** |
| `is_uk_residential_mortgage_commitment` | `Boolean` | No | Basel 3.1 Table A1 Row 4(b) flag, tri-state — see Facility schema. Never derived for a row with `is_obs_commitment = False` |
| `is_purchased_receivable_commitment` | `Boolean` | No | PS1/26 Art. 166A(5) revolving purchased-receivables commitment (IRB rows only) — see Facility schema |
| `has_one_day_maturity_floor` | `Boolean` | No | Eligible for the Art. 162(3) one-day `M` minimum |
| `is_sft` | `Boolean` | No | Securities Financing Transaction — see Facility schema |
| `effective_maturity` | `Float64` | No | Explicit numeric `M` override (years) per CRR Art. 162(3) / PS1/26 |
| `bs_type` | `String` | No | `"ONB"` (on-balance-sheet / drawn) or `"OFB"` (off-balance-sheet / undrawn). Default: `"OFB"` |
| `due_diligence_performed` | `Boolean` | No | Basel 3.1 Art. 110A due-diligence attestation (see Loan schema) |
| `due_diligence_override_rw` | `Float64` | No | Basel 3.1 Art. 110A SA RW override (max-only — see Loan schema) |
| `intragroup_entity_reference` | `String` | No | Intragroup tag — see Facility schema and [Multi-Entity Reporting](../features/multi-entity-reporting.md) |
| `is_under_irb_rollout` | `Boolean` | No | CRR Art. 148 IRB roll-out-plan flag — see Facility schema. Reporting-only (COREP C 08.07 / OF 08.07 col 0040); default False |

**Example:**

```python
from datetime import date
import polars as pl

contingents = pl.DataFrame({
    "contingent_reference": ["CONT_001", "CONT_002", "CONT_003"],
    "product_type": ["trade_finance", "guarantee", "import_lc"],
    "book_code": ["TRADE", "GUARANTEE", "TRADE"],
    "counterparty_reference": ["CORP_001", "CORP_002", "CORP_003"],
    "value_date": [date(2024, 1, 1), date(2024, 2, 1), date(2024, 3, 1)],
    "maturity_date": [date(2025, 1, 1), date(2025, 2, 1), date(2024, 6, 1)],
    "currency": ["GBP", "GBP", "GBP"],
    "nominal_amount": [500_000.0, 1_000_000.0, 250_000.0],
    "lgd": [None, None, None],
    "beel": [None, None, None],
    "seniority": ["senior", "senior", "senior"],
    "risk_type": ["FR", "MR_ISSUED", "MLR"],  # FR=100%, MR_ISSUED=50%, MLR=20%
    "ccf_modelled": [None, None, None],  # No modelled CCF
    "is_short_term_trade_lc": [False, False, True],  # Third: CRR Art. 166(8)(b) 20%
    "bs_type": ["OFB", "OFB", "OFB"],  # Off-balance sheet (default)
})
```

---

## Collateral Schema

**Purpose:** Defines collateral/security items used for Credit Risk Mitigation (CRM). Collateral can be linked at counterparty, facility, or loan level.

**File:** `collateral/collateral.parquet`

| Column | Type | Required | Description |
|--------|------|----------|-------------|
| `collateral_reference` | `String` | Yes | Unique identifier |
| `collateral_type` | `String` | Yes | Type of collateral (see valid values) |
| `currency` | `String` | No | ISO 4217 currency code. Compared with the exposure's currency for the Art. 224 Table 4 currency-mismatch adjustment `H_fx`. A **null** currency cannot show a match, so the row is treated as currency-mismatched (H_fx applied wherever it applies to the type), its value is left unconverted, and a rolled-up **CRM023** warning names it (life-insurance policies are covered by CRM020 instead) |
| `maturity_date` | `Date` | No | Collateral maturity — the earliest date the protection may terminate (CRR/PS1-26 Art. 238(1)). Where `residual_maturity_years` is null, the residual maturity is derived from it (days to the reporting date / 365.25) and feeds both the Art. 224 Table 1 haircut band and the Art. 237-239 maturity mismatch |
| `market_value` | `Float64` | Conditional | Current market value (required unless `pledge_percentage` provided) |
| `nominal_value` | `Float64` | No | Nominal/face value |
| `pledge_percentage` | `Float64` | Conditional | Fraction of beneficiary EAD (0.5 = 50%). Used when `market_value` not provided. Resolved to absolute `market_value` before haircuts. |
| `beneficiary_type` | `String` | Yes | Level of allocation |
| `beneficiary_reference` | `String` | Yes | Reference to counterparty/facility/loan |
| `issuer_cqs` | `Int8` | No | CQS of issuer (for securities) |
| `issuer_type` | `String` | No | Issuer type (for haircut lookup) |
| `residual_maturity_years` | `Float64` | No | Residual maturity in years. Takes precedence over `maturity_date`; when null it is derived from `maturity_date`, and when both are null the haircut takes the longest maturity band and the maturity mismatch treats the protection as long-dated |
| `original_maturity_years` | `Float64` | No | Original maturity in years — used for collateral maturity-band differentiation where the haircut depends on issuance maturity rather than residual maturity |
| `is_eligible_financial_collateral` | `Boolean` | No | Meets SA eligibility (CRR Art 197). Honoured only on an Art. 197 type — cash / deposit, debt securities (`bond` with a recognised `issuer_type`, government / corporate bonds, securitisation positions), covered bonds, equity, gold, credit-linked notes. On immovable property, receivables, other physical collateral, life insurance or an unrecognised type the flag is ignored for the SA (the Comprehensive Method's exposure-value reduction and the Simple Method's risk-weight substitution) and a rolled-up **CRM026** warning is raised (those types are recognised under Art. 199 via `is_eligible_irb_collateral`, or Art. 232) |
| `is_eligible_irb_collateral` | `Boolean` | No | Meets IRB eligibility (CRR Art 199) |
| `is_lease_collateral_attested` | `Boolean` | No | CRR Art. 199(7)/211: the leased asset of a finance-lease exposure attested to meet the Art. 211 lease-specific conditions (robust lessor risk management, legal ownership, unamortised-vs-market-value gap). Supply the leased asset as a `real_estate` / `other_physical` collateral row pledged to the lease exposure with this flag `True`; it is an independent F-IRB Foundation Collateral Method eligibility route (subsumes the Art. 208/210 conditions `is_eligible_irb_collateral` carries). No default: null → not attested → not recognised (conservative). Consulted only for non-financial collateral |
| `is_airb_model_collateral` | `Boolean` | No | Default `False`. When `True`, the firm asserts the collateral has been used to construct the internal LGD model (CRR Art. 181 / Basel 3.1 Art. 169A). The CRM allocator excludes flagged rows from non-AIRB exposures (no double-counting of the modelled-LGD effect) and routes them only to AIRB-pool exposures whose modelled LGD is preserved. Direct allocation of a flagged row onto a non-AIRB exposure raises CRM006 |
| `is_qualifying_re` | `Boolean` | No | Meets Basel 3.1 qualifying real-estate criteria for the loan-splitter (PS1/26 Art. 124A finished-property / legal-enforceability / valuation / borrower-ability tests). Drives Art. 124F (RRE) / Art. 124H (CRE) eligibility. **Under CRR**, an explicit `False` attests that the Art. 125(2) / 126(2) conditions are not met — limbs (a)-(c), Art. 208 / Art. 229(1), and for UK commercial property the PRA Credit Risk Part rule 4.1 loss condition (in force to 31 Dec 2026): the property-secured part, up to the property's market value, takes Art. 124(1) 100% and any excess the counterparty's unsecured weight, on a whole mortgage row and on the loan-split secured row alike; the Art. 127(3) 100% defaulted-residential weight is withheld too. Null keeps the preferential treatment in both regimes, **except CRR commercial property**: the Art. 126 50% needs an explicit `True`, because PRA rule 4.1 / 4.1A admit it only where a loss condition measured on PRA-published market data is met, which no input carries — a null takes Art. 124(1) 100% |
| `is_main_index` | `Boolean` | No | Equity collateral listed on a recognised main index (e.g. FTSE 100) — qualifies for the lower main-index haircut (CRR Art. 197(8)) |
| `is_own_issued_cln` | `Boolean` | No | CRR/PS1-26 Art. 218: attests that a `credit_linked_note` collateral row is issued by the **lending institution itself** — the only case Art. 218 grants cash-collateral treatment (0% haircut, full EAD/LGD\* offset). No default: null → own-issuance unattested → the CLN is treated as ineligible funded protection (a third-party CLN is materially correlated with its reference entity, Art. 194(4)); its value is zeroed and a `CRM019` warning is raised. Consulted only for `credit_linked_note` collateral |
| `valuation_date` | `Date` | No | Date of last valuation |
| `valuation_type` | `String` | No | `market`, `indexed`, `independent` |
| `property_type` | `String` | No | `residential` or `commercial` (RE only) |
| `property_ltv` | `Float64` | No | Regulatory LTV per Art. 124C — must include prior/pari passu charges (Art. 124C(3)) in numerator. When null on a `real_estate` row with a `market_value`, the LTV is **derived** as (drawn + accrued interest + undrawn committed amount) / property value + `prior_charge_ltv` — over every exposure the pledge secures for a facility / counterparty-level row — and a `RE006` warning is raised. A null-LTV row still supplies its `property_type` / `is_qualifying_re` / `is_income_producing` / `prior_charge_ltv` (a row carrying an LTV is preferred at the same level). A linked property with neither a `market_value` nor an LTV stays real estate but takes no LTV-band weight (Basel 3.1 Art. 124J; CRR no 35% / 50% part). No linked property and no LTV anywhere (collateral or loan `ltv`) → no real-estate weight (`RE005`). The Basel 3.1 Art. 124H(3) whole-loan path (commercial property, obligor neither natural person nor SME) bands on this LTV — it is no longer replaced by exposure / property value, which dropped the prior charges (review CL-10) |
| `prior_charge_ltv` | `Float64` | No | LTV portion from prior/pari passu charges only (Art. 124C(3)); 0.0 = first charge. Used by Art. 124F(2)/124G(2) junior charge treatment, and by the Foundation Collateral Method (F-IRB LGD\*, the CRR C\* test, the Basel 3.1 A-IRB LGD input floors): the property is valued net of `P = prior_charge_ltv × market_value` (CRR Art. 229(1) `MV − P`; PS1/26 Art. 229(1)(b) `MV × (1 − HC − Hfx) − P`, floored at zero). Pari-passu claims in the figure are deducted in full (conservative) until the input is split (P1.449). Null deducts nothing |
| `is_income_producing` | `Boolean` | No | Material dependency on property cash flows per Art. 124E. `True` = materially dependent (residential: Art. 124G whole-loan; commercial: Art. 124I). `False`/null = not materially dependent (residential: Art. 124F loan-splitting; commercial: Art. 124H). **Under CRR** the same flag is the Art. 126(2)(b) test: commercial property takes the Art. 126 50% (on the part up to 50% of value) only where it is `False` — repayment does not materially depend on the property's cash flows; `True` takes Art. 124(1) 100%. (Before review RE-17 the CRR gate was inverted: `True` took 50%.) For residential RE, this requires upstream assessment of Art. 124E(1) exceptions (primary residence, three-property limit, social housing, cooperative). For commercial RE, the own-business-use test (Art. 124E(6)). See [Art. 124E spec](../specifications/basel31/sa-risk-weights.md#real-estate-material-dependency-classification-art-124e) |
| `is_adc` | `Boolean` | No | Acquisition/Development/Construction (PS1/26 Art. 124K). Any-True across every `real_estate` row linked to the exposure (loan, facility or counterparty level); applies only to a corporate / SPE borrower (Glossary, *ADC exposure*). Basel 3.1: 150% on the whole exposure; CRR: the exposure is not loan-split and keeps its corporate weight |
| `is_presold` | `Boolean` | No | Attests PS1/26 Art. 124K(2)(a) prudent underwriting and (b)(i) pre-sale / pre-lease contracts — a residential ADC exposure takes 100% (Basel 3.1 only). Any-True like `is_adc`, but holds only when every property linked to the exposure is residential: a mixed residential / commercial security takes 150%. Limb (b)(ii), substantial equity at risk, has no input |
| `rental_to_interest_ratio` | `Float64` | No | CRR Art. 126(2)(d): rental income / interest payments ratio. The ≥ 1.5 test gates the 50% preferential CRE risk weight; if absent, CRE collateral is conservatively treated as failing the test under CRR and the loan-splitter leaves the exposure in its original corporate / retail class. **Not used under Basel 3.1.** |
| `liquidation_period_days` | `Int32` | No | Liquidation period in business days — used to scale supervisory haircuts under the Comprehensive method when the firm's holding period differs from the supervisory minimum (CRR Art. 224) |
| `qualifies_for_zero_haircut` | `Boolean` | No | Repo-style transaction qualifying for the zero-haircut carve-out under CRR Art. 224(1) / Art. 227 (core market participants, eligible securities, daily margining) |
| `insurer_risk_weight` | `Float64` | No | Credit-protection insurer risk weight override — when funded credit protection is provided by an eligible insurer, this RW is substituted for the obligor RW on the protected portion (CRR Art. 235) |
| `credit_event_reduction` | `Float64` | No | Adjustment factor (decimal, default `0.0`) applied to the protection's covered amount when the contract restricts the set of credit events. Reduces recognised CRM accordingly (CRR Art. 213-216) |

**Valid `collateral_type` values:**

| Value | Description |
|-------|-------------|
| `cash` | Cash collateral (0% haircut) |
| `gold` | Gold collateral (CRR 15% / B31 20% haircut) |
| `bond` | Bond securities — haircut depends on `issuer_type`, `issuer_cqs`, and `residual_maturity_years`. Categorised by its issuer: with `issuer_type` `sovereign`, `pse`, `institution`, `corporate` or `securitisation` it is financial collateral on every path (SA E\*, F-IRB LGDS 0%); with no recognised issuer it is treated as other physical collateral (40% haircut; F-IRB only with `is_eligible_irb_collateral`) |
| `equity` | Equity securities |
| `real_estate` | Real estate — use `property_type` for residential/commercial classification |
| `receivables` | Trade receivables |
| `other_physical` | Other physical collateral |

**Valid `beneficiary_type` values:**

| Value | Description |
|-------|-------------|
| `counterparty` | Allocated at counterparty level (expands to all exposures) |
| `facility` | Allocated at facility level (expands to facility + child loans) |
| `loan` | Allocated directly to specific loan |
| `contingent` | Allocated directly to contingent |

**Counterparty-credit-risk rows take no loan-table collateral.** The synthetic rows the CCR engines add — SA-CCR derivative and FCCM SFT netting sets, failed trades and CCP default-fund contributions (`risk_type` `CCR_DERIVATIVE`, `CCR_SFT`, `SETTLEMENT_FAILED_TRADE`, `CCR_DEFAULT_FUND`) — are left out of every collateral pool, pro-rata share and direct link from this table (Comprehensive and Simple Method, life-insurance policies and third-party deposits alike): their exposure value already reflects collateral under the Counterparty Credit Risk Part (CRR Art. 223(5A); PS1/26 Art. 191A(4)). A counterparty-level pledge is shared over the counterparty's other exposures only; a pledge whose only beneficiaries are CCR rows mitigates nothing and raises a rolled-up **CRM025** warning. Supply derivative and SFT collateral in `ccr_collateral` / `sft_collateral`. Guarantees still apply to CCR rows.

**Example:**

```python
from datetime import date
import polars as pl

collateral = pl.DataFrame({
    "collateral_reference": ["COLL_001", "COLL_002"],
    "collateral_type": ["cash", "real_estate"],
    "currency": ["GBP", "GBP"],
    "maturity_date": [None, None],
    "market_value": [1_000_000.0, 500_000.0],
    "nominal_value": [1_000_000.0, None],
    "beneficiary_type": ["counterparty", "loan"],
    "beneficiary_reference": ["CORP_001", "LOAN_003"],
    "issuer_cqs": [None, None],
    "issuer_type": [None, None],
    "residual_maturity_years": [None, None],
    "is_eligible_financial_collateral": [True, False],
    "is_eligible_irb_collateral": [True, True],
    "valuation_date": [date(2024, 12, 31), date(2024, 11, 15)],
    "valuation_type": ["market", "independent"],
    "property_type": [None, "residential"],
    "property_ltv": [None, 0.65],  # Art. 124C: includes prior charges in numerator
    "prior_charge_ltv": [None, 0.0],  # Art. 124C(3): 0.0 = first charge
    "is_income_producing": [None, False],
    "is_adc": [None, False],
    "is_presold": [None, None],
})
```

---

## Guarantee Schema

**Purpose:** Defines guarantee protection for Credit Risk Mitigation using the substitution approach.

**File:** `guarantee/guarantee.parquet`

| Column | Type | Required | Description |
|--------|------|----------|-------------|
| `guarantee_reference` | `String` | Yes | Identifies one protection **contract**. Rows that share a reference are one contract with **one** cap (Art. 233(1): G is the amount the provider undertook to pay): the total recognised across them is capped at the contract's `amount_covered` and shared pro-rata to each row's covered demand, min(G, E). Sharing a reference across beneficiaries is how to state a pool / aggregate-cap guarantee over obligors in different counterparty or facility trees. Rows that state different `amount_covered` values (the largest is used), or repeat one beneficiary, raise **CRM028**; a repeat for the same beneficiary from the same guarantor is one undertaking, so only its largest row is used |
| `guarantee_type` | `String` | No | Free-text descriptor. Read for two families only — see [`guarantee_type` values](#guarantee-type-values) below |
| `guarantor` | `String` | Yes | Guarantor counterparty reference |
| `currency` | `String` | No | ISO 4217 currency code |
| `maturity_date` | `Date` | No | Guarantee expiry date |
| `amount_covered` | `Float64` | Conditional | Amount the provider undertook to pay (required unless `percentage_covered` provided). With `percentage_covered` also given, it is the cap on the percentage |
| `percentage_covered` | `Float64` | Conditional | Fraction of exposure covered (`1.0` = 100%), measured on the exposure value with off-balance-sheet items at 100% (Art. 235(1)(a)). Where `amount_covered` is also given, G = **min(percentage × exposure, amount)** — "x% of the exposure, up to the amount" (Art. 233(1)). An `amount_covered` of 0 or null means the percentage alone is used |
| `beneficiary_type` | `String` | Yes | Level of allocation |
| `beneficiary_reference` | `String` | Yes | Reference to counterparty/facility/loan |
| `protection_type` | `String` | No | `"guarantee"` (default) or `"credit_derivative"` — drives CRM treatment under CRR Art. 213 vs Art. 215 (credit-derivative-specific eligibility tests). A `guarantee_type` naming a credit derivative overrides it (**CRM030**) |
| `includes_restructuring` | `Boolean` | No | Default `False` (the loader fills an absent column or a null value with it). For a credit derivative: True when restructuring of the underlying obligation is a credit event. When False, Art. 233(2) applies (both regimes): the cover is reduced by 40% where the amount undertaken is not higher than the exposure value, and valued at no more than 60% of the exposure value where it is higher — whether the cover is stated as an amount or a percentage. Applied before the Art. 233(3) currency haircut |
| `is_unilaterally_cancellable` / `is_unilaterally_changeable` | `Boolean` | No | Art. 213(1)(c)(i): True drops the protection with **CRM012** — cancellable in both regimes, changeable under Basel 3.1 only. Null is permissive |
| `attachment_amount` / `detachment_amount` | `Float64` | No | Art. 234 **tranched** protection: an `attachment_amount` above zero, or any `detachment_amount`, says the protection covers a band of the loss rather than a pro-rata share. Art. 234 sends a tranched transfer of risk to the securitisation framework and Art. 235(2) allows the substitution only where the protected and unprotected parts are of equal seniority, so such a row is **not recognised** (**CRM027**) and the exposure keeps the obligor's own risk weight. Leave both null for a guarantee of a share of the exposure, or of all of it |
| `guarantor_entity_reference` | `String` | No | Non-null tags the guarantor as the named group reporting entity (an `entity_reference` in the [Reporting Entity registry](#multi-entity-reporting-schemas)). Internal protection is not CRM at the consolidated / sub-consolidated level, so such rows are dropped there; kept on an individual run. Null (default) = external guarantor — see [Multi-Entity Reporting](../features/multi-entity-reporting.md) |

<a id="guarantee-type-values"></a>
**`guarantee_type` values the engine reads** (matched case-insensitively, with spaces and hyphens folded to `_`; any other value — `guarantee`, `bank_guarantee`, `standby_letter_of_credit`, `counter_guarantee`, … — is a descriptor only):

| Value | Treatment |
|-------|-----------|
| `credit_derivative`, `credit_default_swap`, `cds`, `total_return_swap`, `trs` | The row is a credit derivative whatever `protection_type` says, so Art. 233(2) applies when `includes_restructuring` is False. A disagreeing `protection_type` raises **CRM030** |
| `letter_of_comfort`, `comfort_letter`, `keepwell`, `keepwell_agreement` | **Not** eligible unfunded credit protection — not "an explicitly documented obligation assumed by the guarantor" (Art. 215(1)(b); Art. 213(1)(b)-(d)). The row is not recognised and **CRM029** names it |

A counter-guarantee (`counter_guarantee`) is entered with the counter-guarantor named as `guarantor` directly on the exposure.

**Example:**

```python
from datetime import date
import polars as pl

guarantees = pl.DataFrame({
    "guarantee_reference": ["GUAR_001"],
    "guarantee_type": ["guarantee"],
    "guarantor": ["SOV_001"],  # UK Treasury guaranteeing
    "currency": ["GBP"],
    "maturity_date": [date(2030, 12, 31)],
    "amount_covered": [2_000_000.0],
    "percentage_covered": [1.0],
    "beneficiary_type": ["counterparty"],
    "beneficiary_reference": ["CORP_001"],
})
```

---

## Provision Schema

**Purpose:** Defines IFRS 9 provisions/impairments for EAD reduction and IRB expected loss comparison.

**File:** `provision/provision.parquet`

| Column | Type | Required | Description |
|--------|------|----------|-------------|
| `provision_reference` | `String` | Yes | Unique identifier |
| `provision_type` | `String` | Yes | `scra` (specific) or `gcra` (general) |
| `ifrs9_stage` | `Int8` | No | IFRS 9 stage (1, 2, or 3) |
| `currency` | `String` | Yes | ISO 4217 currency code |
| `amount` | `Float64` | Yes | Provision amount |
| `as_of_date` | `Date` | Yes | Provision as-of date |
| `beneficiary_type` | `String` | Yes | Level of allocation |
| `beneficiary_reference` | `String` | Yes | Reference to counterparty/facility/loan |

**Valid `provision_type` values:**

| Value | Description | Usage |
|-------|-------------|-------|
| `scra` | Specific Credit Risk Adjustment | Reduces exposure value; affects defaulted RW |
| `gcra` | General Credit Risk Adjustment | Reduces exposure value |

**Valid `beneficiary_type` values:**

| Value | Description | Resolution |
|-------|-------------|------------|
| `loan` | Allocated directly to a specific loan | Matched by `beneficiary_reference` = `loan_reference` |
| `contingent` | Allocated directly to a contingent | Matched by `beneficiary_reference` = `contingent_reference` |
| `facility` | Allocated at facility level | Distributed pro-rata across facility's exposures by `ead_gross` |
| `counterparty` | Allocated at counterparty level | Distributed pro-rata across all counterparty exposures by `ead_gross` |

**Valid `ifrs9_stage` values:**

| Stage | Description | ECL Type |
|-------|-------------|----------|
| `1` | Performing | 12-month ECL |
| `2` | Performing, significant increase in credit risk | Lifetime ECL |
| `3` | Non-performing/credit-impaired | Lifetime ECL |

**Example:**

```python
from datetime import date
import polars as pl

provisions = pl.DataFrame({
    "provision_reference": ["PROV_001", "PROV_002"],
    "provision_type": ["scra", "gcra"],
    "ifrs9_stage": [1, 2],
    "currency": ["GBP", "GBP"],
    "amount": [50_000.0, 100_000.0],
    "as_of_date": [date(2024, 12, 31), date(2024, 12, 31)],
    "beneficiary_type": ["loan", "counterparty"],
    "beneficiary_reference": ["LOAN_001", "CORP_002"],
})
```

---

## Rating Schema

**Purpose:** Defines internal and external credit ratings for risk weight determination.

**File:** `ratings/ratings.parquet`

| Column | Type | Required | Description |
|--------|------|----------|-------------|
| `rating_reference` | `String` | Yes | Unique identifier |
| `counterparty_reference` | `String` | Yes | Link to counterparty |
| `rating_type` | `String` | Yes | `internal` or `external` |
| `rating_agency` | `String` | Yes | Rating source |
| `rating_value` | `String` | Yes | Rating value (e.g., `AAA`, `Aa1`) |
| `cqs` | `Int8` | Yes | Credit Quality Step (1-6) |
| `pd` | `Float64` | No | Probability of Default (internal ratings) |
| `rating_date` | `Date` | Yes | Rating as-of date |
| `is_solicited` | `Boolean` | No | Whether rating was solicited |
| `model_id` | `String` | No | IRB model identifier — links to [Model Permissions](#model-permissions-schema) for per-model approach gating. Flows through rating inheritance pipeline to exposures. Null defaults to SA. |
| `is_short_term` | `Boolean` | No | `True` flags this row as a dedicated **short-term ECAI assessment** (PRA PS1/26 Art. 120(2B) Table 4A / Art. 122(3) Table 6A). Defaults to `False` (long-term, counterparty-wide). |
| `scope_type` | `String` | No | Which exposure the short-term rating attaches to: `facility`, `loan`, or `contingent`. Must be populated when `is_short_term=True`; must be null otherwise. |
| `scope_id` | `String` | No | Matching `facility_reference` / `loan_reference` / `contingent_reference`. Must be populated when `is_short_term=True`; must be null otherwise. |

**Short-term ECAI assessments (Art. 120(2B) / Art. 122(3)):**
Short-term assessments are issue-specific — they attach to a particular exposure
rather than to the counterparty as a whole. Populate `is_short_term=True` together
with `scope_type` and `scope_id` to override the counterparty-level long-term
rating for the targeted exposure. When the scope is `facility`, the override
propagates to all loans and undrawn portions drawn under that facility. The
SA engine routes the overridden exposure via Table 4A (institution) or
Table 6A (corporate). The producer is responsible for ensuring the underlying
exposure satisfies the regulatory maturity test before flagging the rating
short-term — the engine does not re-check maturity.

**Valid `rating_agency` values:**

| Value | Description |
|-------|-------------|
| `internal` | Internal rating system |
| `SP` | Standard & Poor's |
| `MOODYS` | Moody's |
| `FITCH` | Fitch Ratings |
| `DBRS` | DBRS Morningstar |

**CQS Mapping:**

| CQS | S&P/Fitch | Moody's | Sovereign RW | Institution RW | Corporate RW |
|-----|-----------|---------|--------------|----------------|--------------|
| 1 | AAA to AA- | Aaa to Aa3 | 0% | 20% | 20% |
| 2 | A+ to A- | A1 to A3 | 20% | 30%* | 50% |
| 3 | BBB+ to BBB- | Baa1 to Baa3 | 50% | 50% | 100% |
| 4 | BB+ to BB- | Ba1 to Ba3 | 100% | 100% | 100% |
| 5 | B+ to B- | B1 to B3 | 100% | 100% | 150% |
| 6 | CCC+ and below | Caa1 and below | 150% | 150% | 150% |

*CRR Art. 120 Table 3 assigns CQS 2 institutions 50%. Basel 3.1 ECRA (PRA PS1/26 Art. 120 Table 3) reduces this to 30%.

**Example:**

```python
from datetime import date
import polars as pl

ratings = pl.DataFrame({
    "rating_reference": ["RAT_001", "RAT_002"],
    "counterparty_reference": ["CORP_001", "SOV_001"],
    "rating_type": ["external", "external"],
    "rating_agency": ["SP", "SP"],
    "rating_value": ["BBB+", "AA"],
    "cqs": [3, 1],
    "pd": [None, None],
    "rating_date": [date(2024, 6, 15), date(2024, 1, 1)],
    "is_solicited": [True, True],
})
```

---

## FX Rates Schema

**Purpose:** Defines FX (foreign exchange) rates for converting exposure amounts from their original currencies to a reporting currency. This enables consistent RWA calculations across multi-currency portfolios.

**File:** `fx_rates/fx_rates.parquet`

| Column | Type | Required | Description |
|--------|------|----------|-------------|
| `currency_from` | `String` | Yes | Source currency code (ISO 4217) |
| `currency_to` | `String` | Yes | Target currency code (ISO 4217) |
| `rate` | `Float64` | Yes | Conversion multiplier: `target_amount = source_amount * rate` |

**Usage:**
- Rates should be provided for all currency pairs needed (source → target)
- Include identity rates (e.g., GBP→GBP = 1.0) for the target currency
- The target currency should match `CalculationConfig.base_currency`

**Converted Fields:**
- Exposures: `drawn_amount`, `undrawn_amount`, `nominal_amount`
- Collateral: `market_value`, `nominal_value`
- Guarantees: `amount_covered`
- Provisions: `amount`

**Audit Trail:**
After conversion, the following columns are added:
- `original_currency` - Currency before conversion
- `original_amount` - Amount before conversion (drawn + nominal)
- `fx_rate_applied` - Rate used (null if no conversion needed)

**Example:**

```python
from datetime import date
import polars as pl

fx_rates = pl.DataFrame({
    "currency_from": ["GBP", "USD", "EUR", "JPY", "CHF"],
    "currency_to": ["GBP", "GBP", "GBP", "GBP", "GBP"],
    "rate": [1.0, 0.79, 0.88, 0.0053, 0.89],
})
```

**Behaviour:**
- **Missing rates:** Exposures in currencies without rates retain original values; `fx_rate_applied` is null
- **Facility headroom:** a loan / contingent drawn in a currency other than its facility's is converted into the facility's currency at these rates before the undrawn headroom is netted; one with no rate is not netted and raises **HIE005** (see [FX Conversion](../user-guide/methodology/fx-conversion.md#facility-headroom-netting))
- **FX disabled:** Set `apply_fx_conversion=False` in `CalculationConfig` to skip conversion
- **No FX file:** If `fx_rates.parquet` is not provided, no conversion occurs

---

## Specialised Lending Schema

**Purpose:** Defines specialised lending metadata for slotting approach treatment (CRE33). Keyed by `counterparty_reference` — all exposures to an SL counterparty inherit the same slotting treatment. This allows a corporate counterparty to have both SL and non-SL exposures.

**File:** `ratings/specialised_lending.parquet`

| Column | Type | Required | Description |
|--------|------|----------|-------------|
| `counterparty_reference` | `String` | Yes | Links to counterparty (all exposures inherit SL treatment) |
| `sl_type` | `String` | Yes | Type of specialised lending |
| `project_phase` | `String` | No | Project-finance phase, one of `pre_operational`, `operational`, `high_quality_operational` (case-insensitive; anything else raises **DQ006**). Basel 3.1 only: drives the unrated SA project-finance weight — 130% pre-operational, 100% operational, 80% high-quality operational (PS1/26 Art. 122B(2)(c) / (4)) — on SA rows and on the output-floor SA-equivalent of slotted rows. Supply `high_quality_operational` only where the Art. 122B(5) criteria are met. Art. 122B(3) defines the operational phase by conditions the firm must show, so a **null or unrecognised phase on a project-finance row is treated as `pre_operational`** and raises the **SA006** warning; the resolved phase is carried on the output as `sl_project_phase` and reported in OF 07.00 rows 0024–0026. Under CRR the value is carried unchanged and affects no weight (an unrated SL exposure is a corporate); slotting weights do not depend on it in either regime |
| `slotting_category` | `String` | No | Slotting category (case-insensitive). A row routed to slotting with a null or unrecognised category is weighted at the `satisfactory` pack default and raises the **CLS012** warning (both regimes) |
| `is_hvcre` | `Boolean` | No | High-volatility commercial real estate |

**Valid `sl_type` values:**

| Value | Description |
|-------|-------------|
| `project_finance` | Project finance (PF) |
| `object_finance` | Object finance (OF) |
| `commodities_finance` | Commodities finance (CF) |
| `ipre` | Income-producing real estate |
| `hvcre` | High-volatility commercial real estate |

!!! note "Basel 3.1: IPRE / HVCRE slotting needs an IRB permission"
    PS1/26 Art. 147A(1)(c) puts IPRE and HVCRE on the slotting approach — but only
    for a firm whose IRB permission covers the exposure (Art. 107(1)), and never
    over an Art. 148 / 150 standardised permission. The engine slots an `ipre` /
    `hvcre` row only when the run grants a slotting, F-IRB or A-IRB permission for
    `specialised_lending` that applies to it: an org-wide `irb_permissions` map
    covering the class, or (in `PermissionMode.IRB`) a `model_permissions` row
    matched through the exposure's `model_id` with no matching `standardised`
    row. Otherwise the row stays on the Standardised Approach — an SA-only firm,
    the default `PermissionMode.STANDARDISED` factory included. On SA an HVCRE row
    is ADC (Art. 124K, 150%) only when `is_under_construction` (or the product
    type) says so; with no property collateral, IPRE / HVCRE take 100%.

**Valid `slotting_category` values:**

| Category | CRR RW | Description |
|----------|--------|-------------|
| `strong` | 70% | Excellent risk profile |
| `good` | 90% (70% if <2.5yr) | Good risk profile |
| `satisfactory` | 115% | Acceptable risk profile |
| `weak` | 250% | Higher risk profile |
| `default` | 0% | In default (provisions apply) |

---

## SFT Input Schemas (FCCM)

**Purpose:** Dedicated input contract for **securities financing transactions
(SFTs)** — repos, reverse repos, securities-borrowing/lending and
margin-lending — whose exposure-at-default is computed by the **Financial
Collateral Comprehensive Method (FCCM)** under CRR Art. 220–223. SFTs are a
**peer** of the SA-CCR derivative book, not a sub-mode of it: they have their
own input bundle, their own dataloads and their own pipeline stage.

!!! warning "Two unrelated meanings of \"SFT\""
    The `transaction_type == "sft"` / FCCM path documented here (CCR EAD,
    CRR Art. 220–223) is a **completely different concept** from the
    [`is_sft` Boolean](#facility-schema) carried on the loan / contingent /
    facility schemas (which selects the F-IRB **0.5-year** repo-style
    supervisory maturity under CRR **Art. 162(1)**). **Same acronym, different
    concept.** (FCCM SFT rows that route to IRB carry their Art. 162 maturity
    via a dedicated `ccr_effective_maturity` carrier — never `is_sft`.)
    See [The two meanings of "SFT"](#the-two-meanings-of-sft) below.

### How SFTs flow through the pipeline

SFT inputs are loaded into a dedicated bundle and processed by a dedicated
stage that runs as a **peer** of the SA-CCR derivative stage:

```
sft_trades.parquet (+ optional sft_collateral.parquet)
   → RawSFTBundle  (RawDataBundle.sft)
   → sft_fccm stage  (engine/stages/sft.py)
   → E* = max(0, E·(1+HE) − CVA·(1−HC−HFX))   (CRR Art. 223(5))
   → one synthetic exposure row per netting set
        (risk_type = "CCR_SFT", ccr_method = "fccm_sft", drawn_amount = E*)
   → Classifier → CRM → SA / IRB exposure ladder
```

The `sft_fccm` stage sits immediately after `ccr_sa_ccr` in the literal
pipeline registry, so the two regulatory EAD methods are **adjacent and
visible**:

| Stage | Input bundle | Regulatory EAD basis | Output `risk_type` |
|-------|--------------|----------------------|--------------------|
| `ccr_sa_ccr` | `RawDataBundle.ccr` | SA-CCR `EAD = α·(RC + PFE)` (CRR Art. 274) | `CCR_DERIVATIVE` |
| `sft_fccm` | `RawDataBundle.sft` | FCCM `E*` (CRR Art. 220–223 via Art. 271(2)) | `CCR_SFT` |

The stage **no-ops** when `RawDataBundle.sft is None` (a firm with no SFT
book is unaffected), and it re-seals its output to the existing `ccr_exit`
edge brand so SFT and derivative rows share the same downstream contract.

> **Details:** see the
> [SFT (FCCM EAD) specification](../specifications/crr/sft/index.md) for the
> E\* formula, haircut treatment, and the architectural separation from
> SA-CCR.

### SFT Trade Schema

**File:** `ccr/sft_trades.parquet` (the single primary SFT dataload; optional)

One row per SFT. The netting-set counterparty is **denormalised onto the
trade row**, so no separate SFT netting-set table is needed. Trades sharing a
`netting_set_id` are netted into one `E*` only when **every** trade carries
both `under_master_netting_agreement` and `is_legally_enforceable` (an
*eligible* master netting agreement, Art. 220(1) / 206) and they name one
counterparty (Art. 220(4)); otherwise each trade is its own exposure and the
engine raises `CCR028` (no eligible MNA) or `CCR029` (several counterparties) —
see the [SFT specification](../specifications/crr/sft/index.md#netting-sets-one-e-only-under-an-eligible-bilateral-master-netting-agreement).
The three `exposure_*` columns carry the Art. 223(5) exposure-side
volatility-haircut (`HE`) inputs.

| Column | Type | Required | Description |
|--------|------|----------|-------------|
| `trade_id` | `String` | Yes | Unique identifier for the SFT |
| `netting_set_id` | `String` | Yes | Netting-set reference — used for the `ccr__<netting_set_id>` output reference and the collateral join |
| `counterparty_reference` | `String` | Yes | Counterparty (denormalised from the netting set) — drives the SA institution risk-weight lookup (CRR Art. 120(1) Table 3) |
| `notional` | `Float64` | Yes | `E` — the exposure amount lent / sold under the SFT (Art. 223(5)), in `currency`; rebased to the reporting currency by the SFT stage (no `fx_rates` row: unconverted, `CCR026`) |
| `currency` | `String` | Yes | ISO 4217 currency code of the exposure (kept as the denomination for the `HFX` test) |
| `maturity_date` | `Date` | Yes | SFT maturity date |
| `start_date` | `Date` | Yes | SFT start date |
| `exposure_collateral_type` | `String` | No | `HE` input — the security lent / sold, for the Art. 224 Table 1 / 3 haircut lookup of the run's regime. Null when the exposure side is cash (`HE = 0`). A type that is not eligible collateral — an unrated or low-CQS bond, real estate, an unknown string — takes the Art. 224(4) non-main-index listed-equity haircut (as a floor), never `HE = 0` |
| `exposure_security_cqs` | `Int8` | No | `HE` input — exposure-side issuer CQS |
| `exposure_security_residual_maturity_years` | `Float64` | No | `HE` input — exposure-side residual maturity (years) |
| `is_margined` | `Boolean` | No (default `False`) | Branch selector (Art. 224(2) final subparagraph). `False` → unmargined branch (today's behaviour); `True` → the margined Art. 285 MPOR branch |
| `remargining_frequency_days` | `Int16` | No (default `1`) | Dual role: `N_R` for the Art. 226 non-daily revaluation factor on the **unmargined** branch (1 = daily revaluation, factor = 1.0) / `N` in `MPOR = F + N − 1` on the **margined** branch |
| `mpor_floor_category` | `String` | No (default `repo_only`) | MPOR floor `F` selector (margined branch only): `repo_only` → 5 (Art. 285(2)(a)) / `other` → 10 (Art. 285(2)(b)) / `illiquid_or_large` → 20 (Art. 285(3)). Constrained to `VALID_MPOR_FLOOR_CATEGORIES` |
| `has_margin_dispute_doubling` | `Boolean` | No (default `False`) | `True` doubles `F` for the two quarters following more than two margin disputes (Art. 285(4)) |
| `mpor_days_override` | `Int16` | No (default `null`) | Explicit MPOR in business days; supersedes the `F + N − 1` derivation when set |
| `under_master_netting_agreement` | `Boolean` | No (default `False`) | The SFT is under a master netting agreement — the Art. 162(2) precondition for the sub-1-year IRB maturity floors and, with `is_legally_enforceable`, for netting the set (Art. 220(1)) |
| `is_legally_enforceable` | `Boolean` | No (default `False`) | The master netting agreement meets the Art. 206(1)(a)–(d) conditions (legally effective and enforceable in all relevant jurisdictions incl. insolvency; close-out right; netting of gains and losses; prompt liquidation / set-off of collateral). A multi-trade netting set nets only when every trade carries this **and** `under_master_netting_agreement`; a single-trade set is unaffected |
| `book_code` | `String` | No | Booking-unit code (default `""`) — mirrors the Facility/Loan/Contingent column; joined to the [Book-Entity Mapping](#multi-entity-reporting-schemas) by the scope resolver |
| `intragroup_entity_reference` | `String` | No | Intragroup tag — see Facility schema and [Multi-Entity Reporting](../features/multi-entity-reporting.md) |

!!! note "The five margining columns are inert on the unmargined-daily path"
    All five margining columns default so that `is_margined = False` with
    `remargining_frequency_days = 1` reproduces today's `E*` **exactly** (the
    Art. 226 non-daily factor collapses to 1.0 at daily revaluation). They take
    effect only when `is_margined = True` (the Art. 285 MPOR branch) or
    `remargining_frequency_days > 1` (non-daily revaluation). See the
    [SFT specification — two mutually-exclusive branches](../specifications/crr/sft/index.md#two-mutually-exclusive-branches-margined-vs-unmargined).

!!! note "These three columns were previously schema-orphaned"
    `exposure_collateral_type`, `exposure_security_cqs` and
    `exposure_security_residual_maturity_years` are **first-class** on
    `SFT_TRADE_SCHEMA`. They are *not* the identically-named columns on
    `LOAN_SCHEMA` / `CONTINGENTS_SCHEMA` (which serve an unrelated lending
    purpose) — grepping the name across schemas can mislead.

### SFT Collateral Schema

**File:** `ccr/sft_collateral.parquet` (optional — appears only when securities
are posted)

Collateral received against an SFT, keyed by `netting_set_id` (a genuinely
different grain — 0..n securities per netting set — so it stays a separate
optional file). Feeds the `CVA·(1 − HC − HFX)` collateral term of the FCCM
`E*` formula. An **uncollateralised** SFT carries no collateral row, so for
the common case this is literally one file.

| Column | Type | Required | Description |
|--------|------|----------|-------------|
| `sft_collateral_reference` | `String` | Yes | Unique identifier for the collateral row |
| `netting_set_id` | `String` | Yes | Join key back to the SFT trade's `netting_set_id` |
| `collateral_type` | `String` | Yes | Collateral security type — `HC` input for the Art. 224 Table 1 lookup |
| `market_value` | `Float64` | No (default `0.0`) | `CVA` — collateral market value in the `E*` formula, in `currency`; rebased to the reporting currency by the SFT stage; `0.0` when unknown (no collateral credit) |
| `currency` | `String` | No | Collateral currency. Drives the `HFX` same-currency shortcut (Art. 224 Table 4: `HFX = 0` when collateral and exposure currencies match) |
| `issuer_cqs` | `Int8` | No | `HC` input — collateral issuer CQS |
| `residual_maturity_years` | `Float64` | No | `HC` input — collateral residual maturity (years) |
| `trade_id` | `String` | No | The SFT trade the collateral was received against. Read only when the netting set is **split** per trade (no eligible master netting agreement, or several counterparties): a linked row moves with its trade, an unlinked one is not recognised (`CCR028` / `CCR029` name it). Ignored on a netted or single-trade set |

Only financial collateral the Art. 224 Tables 1 / 3 price is recognised on the
SFT path — cash / deposit, gold, government bonds (CQS 1–4), corporate and
covered bonds (CQS 1–3) and equities (`data/schemas.py::SFT_FCCM_HAIRCUT_LOOKUP_TYPES`).
Any other `collateral_type` (real estate, receivables, other physical, a bare
`bond`, fund units, an unknown string) or a bond failing the Art. 197 CQS test
contributes nothing to `E*` and raises one `CCR027` warning per row
(Art. 223(1): volatility adjustments value *financial* collateral).

### SA-CCR collateral and margin agreements

Read since review cluster saccr_b (CC-02 / CC-03); before it, SA-CCR netted no
collateral at all and ignored the margin agreement's terms. Full method:
[Replacement cost — collateral, the Art. 274(3) cap and shared CSAs](../specifications/crr/ccr/rc-calculation.md#collateral-the-art-2743-cap-and-shared-csas).

**`ccr.ccr_collateral`** (`CCR_COLLATERAL_SCHEMA`, one row per item, keyed by
`netting_set_id` — a foreign key to `ccr.netting_sets`, `DQ005` when it names
none):

| Column | Type | Required | Description |
|--------|------|----------|-------------|
| `market_value` | `Float64` | No (default `0.0`) | Unsigned value before the Art. 223 volatility adjustment, in `currency` (rebased to the reporting currency) |
| `is_posted_by_firm` | `Boolean` | No (default `False`) | Direction: received collateral is recognised positive, posted negative (CCR (CRR) Part Art. 276(1)(c)) |
| `is_segregated` | `Boolean` | No (default `False`) | Posted and bankruptcy remote: not recognised in NICA (Art. 276(1)(g)) |
| `collateral_role` | `String` | No (default `"vm"`) | `"vm"` (variation margin) or `"im"` (independent collateral → NICA) on a margined netting set (Art. 275(2), 276(1)(e)); every item is NICA on an unmargined one. Constrained to `VALID_CCR_COLLATERAL_ROLES` |
| `is_main_index` | `Boolean` | No (default `False`) | An equity is recognised only when included in a main index (Art. 197(1)(f); the Art. 198 extension does not apply to SA-CCR) |
| `collateral_type`, `issuer_cqs`, `issuer_type`, `residual_maturity_years`, `currency` | — | — | The Art. 224 haircut lookup and the Art. 197 gates, as for lending collateral; an item that is not Art. 197 eligible is left out and reported `CCR024`. `currency` also decides `Hfx` (waived only for an item in the single currency of every trade of its netting set) |
| `haircut_override` | `Float64` | No | **Not read** — Art. 276(1)(d) excludes own-estimate haircuts |

**`ccr.margin_agreements`** (`MARGIN_AGREEMENT_SCHEMA`): `margin_threshold`,
`minimum_transfer_amount`, `nica` and `mpor_days` are nullable with **no
default** (null = not stated on the CSA) and are coalesced with the same-named
`ccr.netting_sets` columns of every netting set naming the agreement. A term
both state with different values is reported `CCR025` and the conservative value
applies (larger TH / MTA / MPOR, smaller signed NICA). An unstated TH or MTA is
0; an unstated MPOR takes the Art. 285(2)(b) 10-business-day floor. TH, MTA and
NICA are reporting-currency amounts; NICA is signed (received +, posted −) and
is **added** to the NICA itemised in `ccr.ccr_collateral` — do not enter an
itemised amount twice. Margined netting sets naming the same agreement take one
Art. 275(3) replacement cost for it.

**`ccr.netting_sets.number_of_trades`**: the Art. 285(3)(a) large-netting-set
test now uses `max(number_of_trades, trades in the input)`.

**`ccr.trades`**: `notional`, `market_price` and `mtm_value` are in the trade
`currency` and rebased to the reporting currency (Art. 279b(3)); a currency with
no `fx_rates` row is left unconverted and reported `CCR026`.

### `transaction_type` discriminator

The CCR/SFT split key is `transaction_type` on the SA-CCR `TRADE_SCHEMA`,
constrained to `VALID_TRANSACTION_TYPES = {"derivative", "sft"}` via
`COLUMN_VALUE_CONSTRAINTS`. A bad value (e.g. `"SFT"`, `"repo"`) would
otherwise silently mis-route an SFT into the SA-CCR Art. 274 chain (≈£0 EAD);
the value constraint surfaces it as a `DQ006` data-quality error instead. SFT
rows belong in `SFT_TRADE_SCHEMA` / `RawDataBundle.sft`, not on the SA-CCR
trade frame.

### Configuration

`SFTConfig.method` (on `CalculationConfig.sft`) selects the SFT EAD method per
CRR Art. 271(2):

| `method` | Meaning | Status |
|----------|---------|--------|
| `"fccm"` (default) | Financial Collateral Comprehensive Method (Art. 220–223) | Implemented |
| `"var"` | VaR method (Art. 221) | Reserved — engine fails loud (`NotImplementedError`) |
| `"imm"` | Internal Model Method (Art. 283) | Reserved — engine fails loud |

The method is exposed as the `sft_method` factory argument on
`CalculationConfig.crr()` / `.basel_3_1()`.

### The two meanings of "SFT"

The acronym "SFT" denotes **two unrelated concepts** that never interact:

| | FCCM SFT (this section) | Lending `is_sft` |
|---|---|---|
| Carrier | `transaction_type == "sft"` on `SFT_TRADE_SCHEMA` | `is_sft` Boolean on `LOAN` / `CONTINGENT` / `FACILITY` schemas |
| Concept | Securities financing transaction routed to **FCCM CCR EAD** | A lending exposure flagged as an SFT for the F-IRB maturity carve-out |
| Drives | The `sft_fccm` stage: `E* = max(0, E·(1+HE) − CVA·(1−HC−HFX))` | The F-IRB **0.5-year fixed supervisory maturity (`M`)** for repo-style transactions, in place of the date-derived Art. 162(2) `M` — or of the fixed 2.5 years where the firm has elected them (`firb_fixed_maturity`) |
| Regulatory basis | CRR Art. 220–223, Art. 271(2) | CRR Art. 162(1) (fixed `M = 0.5y`; deleted under Basel 3.1) |
| Engine site | `engine/sft/fccm.py` | `engine/irb/transforms.py` |

The lending `is_sft` Boolean is deliberately **not renamed** as part of the
SFT/FCCM separation — that would touch the sealed `hierarchy_resolved` edge,
the IRB transforms and every fixture that sets `is_sft` — so it is reserved
for a standalone future codemod. See the
[SFT (FCCM EAD) specification](../specifications/crr/sft/index.md#the-two-meanings-of-sft).

---

## Equity Exposure Schema

**Purpose:** Defines equity holdings (SA only under Basel 3.1, IRB approaches withdrawn).

| Column | Type | Required | Description |
|--------|------|----------|-------------|
| `exposure_reference` | `String` | Yes | Unique identifier |
| `counterparty_reference` | `String` | Yes | Link to counterparty |
| `equity_type` | `String` | No | Type of equity exposure (default `"other"`) |
| `currency` | `String` | No | ISO 4217 currency code |
| `carrying_value` | `Float64` | No | Balance sheet value |
| `fair_value` | `Float64` | No | Mark-to-market value |
| `is_speculative` | `Boolean` | No | Higher-risk equity (unlisted + business < 5yr) |
| `is_exchange_traded` | `Boolean` | No | Listed on recognised exchange |
| `is_government_supported` | `Boolean` | No | Government-supported programme |
| `is_significant_investment` | `Boolean` | No | The firm's assertion that the row is the **non-deducted** amount of a significant investment (>10%) in a financial sector entity, risk weighted 250% under Own Funds Art. 48(4) (the engine performs no deduction). **CRR:** 250% on every equity path — Art. 133(2) defers to Art. 48(4) on SA, and Art. 155(1) excludes the leg from the IRB simple-RW and PD/LGD approaches, so on those paths it takes 250% (not 190% / 290% / 370% or the K formula), carries no Art. 158(7) EL and is sealed `equity_method = "irb_fixed_rw"` (COREP C 10.01 row 0110 / C 02.00 row 0420 Equity IRB; not CR10.5 simple-RW equity). A `ciu` or `central_bank` row keeps its own treatment whatever the flag says. **Basel 3.1:** removes the leg from the rules 4.2 / 4.3 transitional (Art. 133(6)(c)); its weight stays the Art. 133(3) / (4) chain (P1.393). Default `False`; null is not an assertion |
| `ciu_approach` | `String` | No | CIU treatment selector — `"look_through"` (Art. 132(3)), `"mandate_based"` (Art. 132(4)), or `"fallback"` (1,250% per Art. 132(2)). When null the calculator selects based on data availability and falls back conservatively |
| `ciu_mandate_rw` | `Float64` | No | Mandate-based RW (decimal) when `ciu_approach = "mandate_based"`. Calculated upstream from the fund's investment mandate |
| `ciu_third_party_calc` | `Boolean` | No | True when the look-through RW has been calculated by an eligible third party (custodian / depositary / management company) per Art. 132(3) — relaxes the holding-level evidence requirement |
| `fund_reference` | `String` | No | Join key into the [CIU Holdings schema](#ciu-holdings-schema). Required when `ciu_approach = "look_through"` and `ciu_third_party_calc = False` |
| `fund_nav` | `Float64` | No | Fund NAV — denominator of the look-through RW formula `sum(holding_value_i × rw_i) / fund_nav`. See [equity-approach spec](../specifications/basel31/equity-approach.md) |
| `book_code` | `String` | No | Booking-unit code (default `""`) — mirrors the Facility/Loan/Contingent column; joined to the [Book-Entity Mapping](#multi-entity-reporting-schemas) by the scope resolver |
| `intragroup_entity_reference` | `String` | No | Intragroup tag — see Facility schema and [Multi-Entity Reporting](../features/multi-entity-reporting.md) |

**Valid `equity_type` values:**

| Value | Risk Weight | Description |
|-------|-------------|-------------|
| `central_bank` | 0% | Central bank equity holdings (Art. 133(6)) |
| `listed` | 100% | Exchange-traded equities |
| `exchange_traded` | 100% | Listed on recognised exchange |
| `government_supported` | 100% CRR / 250% B31 | Government-supported programme |
| `unlisted` | 250% | Unlisted equities |
| `private_equity` | 250% | Private equity investments |
| `private_equity_diversified` | 190% | Diversified private equity portfolio |
| `speculative` | 400% | Higher-risk (unlisted + business < 5yr) |
| `ciu` | Look-through | Collective investment undertakings |
| `other` | 250% | Other equity exposures |

---

## CIU Holdings Schema

**Purpose:** Per-holding constituents of a Collective Investment Undertaking (CIU) used by the **look-through approach** (Art. 132(3)). Each row represents one underlying exposure inside a fund, joined to the parent equity row via `fund_reference`. The look-through RW is computed as `sum(holding_value_i × rw_i) / fund_nav` and applied to the equity exposure's carrying value.

**File:** No canonical loader path — passed in-memory via `DataSourceConfig.ciu_holdings_file` (loader source: `engine/loader.py:139`). Not part of the standard fixture registry, since the CIU look-through is opt-in.

**When required:** Only when one or more `EQUITY_EXPOSURE` rows have `ciu_approach = "look_through"` and `ciu_third_party_calc = False`. If absent, CIU rows fall through to the mandate-based or punitive 1,250% fallback (Art. 132(2)) — see [equity-approach spec](../specifications/basel31/equity-approach.md).

| Column | Type | Required | Description |
|--------|------|----------|-------------|
| `fund_reference` | `String` | Yes | Join key to `EQUITY_EXPOSURE.fund_reference` — uniquely identifies the parent fund |
| `holding_reference` | `String` | Yes | Unique identifier for the holding within the fund |
| `exposure_class` | `String` | Yes | Exposure class of the underlying holding — an `ExposureClass` value, case-insensitive (`"corporate"`, `"institution"`, `"central_govt_central_bank"`, …). With `cqs` it drives the SA risk weight the holding takes "as if directly held" (Art. 132A(1)). A class the CQS table cannot price takes 100% (unrated corporate, retail, real estate, `other`), except: a nested CIU (`"ciu"`, a level 2 CIU with no look-through data of its own) takes the 1,250% fall-back (Art. 132(5)); `"high_risk"` takes 150% under Basel 3.1 (Art. 128) and 100% under CRR (Art. 128 omitted from UK CRR); a null or any value outside the vocabulary (e.g. `"sovereign"`, `"securitisation"`, `"subordinated_debt"`) takes 1,250% and raises **SA008** |
| `cqs` | `Int8` | No | Credit Quality Step of the underlying holding, where applicable |
| `holding_value` | `Float64` | No | Market value of the holding inside the fund — numerator of the look-through formula |

**Regulatory references:**

- **CRR Art. 132**: CIU treatment under the Standardised Approach
- **PRA PS1/26 Art. 132(2)**: Punitive 1,250% fallback when neither look-through nor mandate-based data is available
- **PRA PS1/26 Art. 132(3)**: Look-through approach — requires sufficient and frequent information about the underlying exposures
- **PRA PS1/26 Art. 132(4)**: Mandate-based approach — uses the fund's investment mandate / prospectus

**Example:**

```python
import polars as pl

ciu_holdings = pl.DataFrame({
    "fund_reference": ["FUND_001", "FUND_001", "FUND_001"],
    "holding_reference": ["HOLD_001", "HOLD_002", "HOLD_003"],
    "exposure_class": ["corporate", "central_govt_central_bank", "institution"],
    "cqs": [3, 1, 2],
    "holding_value": [40_000_000.0, 30_000_000.0, 30_000_000.0],
})

# Parent equity row links via fund_reference:
equity_exposures = pl.DataFrame({
    "exposure_reference": ["EQ_001"],
    "counterparty_reference": ["FUND_MGR_001"],
    "equity_type": ["ciu"],
    "ciu_approach": ["look_through"],
    "ciu_third_party_calc": [False],
    "fund_reference": ["FUND_001"],
    "fund_nav": [100_000_000.0],
    "carrying_value": [5_000_000.0],
    # ... other equity fields
})
```

---

## Facility Mapping Schema

**Purpose:** Defines parent-child relationships between facilities, loans, and contingents.

**File:** `exposures/facility_mapping.parquet`

| Column | Type | Required | Description |
|--------|------|----------|-------------|
| `parent_facility_reference` | `String` | Yes | Parent facility reference |
| `child_reference` | `String` | Yes | Child facility/loan/contingent reference |
| `child_type` | `String` | Yes | `facility`, `loan`, or `contingent` |

**Example:**

```python
import polars as pl

facility_mapping = pl.DataFrame({
    "parent_facility_reference": ["FAC_001", "FAC_001", "FAC_001"],
    "child_reference": ["LOAN_001", "LOAN_002", "FAC_001A"],
    "child_type": ["loan", "loan", "facility"],
})
```

**The mappings must form a tree.** Every consumer — undrawn headroom, the MOF waterfall, the
Facility Share fan-out, the collateral cascade — reads them as one. Shapes that are not a tree are
malformed input; the hierarchy stage resolves each deterministically and conservatively and names
it (review findings RC-01 / RC-02 / SF-03):

| Shape | Resolution | Code |
|-------|------------|------|
| A sub-facility mapped under two parents | Attached to its **lowest-referenced** parent only (it used to depend on row order, so RWA changed run to run) | `DQ021` WARNING |
| Facilities whose mappings form a cycle (`F1 -> F2 -> F1`, or `F -> F`) | Every member is treated as a **root of its own**, keeping its own limit and undrawn commitment (every member's undrawn row used to be dropped) | `DQ022` WARNING |
| A loan / contingent mapped under facilities of **different** roots | It reduces the headroom of **one** root only — that of its lowest-referenced parent; the other mappings are ignored, so those facilities' commitments are measured gross of it (every root used to be reduced) | `DQ021` WARNING |
| A loan / contingent mapped under two sub-limits of the **same** root | Each sub-limit's own headroom is reduced by it (an overlapping sub-limit genuinely constrains the same drawing), but the root's headroom only **once** (it used to be reduced twice) | `DQ021` WARNING |

The exposure row's own `parent_facility_reference` is its lowest-referenced remaining parent.
Example (both regimes, 100% obligor): `F1`, `F2` 2m `medium_risk`, `L1` 1m drawn mapped to both —
EAD = 1m + (2m − 1m) × 50% + 2m × 50% = **2.5m** (was 2.0m).

---

## Exposure reference uniqueness

Every input that becomes an exposure row shares **one** `exposure_reference` space: a loan's
`loan_reference`, a contingent's `contingent_reference` and an equity exposure's
`exposure_reference` verbatim, and the engine's own rows — `ccr__<netting_set_id>` (SA-CCR and
SFT netting sets), `ft__<failed_trade_id>`, `dfc__<contribution_id>` and
`<facility_reference>_UNDRAWN[_<sub>|_RESIDUAL|@<member>]`. Each table's own key must be unique
(`DQ004`), and a reference claimed by **two** of these namespaces raises one **`DQ019` ERROR**
(review finding RC-10): before, every join keyed on the bare reference merged the two rows — the
IRB model-permission de-duplication kept one of them, and a guarantee on the loan covered the
contingent too.

The run keeps them apart: each colliding loan / contingent is published as
`<reference>#loan` / `<reference>#contingent`, and every pointer to it is resolved by the type it
declares — `facility_mappings.child_type`, a short-term rating's `scope_type`, the
`beneficiary_type` of collateral, collateral links, guarantees and provisions, and a
securitisation allocation's `exposure_type`. A pointer whose type does not say which row it means
(`beneficiary_type` `exposure`, or null) matches **neither**. A facility reference equal to a loan
reference is not a collision — a facility is not an exposure row.

---

## Org Mapping Schema

**Purpose:** Defines the organisation hierarchy. It drives rating inheritance and the **group size figures**: every size test (the SME turnover / balance-sheet test, the Art. 153(4) IRB firm-size adjustment, the Basel 3.1 Art. 147(4C) large-corporate test and the Basel 3.1 large-FSE asset test) reads the maximum of the counterparty's own figure and every ancestor's along its parent chain, so a subsidiary is sized on its group's consolidated accounts and a figure-less apex (a fund, a holding company) does not hide the consolidating parent beneath it. CLS016 names counterparties whose own figures are SME-sized but whose group's are not. A child listed under two parents keeps the first row (DQ004).

**File:** `mapping/org_mapping.parquet`

| Column | Type | Required | Description |
|--------|------|----------|-------------|
| `parent_counterparty_reference` | `String` | Yes | Parent counterparty reference |
| `child_counterparty_reference` | `String` | Yes | Child counterparty reference |

**Example:**

```python
import polars as pl

org_mapping = pl.DataFrame({
    "parent_counterparty_reference": ["CORP_PARENT", "CORP_PARENT"],
    "child_counterparty_reference": ["CORP_001", "CORP_002"],
})
```

---

## Lending Mapping Schema

**Purpose:** Defines lending groups for retail threshold aggregation.

**File:** `mapping/lending_mapping.parquet`

| Column | Type | Required | Description |
|--------|------|----------|-------------|
| `parent_counterparty_reference` | `String` | Yes | Lending group lead reference |
| `child_counterparty_reference` | `String` | Yes | Member counterparty reference |

Exposures are aggregated to the group level for retail eligibility (threshold: EUR 1m CRR Art. 123(c) / GBP 880k Basel 3.1 Art. 123(1)(b)(ii)) and for the CRR Art. 501 SME supporting factor's E*. On a solo or sub-consolidated run both aggregates also count what the group owes to the reporting group's **other** registry entities (see [Multi-Entity Reporting](../features/multi-entity-reporting.md)).

---

## Multi-Entity Reporting Schemas

**Purpose:** Two OPTIONAL registries enabling per-scope regulatory submissions (group
consolidated, sub-consolidated, solo/individual) from one dataset. The scope-resolver
pipeline stage reads them to resolve a reporting entity's membership subtree and attribute
booking books to entities; when both are absent the pipeline runs unscoped exactly as before.
See [Multi-Entity Reporting](../features/multi-entity-reporting.md) for the full feature guide
(scope semantics, launching a scoped run, the `/hierarchy` page, and the `SCP001`-`SCP006`
data-quality codes).

### Reporting Entity Schema

**Purpose:** The reporting-hierarchy registry — one row per legal / reporting entity, linked
into a single-rooted tree by `parent_entity_reference`. This is the table that
`intragroup_entity_reference`, `guarantor_entity_reference`, and the Book-Entity Mapping's
`reporting_entity_reference` all point at.

**File:** `config/reporting_entities.parquet`

| Column | Type | Required | Description |
|--------|------|----------|-------------|
| `entity_reference` | `String` | Yes | Unique key for the entity |
| `entity_name` | `String` | No | Display name (falls back to `entity_reference` in the UI) |
| `lei` | `String` | No | Legal Entity Identifier (ISO 17442) |
| `parent_entity_reference` | `String` | No | Parent link forming the consolidation tree. Null = group apex (there must be exactly one root) |
| `institution_type` | `String` | No | Mirrors the `InstitutionType` enum values; feeds output-floor applicability per scope (Art. 92 para 2A) |
| `core_uk_group` | `Boolean` | No | CRR Art. 113(6) core-UK-group permission perimeter. Default `False`. On an **individual**-basis run, an intragroup exposure is assigned a **0% risk weight** when both the reporting entity and the tagged intragroup entity carry `core_uk_group=True` — see [Multi-Entity Reporting](../features/multi-entity-reporting.md#art-1136-core-uk-group-0-risk-weight). No effect on `consolidated` / `sub_consolidated` runs (intragroup rows are eliminated) or on unscoped runs |

**Example:**

```python
import polars as pl

reporting_entities = pl.DataFrame({
    "entity_reference": ["UK_BANK_HOLDCO", "RFB_SUBGROUP", "UK_BANK_PLC"],
    "entity_name": ["UK Bank Holdco", "Ring-Fenced Body Subgroup", "UK Bank plc"],
    "lei": [None, None, "213800ABCDEFGHIJKL12"],
    "parent_entity_reference": [None, "UK_BANK_HOLDCO", "RFB_SUBGROUP"],
    "institution_type": [None, None, "ring_fenced_body"],
    "core_uk_group": [False, False, False],
})
```

### Book-Entity Mapping Schema

**Purpose:** Attributes each booking `book_code` to the reporting entity that owns it, so the
scope resolver can filter exposure rows to a reporting scope's consolidation membership.

**File:** `mapping/book_entity_mapping.parquet`

| Column | Type | Required | Description |
|--------|------|----------|-------------|
| `book_code` | `String` | Yes | Booking-unit code, matched against `book_code` on Facility / Loan / Contingent / Equity Exposure / CCR netting sets / SFT trades |
| `reporting_entity_reference` | `String` | Yes | The `entity_reference` (from the Reporting Entity registry) that owns this book |

A book whose code is absent from this table cannot be attributed to any entity and is excluded
from every scoped run (`SCP001`), so every book that should count towards a scope must have a
mapping row.

**Example:**

```python
import polars as pl

book_entity_mapping = pl.DataFrame({
    "book_code": ["CORP_LENDING", "TRADE", "TREASURY_UK_PLC"],
    "reporting_entity_reference": ["UK_BANK_PLC", "UK_BANK_PLC", "UK_BANK_PLC"],
})
```

!!! note "CCR netting sets carry the same tag columns"
    The CCR **netting-set** schema (not separately catalogued on this page — see
    [SA-CCR specification](../specifications/crr/ccr/index.md)) carries the same `book_code`
    and `intragroup_entity_reference` columns as the frames above; the scope resolver filters
    at netting-set grain and semi-joins surviving trades / collateral onto the result.

---

## Model Permissions Schema

**Purpose:** Defines per-model IRB approach permissions, enabling granular control over which exposures can use FIRB, AIRB, or slotting. When `permission_mode=PermissionMode.IRB`, model permissions drive all approach routing. When absent in IRB mode, the pipeline falls back to SA for all exposures with a warning.

**Why model-level permissions matter:** Banks typically have multiple IRB models, each approved for specific exposure classes, geographies, and portfolios. This schema allows the calculator to resolve the correct approach per-exposure based on the model it belongs to, rather than applying a single org-wide permission.

**File:** `config/model_permissions.parquet`

| Column | Type | Required | Description |
|--------|------|----------|-------------|
| `model_id` | `String` | Yes | Unique model identifier (e.g., `"UK_CORP_PD_01"`) — referenced by `model_id` on internal ratings |
| `exposure_class` | `String` | Yes | ExposureClass value this permission covers (e.g., `"corporate"`, `"institution"`) |
| `approach` | `String` | Yes | Approved approach: `"foundation_irb"`, `"advanced_irb"`, or `"slotting"` |
| `country_codes` | `String` | No | Comma-separated ISO country codes where this permission applies. Null = all geographies. |
| `excluded_book_codes` | `String` | No | Comma-separated book codes excluded from this permission. Null = no exclusions. |

!!! note "Optional columns"
    When `country_codes` or `excluded_book_codes` columns are entirely absent from the input file, they are treated as null for all rows — all geographies are permitted and no book codes are excluded. You only need to include these columns if you want to restrict permissions by geography or exclude specific book codes.

**Approach determination logic:**

| Condition | Result |
|-----------|--------|
| AIRB permission + `internal_pd` + modelled `lgd` | **A-IRB** |
| AIRB permission + `internal_pd` + no `lgd` | **SA** (falls back unless FIRB permission also exists) |
| FIRB permission + `internal_pd` + no `lgd` | **F-IRB** (uses regulatory LGD floors) |
| Both AIRB + FIRB permissions + `internal_pd` + `lgd` | **A-IRB** (higher approach wins) |
| Both AIRB + FIRB permissions + `internal_pd` + no `lgd` | **F-IRB** (fallback) |
| Slotting permission + `internal_pd` | **Slotting** |
| No `model_id` on internal rating | **SA** (default) |

**Example:**

```python
import polars as pl

model_permissions = pl.DataFrame({
    "model_id": ["UK_CORP_PD_01", "UK_CORP_PD_01", "EU_INST_01"],
    "exposure_class": ["corporate", "corporate_sme", "institution"],
    "approach": ["advanced_irb", "foundation_irb", "advanced_irb"],
    "country_codes": ["GB", "GB,IE", None],  # None = all geographies
    "excluded_book_codes": [None, "LEGACY_BOOK", None],
})
```

---

## Data Preparation Checklist

Before running the calculator, verify your data meets these requirements:

- [ ] All required files present in expected locations
- [ ] Column names match schema exactly (case-sensitive)
- [ ] Data types match expected types
- [ ] All required columns have non-null values
- [ ] Reference columns have valid foreign key relationships
- [ ] Dates are in `YYYY-MM-DD` format
- [ ] Currency codes are valid ISO 4217
- [ ] Country codes are valid ISO 3166-1 alpha-2
- [ ] Numeric amounts are non-negative where expected
- [ ] PD values are in range [0, 1]
- [ ] LGD values are in range [0, 1.25]

See [Data Validation Guide](data-validation.md) for validation functions and troubleshooting.

---

## Next Steps

- [Data Validation Guide](data-validation.md) - Validation rules and error handling
- [Intermediate Schemas](intermediate-schemas.md) - Pipeline intermediate data
- [Output Schemas](output-schemas.md) - Calculation results
