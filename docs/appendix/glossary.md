# Glossary

This glossary provides definitions for key terms used throughout the documentation.

## A

### A-IRB (Advanced Internal Ratings-Based)
An IRB approach where the bank estimates PD, LGD, and EAD using internal models, subject to regulatory floors and approval.

### ADC (Acquisition, Development, and Construction)
An exposure to a corporate or SPE financing land acquisition for development and construction, or financing development and construction of residential or commercial real estate. ADC exposures are excluded from the regulatory real estate framework (Art. 124A) and receive standalone risk weights under Art. 124K: 150% standard, 100% for qualifying residential with pre-sales or substantial borrower equity at risk.

### Asset Correlation
A measure of how closely the value of an asset moves with systematic risk factors. Higher correlation means more sensitivity to economic conditions.

## B

### Basel 3.0
The international regulatory framework for banks implemented through CRR in the UK. Effective until December 2026.

### Basel 3.1
The revised Basel framework implemented through PRA PS1/26, effective from January 2027. Introduces output floors, removes supporting factors.

### BCBS
Basel Committee on Banking Supervision. The international body that develops banking standards.

### BEEL (Best Estimate of Expected Loss)
An A-IRB institution's own estimate of the economic loss expected on a defaulted
exposure over the recovery period, expressed as a fraction of exposure at default.
Under PRA PS1/26 Art. 158(5) the EL **amount** for defaulted exposures (PD = 1)
treated under A-IRB is `BEEL × EAD` rather than `PD × LGD × EAD` — BEEL substitutes
for the standard product only on the A-IRB side of the Art. 159 provisions-vs-EL
comparison (Pool C). F-IRB defaulted exposures retain `1 × LGD` for Pool C.

The A-IRB capital formula `K = max(0, LGD − BEEL)` in Art. 154(1)(i) additionally
consumes BEEL in the RW calculation. BEEL must be estimated under the Art. 181(1)(h)(ii)
standards (downturn conditions, recognition of unexpected additional loss during
recovery, symmetric use of recovery realisations, governance and validation). Sovereign,
central-bank, and quasi-sovereign exposures cannot use A-IRB under Art. 147A(1)(a), so
BEEL does not arise for those classes.

Pre-revocation CRR used the symbol `ELBE` (Expected Loss Best Estimate) for the same
parameter; PS1/26 renames to `BEEL` with no substantive change. See
[Defaulted Exposures spec — BEEL](../specifications/basel31/defaulted-exposures.md#beel-best-estimate-of-expected-loss-art-1585-art-1811hii).

## C

### Capital Requirement
The minimum amount of capital a bank must hold against its risk exposures. Calculated as RWA × Capital Ratio.

### CCF (Credit Conversion Factor)
A percentage applied to off-balance sheet exposures to convert them to on-balance sheet equivalents for capital calculation.

### CQS (Credit Quality Step)
A standardized credit quality scale (1-6) used to map external credit ratings to risk weights.

### CRE (Credit Risk - Real Estate)
Basel Committee standards for credit risk treatment of real estate exposures.

### CRM (Credit Risk Mitigation)
Techniques used to reduce credit risk exposure, including collateral, guarantees, and provisions.

### CRR (Capital Requirements Regulation)
EU regulation 575/2013 as onshored into UK law. The primary regulatory framework for credit risk capital.

## D

### Default
An event where a counterparty fails to meet its credit obligations. Formally defined by Art. 178 (CRR and PRA PS1/26) as satisfying **either** limb:

- **(a) Unlikeliness to pay (UTP)** — the institution considers the obligor unlikely to pay in full without recourse to actions such as realising security. Indicators include non-accrued status, specific credit risk adjustment for credit-quality decline, sale at material credit-related loss, distressed restructuring, institution-filed bankruptcy, or obligor-sought bankruptcy protection (Art. 178(3)(a)–(f)).
- **(b) 90 days past due (DPD)** on any **material** credit obligation. Materiality under PS1/26: retail > GBP 0 / > 0%; non-retail > GBP 440 / > 1% (Art. 178(2)(d)/(da)). CRR delegates materiality to the competent authority.

Retail exposures may apply the definition at the **facility level**; non-retail default at the **obligor level**. Return to non-defaulted status requires a 3-month cure (Art. 178(5)) or a 1-year probation with material payments after a distressed restructuring (Art. 178(5A)–(5C)).

The calculator consumes default status via the `is_defaulted` input flag — **no DPD counter, UTP inference, or cure-period timer runs in-engine**. See the [Default Definition specification](../specifications/common/default-definition.md) for the full Art. 178 treatment.

### DPD (Days Past Due)
The number of days a payment is overdue.

### Due Diligence Obligation (Art. 110A)
Basel 3.1 framework-wide obligation (PRA PS1/26 Art. 110A) requiring SA firms to assess each obligor's operating and financial condition, review annually, and factor in corporate-group membership. Where internal analysis shows the class/ECAI-based risk weight understates risk, the firm must apply a higher RW (uplift is unbounded, unlike the one-CQS-step Art. 120(4) / 122(4) / 129(4A) overrides). Exempt obligor classes (Art. 110A(5)): central governments and central banks, RGLA, PSE, named 0%-RW MDBs (Art. 117(2)), international organisations (Art. 118(1)). No CRR equivalent. Implementation: `due_diligence_performed` / `due_diligence_override_rw` input fields; `SA004` warning under B31 when DD status absent; `due_diligence_override_applied` audit column. See [B31 SA spec](../specifications/basel31/sa-risk-weights.md#due-diligence-obligation-art-110a).

## E

### EAD (Exposure at Default)
The expected exposure amount at the time of default. For on-balance sheet items, typically the gross carrying amount. For off-balance sheet: `EAD = Drawn + (Undrawn x CCF)`.

### Equity Exposure
Holdings of equity instruments (shares, funds) receiving dedicated risk weight treatment under CRR Art. 133 (SA) or Art. 155 (IRB Simple).

### ECRA (External Credit Risk Assessment Approach)
Basel 3.1 approach for institutions using external ratings.

### EL (Expected Loss)
The anticipated loss on a portfolio. Calculated as PD × LGD × EAD.

### Exposure Class
A regulatory classification of exposures (Central Govt / Central Bank, Institution, Corporate, Retail, etc.) that determines applicable risk weights.

## F

### F-IRB (Foundation Internal Ratings-Based)
An IRB approach where the bank estimates PD but uses supervisory values for LGD and CCF.

### FI Scalar
A 1.25x multiplier applied to the **asset correlation coefficient** (R) for large financial sector entities (LFSEs) or unregulated financial sector entities (Art. 153(2), unchanged between CRR and Basel 3.1). This has a non-linear effect on the capital requirement K. LFSE threshold is **EUR 70 billion** total assets under CRR (Art. 142(1)(4)) and **GBP 79 billion** under Basel 3.1 (PRA PS1/26 Glossary p. 78, with Note "corresponds to Article 142(1)(4) of CRR"). Not to be confused with the Art. 147A large corporate approach restriction (revenue > GBP 440m), which restricts A-IRB eligibility but does not affect correlation.

### Financial Collateral
Liquid assets (cash, bonds, equity) used as security for credit exposures.

### FX Mismatch Haircut
An 8% additional haircut applied when collateral currency differs from exposure currency (CRR Art. 233).

## G

### GCRA (General Credit Risk Adjustment)
General provisions not allocated to specific exposures. May be included in Tier 2 capital.

### Guarantee
Credit protection provided by a third party. Allows substitution of the guarantor's risk weight.

## H

### Haircut
A percentage reduction applied to collateral value to account for potential price volatility and liquidation costs.

### HVCRE (High Volatility Commercial Real Estate)
Speculative commercial real estate development with elevated slotting risk weights. **Introduced by PRA PS1/26** Art. 153(5) Table A — the UK onshored CRR has no HVCRE concept (only a single slotting table for all SL types). The original EU CRR had a separate Table 2 for HVCRE but this was not retained in UK onshoring.

## I

### IFRS 9
International accounting standard for financial instruments, including impairment (ECL) requirements.

### Implicit Government Support
A component of an ECAI credit assessment that relies on expected extraordinary support from central, regional, or local government (typically the "too big to fail" uplift for systemic private banks). **Basel 3.1 Art. 138(1)(g)** prohibits using such assessments to risk-weight exposures to institutions, *unless* the rated institution is owned by or set up and sponsored by a government body. **Art. 139(6)** then imposes a residual "higher-of" floor where no "clean" issue-specific rating exists. No CRR equivalent — CRR Art. 138 has only sub-points (a)–(f) and CRR Art. 139 has only paragraphs (1)–(4); CRR firms apply implicit-support ratings directly. See [B31 SA Risk Weights — Art. 138(1)(g), Art. 139(6)](../specifications/basel31/sa-risk-weights.md#ecai-assessment-implicit-government-support-art-1381g-art-1396).

### Infrastructure Factor
CRR capital relief factor (0.75) for qualifying infrastructure project finance. Removed under Basel 3.1.

### IPRE (Income-Producing Real Estate)
Real estate where repayment is materially dependent on cash flows generated by the property (rental income, sale proceeds). Under Basel 3.1 Art. 124E, residential RE is materially dependent by default unless it meets one of five exceptions (primary residence, three-property limit for natural persons, SPE with guarantor, social housing, or cooperative). Commercial RE is materially dependent unless the borrower uses the property predominantly for its own business (Art. 124E(6)). SA treatment: whole-loan LTV-band risk weights (Art. 124G/124I). IRB treatment: slotting approach (Art. 147A). See [Art. 124E specification](../specifications/basel31/sa-risk-weights.md#real-estate-material-dependency-classification-art-124e).

### IRB (Internal Ratings-Based)
Approaches allowing banks to use internal risk estimates for capital calculation, subject to regulatory approval.

## K

### K (Capital Requirement)
The IRB formula output representing the capital requirement as a percentage of EAD.

## L

### LazyFrame
A Polars data structure representing deferred (lazy) computations on data, enabling query optimization.

### LGD (Loss Given Default)
The percentage of exposure lost if default occurs, after accounting for recoveries.

### LTV (Loan-to-Value)
The ratio of a loan amount to the value of the underlying collateral (typically property).

## M

### MA (Maturity Adjustment)
An adjustment factor in the IRB formula accounting for increased risk of longer-dated exposures.

### MDB (Multilateral Development Bank)
International financial institutions (World Bank, EIB, etc.) that may receive preferential risk weights.

## O

### Overcollateralisation
The requirement that non-financial collateral must exceed the exposure value by a regulatory ratio to receive full CRM benefit. Ratios: financial 1.0x, receivables 1.25x, real estate/other physical 1.4x (CRR Art. 230).

### Output Floor
Basel 3.1 requirement that IRB RWA cannot fall below 72.5% of the equivalent SA RWA.

## P

### PD (Probability of Default)
The likelihood that a counterparty will default within one year. Range: 0% to 100%.

### PRA (Prudential Regulation Authority)
The UK banking regulator responsible for implementing Basel standards.

### PSE (Public Sector Entity)
Non-commercial government bodies that may receive preferential treatment.

## Q

### QRRE (Qualifying Revolving Retail Exposures)
Unsecured revolving credit to individuals (credit cards, overdrafts) meeting specific criteria.

## R

### RGLA (Regional Government and Local Authority)
Sub-national government entities with varying risk treatments.

### Regulatory Real Estate Exposure
A real estate exposure that meets all six qualifying criteria in PRA PS1/26 Art. 124A(1): (a) property condition, (b) legal certainty, (c) charge conditions, (d) Art. 124D valuation, (e) borrower independence, (f) insurance monitoring. Only regulatory RE exposures qualify for the preferential risk weights in Art. 124F–124I. Non-qualifying exposures are "other real estate" under Art. 124J. In the calculator, the `is_qualifying_re` Boolean input field controls this routing.

### Risk Type
A classification for off-balance sheet exposures that determines the applicable CCF. Valid values: FR (full_risk, 100%), MR (medium_risk, 50%/75%), MLR (medium_low_risk, 20%/75%), LR (low_risk, 0%). See CRR Art. 111.

### Risk Weight
A percentage applied to EAD to calculate RWA. Higher risk weights indicate higher risk.

### RWA (Risk-Weighted Assets)
Assets adjusted for risk, used to calculate capital requirements. RWA = EAD × Risk Weight.

## S

### SA (Standardised Approach)
A capital calculation approach using regulatory-prescribed risk weights based on external ratings.

### Scaling Factor
CRR 1.06 multiplier applied to all IRB RWA. Removed under Basel 3.1.

### SCRA (Specific Credit Risk Adjustment)
Provisions allocated to specific exposures. Reduces EAD for SA, compares to EL for IRB.

### SCRA (Standardised Credit Risk Assessment Approach)
Basel 3.1 approach for unrated institutions based on capital adequacy ratios.

### Self-Build Exposure
A residential real estate exposure secured by property or land that has been acquired
or held for development and construction purposes, as defined in PS1/26 Appendix 1
Art. 1.2 (p. 27). To qualify the property must (1) not have more than **four residential
housing units** and (2) be (or be intended to be) the **borrower's primary residence**.
Self-build exposures are the only category under **Art. 124A(1)(a)(iii)** that lets an
exposure secured by land held for development qualify as **regulatory RE** before the
build is complete — the other two gates in Art. 124A(1)(a)(i)/(ii) both require finished
property. In exchange, Art. 124D(9) requires the property value used in the Art. 124C LTV
denominator to be the **higher of** the pre-construction underlying land value and **0.8
× the latest qualifying valuation**, with Art. 124D(10) applying the same 0.8 haircut (or
max(0.8 × updated valuation, updated land estimate)) after any Art. 124D(5)(a)/(b)
revaluation. The 0.8 multiplier enforces a 20% buffer against residual construction /
permitting / market-absorption risk. CRR had no equivalent concept — Art. 124D(9)/(10) is
new Basel 3.1 drafting effective 1 January 2027. See
[SA Risk Weights — Self-Build Valuation](../specifications/basel31/sa-risk-weights.md#self-build-valuation-art-124d9-and-124d10).

### Slotting Approach
A capital calculation method for specialised lending using supervisory categories (Strong/Good/Satisfactory/Weak).

### SME (Small and Medium Enterprise)
Companies with annual turnover below the framework-specific threshold qualifying for
preferential treatment. **Under CRR** the threshold is **EUR 50m** (used by the
Art. 501 SME Supporting Factor and by the Art. 153(4) IRB firm-size correlation
adjustment). **Under Basel 3.1 (PS1/26)** the threshold is fixed at **GBP 44m**
per the PS1/26 Glossary definition (p.9), calculated on the highest consolidated
accounts of the group; this applies both in the SA (Art. 122(11) 85% SME corporate
rate, Art. 123(1)(b) retail SME classification) and in the IRB (Art. 153(4) firm-size
adjustment, which retains the EUR 50m cap in the reduction formula but gates
SME eligibility via the GBP 44m SME definition).

### SME Supporting Factor
CRR capital relief factor (0.7619/0.85) for SME exposures. Removed under Basel 3.1.

### Central Govt / Central Bank (Sovereign)
Exposure to a government or central bank. The exposure class formerly known as "Sovereign".

### Specialised Lending
Project finance, object finance, commodities finance, and real estate exposures with specific treatments.

## T

### Tier 1 Capital
High-quality capital including common equity (CET1) and additional Tier 1 instruments.

### Tier 2 Capital
Supplementary capital including subordinated debt and general provisions.

### Transactor Exposure
A qualifying revolving retail exposure (QRRE) that meets one of two behavioural tests over the **previous 12-month period**, as defined by the PRA Glossary (PS1/26 Appendix 1, p. 9):

1. A revolving facility (credit cards, charge cards, and similar where the balance due at each scheduled repayment date is determined as the amount drawn at a pre-defined reference date) where the obligor has repaid the balance in full at **each** scheduled repayment date for the previous 12-month period; or
2. An overdraft facility that the obligor has not drawn down over the previous 12-month period.

Transactor exposures receive a preferential **45% SA risk weight** under PRA PS1/26 Art. 123(3)(a) (vs 75% for non-transactors under Art. 123(3)(b)) and a **0.05% IRB PD floor** under Art. 163(1)(c) (vs 0.10% for non-transactors). Art. 154(4) explicitly classifies revolving exposures with less than 12 months of repayment history as non-transactors. The 12-month behavioural assessment is the reporting institution's responsibility; the `is_qrre_transactor` input flag is accepted as-is by the calculator. CRR SA has no transactor sub-category — the concept is new to the SA risk-weight table in Basel 3.1. See [SA Risk Weights — Transactor Exposure Eligibility](../specifications/basel31/sa-risk-weights.md#transactor-exposure-eligibility-art-1233a-pra-glossary).

## U

### Unexpected Loss (UL)
Losses above expected levels, covered by regulatory capital. UL = RWA × 8%.

---

## Key Formulas Reference

| Formula | Expression | Reference |
|---------|------------|-----------|
| **SA RWA** | `EAD x RW x SF` | CRR Art. 113 |
| **IRB RWA** | `K x 12.5 x EAD x MA x [1.06]` | CRR Art. 153 |
| **IRB K** | `LGD x N[(1-R)^(-0.5) x G(PD) + (R/(1-R))^(0.5) x G(0.999)] - PD x LGD` | CRR Art. 153 |
| **Corporate Correlation** | `0.12 x f(PD) + 0.24 x (1 - f(PD))` where `f(PD) = (1-e^(-50xPD))/(1-e^(-50))` | CRR Art. 153 |
| **SME Adjustment** | `0.04 x (1 - (max(5,min(S,50)) - 5) / 45)` | CRR Art. 153 |
| **Maturity Adjustment** | `(1 + (M-2.5) x b) / (1 - 1.5 x b)` where `b = (0.11852 - 0.05478 x ln(PD))^2` | CRR Art. 153 |
| **Expected Loss** | `PD x LGD x EAD` | PRA Rulebook Art. 158 (CRR Art. 158 omitted by SI 2021/1078) |
| **EAD (off-BS)** | `Drawn + Undrawn x CCF` | CRR Art. 111, 166 |
| **Effectively Secured** | `Adjusted Collateral Value / Overcollateralisation Ratio` | CRR Art. 230 |
| **Maturity Mismatch** | `(t - 0.25) / (T - 0.25)` | CRR Art. 238 |
| **Output Floor** | `max(RWA_IRB, floor% x RWA_SA)` | PRA PS1/26 |
| **SME SF (Blended)** | `[min(E,T) x 0.7619 + max(E-T,0) x 0.85] / E` | CRR Art. 501 |
