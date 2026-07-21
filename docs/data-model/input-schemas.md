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
| `entity_type` | `String` | Yes | **Single source of truth** for exposure class (see valid values below) |
| `country_code` | `String` | No | ISO 3166-1 alpha-2 country code |
| `annual_revenue` | `Float64` | No | Annual revenue in GBP (for SME classification - EUR 50m threshold) |
| `total_assets` | `Float64` | No | Total assets in GBP (for LFSE threshold: EUR 70bn under CRR Art. 142(1)(4); GBP 79bn under PS1/26 Glossary p. 78) |
| `default_status` | `Boolean` | No | Whether counterparty is in default |
| `sector_code` | `String` | No | Industry sector code (SIC-based) |
| `apply_fi_scalar` | `Boolean` | No | User flag: True = apply 1.25x FI correlation scalar (CRR Art. 153(2)) |
| `is_managed_as_retail` | `Boolean` | No | SME managed on pooled retail basis (75% RW per CRR Art. 123) |
| `is_natural_person` | `Boolean` | No | True for individuals (natural persons). Required to qualify a counterparty for the SA retail exposure class (CRR Art. 123 / PS1/26 Art. 123 — the class is restricted to "natural persons or to a small or medium-sized enterprise"). Also drives the Basel 3.1 retail RE classification gates (PS1/26 Art. 124E(1) primary-residence exception, Art. 124H natural-person CRE branch) |
| `is_social_housing` | `Boolean` | No | True for social-housing providers. Under CRR Art. 123(d), exposures to a "social housing provider, or [a] non-profit association regulated by law" are eligible for retail-class treatment without the natural-person test. Under Basel 3.1 the same population qualifies for the Art. 124E(1) materially-dependent exception so the loan-splitter treats it as non-income-producing residential RE (PRA PS1/26) |
| `is_financial_sector_entity` | `Boolean` | No | True for financial sector entities (FSEs) as defined in CRR Art. 119(5) — credit institutions, investment firms, financial institutions, insurance and reinsurance undertakings, and similar regulated/unregulated entities. Used in conjunction with `apply_fi_scalar` and `total_assets` for the LFSE 1.25x correlation gate (Art. 142(1)(4) — "large financial sector entity") |
| `is_ccp_client_cleared` | `Boolean` | No | True when the counterparty is a CCP whose exposures arise from client-cleared trades — drives the QCCP 4% RW (vs 2% proprietary) under CRR Art. 306 / PS1/26 Art. 306 |
| `borrower_income_currency` | `String` | No | ISO 4217 currency in which the borrower earns income (or, for RRE indexation, the currency in which the borrower's repayment cashflows are denominated). Triggers **two** independent currency-mismatch tests: (1) **PRA PS1/26 Art. 123A** unhedged-FX retail uplift — when the *exposure* currency differs from `borrower_income_currency` for an unhedged retail exposure, the RW is multiplied by 1.5 (capped at 150%); (2) **PS1/26 Art. 124(2)(c)** RRE primary-residence carve-out — only available where the exposure currency matches the currency of the borrower's repayment cashflows |
| `local_currency` | `String` | No | Counterparty's domestic currency (ISO 4217). Two use sites: (1) **CRR Art. 114(4) sovereign domestic-currency carve-out** — exposures to a central government or central bank denominated **and** funded in that sovereign's own domestic currency may receive a 0% RW regardless of CQS (compared to `currency` on the loan/facility row); (2) currency-mismatch test for retail under PS1/26 Art. 123A when `borrower_income_currency` is unavailable — `local_currency` is then used as the proxy "income" currency. Distinct from `borrower_income_currency`, which is the obligor's actual income currency |
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
| `mdb` | MDB | CENTRAL_GOVT_CENTRAL_BANK | CRR Art. 117(1) — non-named MDB; institution table (CRR) / dedicated Table 2B (PS1/26 Art. 117(1)(a)) |
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
| `other_items_in_collection` | OTHER | OTHER | CRR Art. 134(2) / PS1/26 Art. 134(2) — cash items in the process of collection; **20% RW** |
| `other_tangible` | OTHER | OTHER | CRR Art. 134(7) / PS1/26 Art. 134(7) — other tangible assets, prepayments, and accrued income (where the counterparty cannot be identified); **100% RW** |
| `other_residual_lease` | OTHER | OTHER | CRR Art. 134(7) / PS1/26 Art. 134(7) — residual value of leasing exposures (i.e. the portion not captured as a lease receivable on the obligor); **100% RW** |

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

**How it works in the calculator:** The `apply_fi_scalar` flag on the counterparty record is the **sole input** — the calculator does not automatically compare `total_assets` against the framework-specific threshold. The user is responsible for setting `apply_fi_scalar = True` on counterparties that meet the regulatory LFSE (or unregulated FSE) criteria for the framework in use. The classifier derives `requires_fi_scalar` directly from this flag with no entity-type gate.

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

The classifier (`engine/classifier.py`) processes counterparties through these steps:

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
| `currency` | `String` | No | ISO 4217 currency code |
| `limit` | `Float64` | No | Committed facility limit |
| `committed` | `Boolean` | No | Whether the facility is a binding commitment to lend (default `True`). When `False`, the facility is treated as unconditionally cancellable: the hierarchy resolver does **not** generate a `facility_undrawn` exposure row, so no commitment CCF / EAD / RWA is held against the unused headroom. Loans and contingents already mapped to the facility are unaffected and continue to flow through the pipeline as their own exposure rows, with normal counterparty / parent rollup and collateral allocation. |
| `lgd` | `Float64` | No | Internal LGD estimate (A-IRB) |
| `lgd_unsecured` | `Float64` | No | A-IRB unsecured LGD estimate, applied to the residual EAD after eligible collateral (CRR Art. 181) |
| `beel` | `Float64` | No | Best estimate expected loss |
| `has_sufficient_collateral_data` | `Boolean` | No | A-IRB attestation that the firm has data quality sufficient to recognise own-estimate collateral effects under Art. 181(1)(f). When `False`, the LGD floor framework treats the row as if no collateral data is available |
| `is_revolving` | `Boolean` | No | Revolving vs term facility (default `False`) |
| `is_qrre_transactor` | `Boolean` | No | QRRE transactor flag. Drives the Basel 3.1 SA 45% weight (Art. 123(3)(a)) and the IRB 0.05% PD floor (Art. 163(1)(c)). True iff the revolving account has been repaid in full at each scheduled repayment date for the previous 12 months, OR the overdraft has not been drawn for the previous 12 months (PRA Glossary p. 9). Per Art. 154(4), accounts with less than 12 months of repayment history must be flagged False. Assessed upstream — not validated by the calculator. See [Transactor Exposure](../appendix/glossary.md#transactor-exposure). |
| `seniority` | `String` | No | `senior` (default) or `subordinated` (affects F-IRB LGD) |
| `risk_type` | `String` | No | Off-balance sheet risk category (see below) |
| `underlying_risk_type` | `String` | No | Underlying-exposure risk type used by the CRM substitution path when the facility's own `risk_type` would otherwise mask the protection's true category |
| `ccf_modelled` | `Float64` | No | A-IRB modelled CCF (0.0-1.5) |
| `ead_modelled` | `Float64` | No | A-IRB modelled EAD — when populated and approach is A-IRB, replaces the `drawn_amount + ccf x undrawn_amount` derivation (CRR Art. 166(8a)) |
| `is_short_term_trade_lc` | `Boolean` | No | Short-term trade LC for goods movement (Art. 166(9)) |
| `is_payroll_loan` | `Boolean` | No | Payroll-deduction / pension lending — qualifies for the Basel 3.1 35% retail RW (PS1/26 Art. 123(2)) |
| `is_buy_to_let` | `Boolean` | No | Buy-to-let property lending — excluded from SME supporting factor (CRR Art. 501) |
| `has_one_day_maturity_floor` | `Boolean` | No | Set True for short-term self-liquidating trade exposures and certain capital-markets-driven exposures eligible for the 1-day `M` floor under CRR Art. 162(3) (otherwise the standard 1-year floor applies) |
| `is_sft` | `Boolean` | No | Securities Financing Transaction — selects the F-IRB **0.5-year** repo-style supervisory maturity (`M`) under CRR **Art. 162(1)** (a fixed value, not a floor; deleted under Basel 3.1) |
| `effective_maturity` | `Float64` | No | Explicit numeric `M` override (years) per CRR Art. 162(3) / PS1/26. When populated it supersedes the `maturity_date`-derived `M` and bypasses the 1-year floor — firm-owned judgement for short-term carve-outs |
| `intragroup_entity_reference` | `String` | No | Non-null tags this facility as an intragroup claim on the named reporting entity (an `entity_reference` in the [Reporting Entity registry](#multi-entity-reporting-schemas)). Null (default) = external counterparty. Eliminated on a `consolidated` / `sub_consolidated` run, retained on `individual` — see [Multi-Entity Reporting](../features/multi-entity-reporting.md) |

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

**Valid `risk_type` values (CRR Art. 111 CCF Categories):**

| Code | Full Value | SA CCF | F-IRB CCF | Description |
|------|------------|--------|-----------|-------------|
| `FR` | `full_risk` | 100% | 100% | Direct credit substitutes, guarantees, acceptances |
| `MR` | `medium_risk` | 50% | 75% | NIFs, RUFs, standby LCs, committed undrawn |
| `MLR` | `medium_low_risk` | 20% | 75% | Documentary credits, trade finance |
| `LR` | `low_risk` | 0% | 0% | Unconditionally cancellable commitments |

**Note:** Under F-IRB (CRR Art. 166(8)), MR and MLR both become 75% CCF.

**F-IRB Exception (Art. 166(9)):** Short-term letters of credit arising from the movement of goods retain 20% CCF under F-IRB. To flag these exposures, set `is_short_term_trade_lc = True` for MLR risk type items.

| Column | Type | Required | Description |
|--------|------|----------|-------------|
| `is_short_term_trade_lc` | `Boolean` | No | True for short-term trade LCs for goods movement (Art. 166(9) - retains 20% CCF under F-IRB) |

**A-IRB Modelled CCF:** For A-IRB exposures, provide the bank's own modelled CCF estimate (0.0 to 1.5) in `ccf_modelled`. Retail IRB CCFs can exceed 100% due to additional drawdown behaviour. When populated and approach is A-IRB, this value takes precedence over the risk_type lookup.

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
    "risk_type": ["MR", "MR"],  # Medium risk - committed undrawn
    "ccf_modelled": [None, None],  # No modelled CCF (use regulatory)
})
```

---

## Loan Schema

**Purpose:** Defines drawn loan exposures (leaf nodes in exposure hierarchy). Loans represent actual credit usage under facilities.

**File:** `exposures/loans.parquet`

| Column | Type | Required | Description |
|--------|------|----------|-------------|
| `loan_reference` | `String` | Yes | Unique identifier for the loan |
| `product_type` | `String` | No | Product classification |
| `book_code` | `String` | No | Portfolio/book classification |
| `counterparty_reference` | `String` | Yes | Link to counterparty |
| `value_date` | `Date` | No | Loan origination date |
| `maturity_date` | `Date` | No | Loan maturity date |
| `currency` | `String` | No | ISO 4217 currency code |
| `drawn_amount` | `Float64` | No | Outstanding principal balance (default `0.0`) |
| `interest` | `Float64` | No | Accrued interest (adds to on-balance-sheet EAD) |
| `lgd` | `Float64` | No | Internal LGD estimate (A-IRB) |
| `lgd_unsecured` | `Float64` | No | A-IRB unsecured LGD estimate, applied to the residual EAD after eligible collateral (CRR Art. 181) |
| `beel` | `Float64` | No | Best estimate expected loss |
| `has_sufficient_collateral_data` | `Boolean` | No | A-IRB collateral data-quality attestation per Art. 181(1)(f). See Facility schema |
| `seniority` | `String` | No | `senior` (default) or `subordinated` (affects F-IRB LGD) |
| `is_payroll_loan` | `Boolean` | No | Payroll-deduction / pension lending — qualifies for the Basel 3.1 35% retail RW (PS1/26 Art. 123(2)) |
| `is_buy_to_let` | `Boolean` | No | Buy-to-let property lending — excluded from SME supporting factor (CRR Art. 501) |
| `has_one_day_maturity_floor` | `Boolean` | No | Eligible for the CRR Art. 162(3) 1-day `M` floor in lieu of the standard 1-year floor |
| `is_sft` | `Boolean` | No | Securities Financing Transaction — see Facility schema |
| `effective_maturity` | `Float64` | No | Explicit numeric `M` override (years) per CRR Art. 162(3) / PS1/26. Bypasses the 1-year floor when populated |
| `netting_agreement_reference` | `String` | No | CRR Art. 195/219 on-balance-sheet netting set. A non-null reference is the sole signal that the loan participates in a netting agreement; exposures net against each other **iff they share the same reference** — independent of facility or counterparty |
| `due_diligence_performed` | `Boolean` | No | Basel 3.1 Art. 110A: True if the firm has performed the prescribed due-diligence assessment of the obligor. Required for the SA RW override below to apply. Absence raises diagnostic warning **SA004** under B3.1 |
| `due_diligence_override_rw` | `Float64` | No | Basel 3.1 Art. 110A SA RW override (decimal, e.g. `1.50` for 150%). Applied as `max(calculated_rw, override_rw)` — the override can only **increase** the regulatory RW, never decrease it. CRR-only runs ignore this column |
| `intragroup_entity_reference` | `String` | No | Intragroup tag — see Facility schema and [Multi-Entity Reporting](../features/multi-entity-reporting.md) |

**Note:** Loans do not have CCF fields (`risk_type`, `ccf_modelled`, `is_short_term_trade_lc`) because CCF only applies to off-balance sheet items. For drawn loans, EAD = `drawn_amount` + `interest` directly.

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
| `ccf_modelled` | `Float64` | No | A-IRB modelled CCF (0.0-1.5) |
| `ead_modelled` | `Float64` | No | A-IRB modelled EAD — replaces the CCF-derived value when populated under A-IRB (CRR Art. 166(8a)) |
| `is_short_term_trade_lc` | `Boolean` | No | Short-term trade LC for goods movement (Art. 166(9)) |
| `has_one_day_maturity_floor` | `Boolean` | No | Eligible for the CRR Art. 162(3) 1-day `M` floor |
| `is_sft` | `Boolean` | No | Securities Financing Transaction — see Facility schema |
| `effective_maturity` | `Float64` | No | Explicit numeric `M` override (years) per CRR Art. 162(3) / PS1/26 |
| `bs_type` | `String` | No | `"ONB"` (on-balance-sheet / drawn) or `"OFB"` (off-balance-sheet / undrawn). Default: `"OFB"` |
| `due_diligence_performed` | `Boolean` | No | Basel 3.1 Art. 110A due-diligence attestation (see Loan schema) |
| `due_diligence_override_rw` | `Float64` | No | Basel 3.1 Art. 110A SA RW override (max-only — see Loan schema) |
| `intragroup_entity_reference` | `String` | No | Intragroup tag — see Facility schema and [Multi-Entity Reporting](../features/multi-entity-reporting.md) |

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
    "risk_type": ["FR", "MR", "MLR"],  # FR=100%, MR=50%/75%, MLR=20%/75%
    "ccf_modelled": [None, None, None],  # No modelled CCF
    "is_short_term_trade_lc": [False, False, True],  # Third is Art. 166(9) exception
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
| `currency` | `String` | No | ISO 4217 currency code |
| `maturity_date` | `Date` | No | Collateral maturity (if applicable) |
| `market_value` | `Float64` | Conditional | Current market value (required unless `pledge_percentage` provided) |
| `nominal_value` | `Float64` | No | Nominal/face value |
| `pledge_percentage` | `Float64` | Conditional | Fraction of beneficiary EAD (0.5 = 50%). Used when `market_value` not provided. Resolved to absolute `market_value` before haircuts. |
| `beneficiary_type` | `String` | Yes | Level of allocation |
| `beneficiary_reference` | `String` | Yes | Reference to counterparty/facility/loan |
| `issuer_cqs` | `Int8` | No | CQS of issuer (for securities) |
| `issuer_type` | `String` | No | Issuer type (for haircut lookup) |
| `residual_maturity_years` | `Float64` | No | Residual maturity in years |
| `original_maturity_years` | `Float64` | No | Original maturity in years — used for collateral maturity-band differentiation where the haircut depends on issuance maturity rather than residual maturity |
| `is_eligible_financial_collateral` | `Boolean` | No | Meets SA eligibility (CRR Art 197) |
| `is_eligible_irb_collateral` | `Boolean` | No | Meets IRB eligibility (CRR Art 199) |
| `is_lease_collateral_attested` | `Boolean` | No | CRR Art. 199(7)/211: the leased asset of a finance-lease exposure attested to meet the Art. 211 lease-specific conditions (robust lessor risk management, legal ownership, unamortised-vs-market-value gap). Supply the leased asset as a `real_estate` / `other_physical` collateral row pledged to the lease exposure with this flag `True`; it is an independent F-IRB Foundation Collateral Method eligibility route (subsumes the Art. 208/210 conditions `is_eligible_irb_collateral` carries). No default: null → not attested → not recognised (conservative). Consulted only for non-financial collateral |
| `is_airb_model_collateral` | `Boolean` | No | Default `False`. When `True`, the firm asserts the collateral has been used to construct the internal LGD model (CRR Art. 181 / Basel 3.1 Art. 169A). The CRM allocator excludes flagged rows from non-AIRB exposures (no double-counting of the modelled-LGD effect) and routes them only to AIRB-pool exposures whose modelled LGD is preserved. Direct allocation of a flagged row onto a non-AIRB exposure raises CRM006 |
| `is_qualifying_re` | `Boolean` | No | Meets Basel 3.1 qualifying real-estate criteria for the loan-splitter (PS1/26 Art. 124A finished-property / legal-enforceability / valuation / borrower-ability tests). Drives Art. 124F (RRE) / Art. 124H (CRE) eligibility |
| `is_main_index` | `Boolean` | No | Equity collateral listed on a recognised main index (e.g. FTSE 100) — qualifies for the lower main-index haircut (CRR Art. 197(8)) |
| `is_own_issued_cln` | `Boolean` | No | CRR/PS1-26 Art. 218: attests that a `credit_linked_note` collateral row is issued by the **lending institution itself** — the only case Art. 218 grants cash-collateral treatment (0% haircut, full EAD/LGD\* offset). No default: null → own-issuance unattested → the CLN is treated as ineligible funded protection (a third-party CLN is materially correlated with its reference entity, Art. 194(4)); its value is zeroed and a `CRM019` warning is raised. Consulted only for `credit_linked_note` collateral |
| `valuation_date` | `Date` | No | Date of last valuation |
| `valuation_type` | `String` | No | `market`, `indexed`, `independent` |
| `property_type` | `String` | No | `residential` or `commercial` (RE only) |
| `property_ltv` | `Float64` | No | Regulatory LTV per Art. 124C — must include prior/pari passu charges (Art. 124C(3)) in numerator |
| `prior_charge_ltv` | `Float64` | No | LTV portion from prior/pari passu charges only (Art. 124C(3)); 0.0 = first charge. Used by Art. 124F(2)/124G(2) junior charge treatment |
| `is_income_producing` | `Boolean` | No | Material dependency on property cash flows per Art. 124E. `True` = materially dependent (residential: Art. 124G whole-loan; commercial: Art. 124I). `False`/null = not materially dependent (residential: Art. 124F loan-splitting; commercial: Art. 124H). For residential RE, this requires upstream assessment of Art. 124E(1) exceptions (primary residence, three-property limit, social housing, cooperative). For commercial RE, the own-business-use test (Art. 124E(6)). See [Art. 124E spec](../specifications/basel31/sa-risk-weights.md#real-estate-material-dependency-classification-art-124e) |
| `is_adc` | `Boolean` | No | Acquisition/Development/Construction |
| `is_presold` | `Boolean` | No | ADC pre-sold to qualifying buyer |
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
| `bond` | Bond securities — haircut depends on `issuer_type`, `issuer_cqs`, and `residual_maturity_years` |
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
| `guarantee_reference` | `String` | Yes | Unique identifier |
| `guarantee_type` | `String` | No | Type of guarantee |
| `guarantor` | `String` | Yes | Guarantor counterparty reference |
| `currency` | `String` | No | ISO 4217 currency code |
| `maturity_date` | `Date` | No | Guarantee expiry date |
| `amount_covered` | `Float64` | Conditional | Amount covered by guarantee (required unless `percentage_covered` provided) |
| `percentage_covered` | `Float64` | Conditional | Fraction of exposure covered (`1.0` = 100%). Used when `amount_covered` not provided |
| `beneficiary_type` | `String` | Yes | Level of allocation |
| `beneficiary_reference` | `String` | Yes | Reference to counterparty/facility/loan |
| `protection_type` | `String` | No | `"guarantee"` (default) or `"credit_derivative"` — drives CRM treatment under CRR Art. 213 vs Art. 215 (credit-derivative-specific eligibility tests) |
| `includes_restructuring` | `Boolean` | No | True when the credit derivative includes restructuring as a credit event. Required for full recognition under CRR Art. 216(1)(d); when False the recognised cover is reduced to 60% per Art. 216(1)(e) |
| `guarantor_entity_reference` | `String` | No | Non-null tags the guarantor as the named group reporting entity (an `entity_reference` in the [Reporting Entity registry](#multi-entity-reporting-schemas)). Internal protection is not CRM at the consolidated / sub-consolidated level, so such rows are dropped there; kept on an individual run. Null (default) = external guarantor — see [Multi-Entity Reporting](../features/multi-entity-reporting.md) |

**Valid `guarantee_type` values:**

| Value | Description |
|-------|-------------|
| `guarantee` | Standard guarantee |
| `credit_derivative` | Credit derivative protection |
| `counter_guarantee` | Counter-guarantee |

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
| `project_phase` | `String` | No | Project lifecycle phase — typically `"planning"`, `"construction"`, or `"operational"`. Drives the CRE33.5 < 2.5-year strong/good preferential weights (which only apply during construction / pre-operational phase) |
| `slotting_category` | `String` | No | Slotting category |
| `is_hvcre` | `Boolean` | No | High-volatility commercial real estate |

**Valid `sl_type` values:**

| Value | Description |
|-------|-------------|
| `project_finance` | Project finance (PF) |
| `object_finance` | Object finance (OF) |
| `commodities_finance` | Commodities finance (CF) |
| `ipre` | Income-producing real estate |
| `hvcre` | High-volatility commercial real estate |

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
trade row** — FCCM's current scope is single-trade, single-counterparty
netting sets (Art. 220(1)(a)), so no separate SFT netting-set table is
needed. The three `exposure_*` columns carry the Art. 223(5) exposure-side
volatility-haircut (`HE`) inputs.

| Column | Type | Required | Description |
|--------|------|----------|-------------|
| `trade_id` | `String` | Yes | Unique identifier for the SFT |
| `netting_set_id` | `String` | Yes | Netting-set reference — used for the `ccr__<netting_set_id>` output reference and the collateral join |
| `counterparty_reference` | `String` | Yes | Counterparty (denormalised from the netting set) — drives the SA institution risk-weight lookup (CRR Art. 120(1) Table 3) |
| `notional` | `Float64` | Yes | `E` — the exposure amount lent / sold under the SFT (Art. 223(5)) |
| `currency` | `String` | Yes | ISO 4217 currency code of the exposure |
| `maturity_date` | `Date` | Yes | SFT maturity date |
| `start_date` | `Date` | Yes | SFT start date |
| `exposure_collateral_type` | `String` | No | `HE` input — exposure-side security type for the Art. 224 Table 1 haircut lookup. Null when the exposure side is cash / a standard loan (`HE = 0`) |
| `exposure_security_cqs` | `Int8` | No | `HE` input — exposure-side issuer CQS |
| `exposure_security_residual_maturity_years` | `Float64` | No | `HE` input — exposure-side residual maturity (years) |
| `is_margined` | `Boolean` | No (default `False`) | Branch selector (Art. 224(2) final subparagraph). `False` → unmargined branch (today's behaviour); `True` → the margined Art. 285 MPOR branch |
| `remargining_frequency_days` | `Int16` | No (default `1`) | Dual role: `N_R` for the Art. 226 non-daily revaluation factor on the **unmargined** branch (1 = daily revaluation, factor = 1.0) / `N` in `MPOR = F + N − 1` on the **margined** branch |
| `mpor_floor_category` | `String` | No (default `repo_only`) | MPOR floor `F` selector (margined branch only): `repo_only` → 5 (Art. 285(2)(a)) / `other` → 10 (Art. 285(2)(b)) / `illiquid_or_large` → 20 (Art. 285(3)). Constrained to `VALID_MPOR_FLOOR_CATEGORIES` |
| `has_margin_dispute_doubling` | `Boolean` | No (default `False`) | `True` doubles `F` for the two quarters following more than two margin disputes (Art. 285(4)) |
| `mpor_days_override` | `Int16` | No (default `null`) | Explicit MPOR in business days; supersedes the `F + N − 1` derivation when set |
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
| `market_value` | `Float64` | No (default `0.0`) | `CVA` — collateral market value in the `E*` formula; `0.0` when unknown (no collateral credit) |
| `currency` | `String` | No | Collateral currency. Drives the `HFX` same-currency shortcut (Art. 224 Table 4: `HFX = 0` when collateral and exposure currencies match) |
| `issuer_cqs` | `Int8` | No | `HC` input — collateral issuer CQS |
| `residual_maturity_years` | `Float64` | No | `HC` input — collateral residual maturity (years) |

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
| Drives | The `sft_fccm` stage: `E* = max(0, E·(1+HE) − CVA·(1−HC−HFX))` | The F-IRB **0.5-year fixed supervisory maturity (`M`)** for repo-style transactions, in place of the 2.5-year default |
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
| `is_significant_investment` | `Boolean` | No | >10% of CET1 |
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
| `exposure_class` | `String` | Yes | Exposure class of the underlying holding (`"corporate"`, `"institution"`, `"sovereign"`, etc.) — drives the SA risk weight applied |
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
    "exposure_class": ["corporate", "sovereign", "institution"],
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

---

## Org Mapping Schema

**Purpose:** Defines organisation hierarchy for rating and turnover inheritance.

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

Exposures are aggregated to the group level for retail eligibility (threshold: EUR 1m CRR Art. 123(c) / GBP 880k Basel 3.1 Art. 123(1)(b)(ii)).

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
