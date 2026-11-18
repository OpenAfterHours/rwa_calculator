# Product & Structure Review (2026-11-18)

A product-by-product review of how rwa-calc treats the banking products and credit
structures catalogued in two research references supplied by the project owner:

- *Banking products and credit structures — reference for a UK Basel 3.1 risk weighted
  asset calculator* (research cut-off 15 November 2026), and
- *Banking products and structures for the RWA calculator — research reference and
  implementation requirements* (15 November 2026), which includes a static assessment of
  this repository (findings G01–G10) and a 113-row product catalogue.

Neither document is regulation. Every finding below was therefore re-checked against the
primary text — PRA PS1/26 Appendix 1 (PRA2026/1, Basel 3.1, effective 1 January 2027) and
the onshored UK CRR as currently in force — and against the code as it stands, by running
the real pipeline where cheap.

## Method

1. **Eleven product families** were reviewed independently (table below). Each reviewer
   traced every catalogue product from the input schema through hierarchy, classification,
   CCF/EAD, CRM and the calculators, and classified it as supported, supported subject to
   input conditions, explicitly rejected, or silently misrouted.
2. **Each P0/P1 finding was adversarially verified** by a second agent instructed to refute
   it: re-read the code, re-run the probe, quote the rule, check the RWA direction and the
   existing plan. Verdicts (confirmed / rescoped / refuted) and corrected priorities are
   carried below; where the verifier rescoped a claim, its reading is authoritative.
3. Findings were de-duplicated across families into **actions** and given plan codes
   (`IMPLEMENTATION_PLAN.md`, section *Product & structure review — action list*).

Priorities: **P0** capital understated, exposure lost or unjustified relief reachable from
normal inputs; **P1** capital overstated, a common structure that cannot be represented, or a
missing data-quality control; **P2** specialist products, representation and documentation.

## Headline

- **160 findings** → **143 actions** after de-duplication: **40 P0**, **42 P1**, **59 P2**, 2 refuted.
- **Coverage register** (248 product rows across the families): 30 supported, 140 supported subject to input conditions, **70 silently misrouted**, 1 explicitly rejected, 7 not applicable.
- The dominant pattern is the one both references warn about: **a missing, unknown or
  ambiguous input silently produces a plausible, lower RWA** rather than a visible
  data-quality outcome — an accepted cancellable line documented as `committed=False`
  disappears, a project-finance phase is never read, a missing FX rate is treated as 1:1,
  an unrecognised CIU holding class takes 100%, an unidentified borrower income currency
  never triggers Art. 123B.
- **Regime-invariant assumptions that are not invariant**: the off-balance-sheet
  product→CCF map treated CRR Annex I and PS1/26 Table A1 as identical (they differ for
  documentary credits, shipping guarantees, customs and tax bonds); a CRR-only SA-CCR
  alpha and a Basel 3.1-only alpha carve-out were crossed.
- **Perimeter**: solo / sub-consolidated runs aggregated retail and SME thresholds over the
  scoped book only, and SME / large-FSE size tests used entity-own rather than consolidated
  figures.
- **Structural representation** (borrower schedules and caps, joint-and-several
  obligations, guarantee pools, external lien stacks, syndication shares) — the core of the
  second reference — is mostly P2 here: the engine's conventions are conservative or
  documented, so these are recorded as backlog with designs rather than defects.

Owner decisions respected: the netting perimeter remains the agreement (operator
decision 2026-09-04, findings NT-01/NT-02 downgraded to P2), and P1.292 (null
`is_qualifying_re`) remains blocked on P1.353 and its golden sign-off.

## Families reviewed

| Family | Findings | P0 | P1 | P2 |
|---|---|---|---|---|
| Commitments, CCFs and facility lifecycle | 12 | 3 | 4 | 5 |
| Shared / multi-borrower facilities, limits, MOF, syndication | 13 | 2 | 4 | 7 |
| On-balance-sheet netting and cash pooling | 8 | 0 | 3 | 5 |
| Collateral and security | 22 | 5 | 9 | 7 |
| Guarantees, credit derivatives and risk transfer | 14 | 3 | 4 | 6 |
| Retail banking and real estate | 21 | 5 | 9 | 7 |
| Trade finance, receivables, ABL and leasing | 10 | 3 | 2 | 5 |
| Derivatives (SA-CCR), CCPs, SFTs, settlement and CVA | 23 | 12 | 6 | 5 |
| Investments, specialised lending and specialist products | 12 | 6 | 0 | 6 |
| Party relationships, groups and data-quality controls | 16 | 3 | 8 | 5 |
| Regime selection, permissions, output floor | 9 | 2 | 3 | 4 |

## Action list

### P0 — capital understated, exposure lost or unjustified relief (40)

| Code | Action | Review IDs | Regime | Effect | Size | Status |
|---|---|---|---|---|---|---|
| P1.401 | SA-CCR alpha=1.0 NFC/pension carve-out applied under current CRR | CC-01 | CRR | RWA understated | S | In this PR |
| P1.402 | CCR collateral never read: c_net always 0 (posted collateral, VM, NICA, haircuts ignored) | CC-02 | Both | Either direction | M | In this PR |
| P1.403 | Margin-agreement terms dead; Art 274(3) cap and Art 275(3) multi-NS margin agreements missing | CC-03 | Both | Either direction | M | In this PR |
| P1.404 | SA-CCR IR add-on pools all currencies into one hedging set | CC-04 | Both | RWA understated | S | In this PR |
| P1.405 | CCR and SFT amounts never converted to reporting currency | CC-05 | Both | Either direction | M | In this PR |
| P1.406 | SA-CCR silently zeroes PFE for unknown/incomplete inputs; CCR/SFT validation dormant | CC-06 | Both | RWA understated | M | In this PR |
| P1.407 | Settlement-risk and default-fund own-funds rows routed to IRB and reduced by CRM | CC-08 | Both | RWA understated | S | In this PR |
| P1.408 | Failed trades: non-DvP Column 3 lost, buy-side DvP loss ignored, settlement_type unvalidated | CC-09 | Both | RWA understated | M | In this PR if time |
| P1.409 | Default-fund capital: non-QCCP K=DF+UC, QCCP DF_CCP denominator and floor, unfunded QCCP 0% | CC-10 | Both | RWA understated | S | In this PR |
| P1.410 | FCCM SFT engine always uses CRR haircut table under Basel 3.1 | CC-12 | Basel 3.1 | RWA understated | S | In this PR |
| P1.411 | FCCM: ineligible securities lent take HE=0; property/receivables/unknown collateral recognised | CC-13 | Both | RWA understated | S | In this PR |
| P1.412 | BA-CVA divides all netting sets by alpha 1.4 and uses post-CRM ead_final incl. SFTs | CC-15 | Basel 3.1 | RWA understated | S | In this PR |
| P1.413 | Collateral maturity_date ignored; maturity mismatch reads only residual_maturity_years | CL-02 | Both | RWA understated | S | In this PR |
| P1.414 | Loan-table collateral reduces SA-CCR derivative and SFT EAD again | CL-04, CC-07 | Both | RWA understated | M | In this PR |
| P1.415 | FIRB property collateral not reduced for prior or pari-passu claims | CL-05 | Both | RWA understated | M | Backlog |
| P1.416 | MORTGAGE-labelled loan with no property collateral gets real-estate weights | CL-08, RE-10 | Both | RWA understated | M | In this PR |
| P1.417 | Basel 3.1 FCM omits Hfx on non-financial collateral | CL-09 | Basel 3.1 | RWA understated | S | In this PR |
| P1.418 | committed=False silently deletes accepted unconditionally cancellable commitments (Doc B G01) | CM-01 | Basel 3.1 | RWA understated | S | In this PR |
| P1.419 | Facility headroom subtracts drawings in other currencies before FX conversion | CM-02, SF-01 | Both | Either direction | M | In this PR |
| P1.420 | B31 A-IRB grants own-estimate CCFs to issued items under a revolving facility | CM-03 | Basel 3.1 | RWA understated | S | In this PR |
| P1.421 | Art. 234 tranched protection (attachment_amount>0) gets RWSM substitution instead of Chapter 5 | GT-03 | Both | RWA understated | M | In this PR |
| P1.202 | No-restructuring CDS entered as percentage_covered escapes the Art. 233(2) 40% cut | GT-05 | Both | RWA understated | S | In this PR |
| P1.201 | Art. 233(2)(b) 60%-of-exposure cap missing for an over-sized no-restructuring CDS | GT-06 | Both | RWA understated | S | In this PR |
| P1.422 | B31 SA project-finance phase dropped: pre-operational 130% / high-quality 80% unreachable | IV-01 | Basel 3.1 | RWA understated | S | In this PR |
| P1.423 | B31 forces IPRE/HVCRE to slotting even for SA-only firms and Art. 148/150 SA permissions | IV-02, RG-01 | Basel 3.1 | RWA understated | S | In this PR |
| P1.424 | B31 Art. 133(5) 150% subordinated-debt weight misses specialised-lending rows | IV-03 | Basel 3.1 | RWA understated | S | In this PR |
| P1.425 | Securitisation allocator excludes exposures even when significant_risk_transfer=False | IV-04 | Both | RWA understated | S | In this PR |
| P1.426 | CIU look-through: unsupported underlying classes silently weighted 100% | IV-05 | Both | RWA understated | M | In this PR |
| P1.427 | CRR equity ignores is_significant_investment (Art. 48(4) 250%) | IV-06 | CRR | RWA understated | S | In this PR |
| P1.428 | SME and B31 LFSE size tests use entity-own, not consolidated-group figures | RC-05, RC-06 | Both | RWA understated | M | In this PR |
| P1.429 | Solo/sub-consolidated runs aggregate retail and SME-SF thresholds on scoped books only | RC-07, RG-02, RE-12 | Both | RWA understated | M | In this PR |
| P1.430 | Cross-table exposure_reference collisions merge rows and double CRM relief | RC-10 | Both | RWA understated | M | In this PR |
| P1.431 | Collateral-level is_adc/is_presold silently dropped; ADC loans priced as regulatory RE | RE-01 | Both | RWA understated | M | In this PR |
| P1.432 | B31 reclassifies non-regulatory natural-person retail to CORPORATE, losing Art. 123B multiplier | RE-03 | Basel 3.1 | RWA understated | M | In this PR |
| P1.433 | Null borrower income currency never triggers Art. 123B; 123B(3) fallback unimplemented and mis-cited | RE-05 | Basel 3.1 | RWA understated | M | In this PR |
| P1.292 | Null is_qualifying_re treated as qualifying (Art. 124A) | RE-16 | Basel 3.1 | RWA understated | M | Blocked (existing item) |
| P1.434 | Committed sub-facilities dropped under an uncommitted MOF/umbrella parent | SF-02 | Both | RWA understated | S | In this PR |
| P1.435 | Trade-LC flag broadcast per counterparty leaks onto every loan | TR-01 | Both | RWA understated | S | In this PR |
| P1.436 | Art 166A(5) IRB 40% purchased-receivables CCF applied to SA rows and A-IRB own estimates | TR-02 | Basel 3.1 | RWA understated | S | In this PR |
| P1.437 | Retail dilution risk priced with retail correlation, not Art 153(1) | TR-03 | Both | RWA understated | S | In this PR |

### P1 — capital overstated, common structure not representable, or missing control (42)

| Code | Action | Review IDs | Regime | Effect | Size | Status |
|---|---|---|---|---|---|---|
| P1.438 | QCCP 2%/4% pin applied to non-trade exposures; non-QCCP treated as institution not corporate | CC-11 | Both | RWA understated | S | In this PR |
| P1.439 | SFT netting set pools trades without master-netting eligibility; multi-counterparty sets merged | CC-14 | Both | RWA understated | M | In this PR |
| P1.440 | BA-CVA completeness: missing or partial CVA counterparty input silently gives no CVA charge | CC-16 | Basel 3.1 | RWA understated | S | In this PR |
| P1.441 | Specific wrong-way risk: netting-set split only; no jump-to-default EAD, LGD 100% never consumed | CC-18 | Both | RWA understated | M | Backlog |
| P1.442 | Engine-only risk types CCR_DERIVATIVE/CCR_SFT accepted on lending tables | CC-19 | Both | Either direction | S | In this PR |
| P1.443 | SA FCCM E* accepts any collateral type flagged is_eligible_financial_collateral | CL-01 | Both | RWA understated | S | In this PR |
| P1.444 | Duplicate collateral_reference undetected; same asset credited in full per row | CL-03 | Both | RWA understated | M | Backlog |
| P1.445 | FIRB recognises financial collateral the firm marked as failing Art. 207 | CL-06 | Both | RWA understated | M | Backlog |
| P1.446 | CRR SA real estate ignores is_qualifying_re=False | CL-07, RE-09 | CRR | RWA understated | S | In this PR |
| P1.447 | B31 Art. 124H(3) whole-loan CRE overwrites the 124C LTV and drops the 124I(3) junior weights | CL-10 | Basel 3.1 | RWA understated | S | In this PR |
| P1.448 | Canonical collateral type 'bond' is not financial collateral on the FIRB path | CL-11 | Both | RWA overstated | S | In this PR |
| P1.449 | Single prior_charge_ltv cannot carry the B31 claim stack; loan-split share double-counts it | CL-12, RE-08, SF-11 | Basel 3.1 | RWA overstated | L | Backlog |
| P1.450 | Real-estate attributes ignore collateral_links | CL-13 | Both | RWA overstated | M | Backlog |
| P1.451 | Null collateral currency: no FX conversion and no Hfx, silently | CL-14 | Both | Either direction | S | In this PR |
| P1.452 | MOF sub-limit rows inherit the parent's CCF modifiers instead of their own | CM-06, SF-08 | Both | Either direction | M | Backlog |
| P1.453 | Regime-invariant product map: shipping/customs/tax bonds and unsecured documentary credits wrong under CRR | CM-07, TR-04 | CRR | RWA understated | M | In this PR |
| P1.454 | risk_type guidance mis-maps SBLCs, commitments and performance bonds | CM-08 | Both | RWA understated | S | In this PR |
| P1.455 | Committed facility with null limit silently yields no commitment exposure | CM-11, SF-12 | Both | RWA understated | S | In this PR |
| P1.456 | Aggregate guarantee cap repeated across beneficiary rows is double-counted; no shared-cap representation (G08) | GT-01 | Both | RWA understated | M | In this PR |
| P1.457 | Percentage-plus-amount-cap guarantee: amount_covered overrides percentage instead of min() | GT-02 | Both | RWA understated | S | In this PR |
| P1.458 | Multi-guarantor non-beneficial redistribution is half-applied; RWEA can exceed unprotected | GT-09 | Both | RWA overstated | M | Backlog |
| P1.459 | Collateral plus guarantee: cover fraction taken on the gross exposure wastes the guarantee | GT-10 | Both | RWA overstated | M | Backlog |
| P1.460 | Demand deposit with null maturity nets fully against term loans | NT-03 | Both | RWA understated | S | In this PR |
| P1.461 | Output-floor S-TREA ignores netting on IRB/slotting rows | NT-05, RG-04 | Basel 3.1 | RWA overstated | M | Backlog |
| P1.462 | FCSM election: netted deposits skip maturity mismatch; B31 routes netting via FCSM | NT-06 | Both | RWA understated | M | In this PR if time |
| P1.463 | Child mapped to >1 facility consumes every parent's headroom | RC-01, RC-02, SF-03 | Both | Either direction | S | In this PR |
| P1.464 | Unrated subsidiary silently inherits parent's internal PD and model | RC-04 | Both | RWA understated | S | Backlog |
| P1.465 | Connected-client grouping single-level, first-membership-wins, no closure | RC-08 | Both | RWA understated | M | Backlog |
| P1.466 | Missing FX rate silently treated as 1:1 | RC-11 | Both | Either direction | S | In this PR |
| P1.467 | Null entity_type silently classified 'other' at 100% | RC-12 | Both | Either direction | S | In this PR |
| P1.468 | B31 SME test uses assets fallback and strict < not in PS1/26 definition | RC-16 | Basel 3.1 | Either direction | S | In this PR |
| P1.469 | Art. 124K(2) 100% residential ADC unreachable; equity-at-risk limb unrepresented | RE-02 | Basel 3.1 | RWA overstated | S | In this PR |
| P1.470 | 0.2% retail granularity limb enforced by default but absent from PS1/26 Art. 123A | RE-04 | Basel 3.1 | RWA overstated | S | In this PR |
| P1.471 | Mortgage-class rows with several properties take arbitrary first collateral row; mixed-use never split | RE-07 | Both | Either direction | L | Backlog |
| P1.472 | Undrawn UK residential mortgage commitments get 40% unless manually flagged | RE-14 | Basel 3.1 | RWA understated | S | In this PR |
| P1.262 | RRE exposures with no Art. 124E exception (e.g. corporates) default to not-materially-dependent | RE-15 | Basel 3.1 | RWA understated | M | In this PR if time |
| P1.263 | CRR Art. 126 50% gate inverted; owner-occupied CRE gets 100% | RE-17 | CRR | Either direction | M | In this PR |
| P1.473 | No primary-residence carrier; landlord's own home re-routed to Art. 124G | RE-18 | Basel 3.1 | RWA overstated | S | Backlog |
| P1.474 | S-TREA uses A-IRB own-estimate EAD instead of SA Art. 111 exposure value | RG-03 | Basel 3.1 | Either direction | L | Backlog |
| P1.475 | One flag conflates Art. 122(6) IG permission with Art. 122(8)(b) floor-only election | RG-06 | Basel 3.1 | Either direction | M | Backlog |
| P1.476 | Share candidates dilute facility-level collateral/guarantees; losers' portions discarded | SF-07 | Both | RWA overstated | M | Backlog |
| P1.477 | B31 Art 162(3)(e) one-day M floor for self-liquidating trade disabled | TR-05 | Basel 3.1 | RWA overstated | S | In this PR |

### P2 — specialist products, representation and documentation (59)

| Code | Action | Review IDs | Regime | Effect | Size | Status |
|---|---|---|---|---|---|---|
| P7.9 | Current-UK CVA risk charge (Art 384 standardised) not implemented | CC-17 | CRR | RWA understated | M | Backlog |
| P7.10 | IRB effective maturity of SA-CCR netting sets uses longest trade maturity | CC-20 | Both | RWA overstated | S | Backlog |
| P7.11 | Art 274(2A) alpha add-on recomputed on current RC+PFE for whole netting set | CC-21 | Basel 3.1 | Either direction | S | Backlog |
| P7.12 | SFT input lacks sub-type/direction and link to lent security holding | CC-22 | Both | RWA understated | M | Backlog |
| P7.13 | CCP cap and commodity hedging-set granularity gaps | CC-23 | Both | RWA overstated | M | Backlog |
| P7.14 | valuation_date never consumed: no revaluation-staleness control | CL-15 | Both | Either direction | M | Backlog |
| P7.15 | No cross-table conservation between loan, CCR and SFT collateral | CL-16 | Both | RWA understated | M | Backlog |
| P7.16 | Link allocator sizes slices in market value against EAD; ignores haircuts and eligibility | CL-17 | Both | RWA overstated | L | Backlog |
| P7.17 | FIRB third-party deposits give no benefit (CRM017 deferral) | CL-18 | Both | RWA overstated | M | Backlog |
| P7.18 | No CIU / fund-unit collateral type | CL-19 | Both | RWA overstated | M | Backlog |
| P7.19 | Other funded protection has no Art. 212 attestation input | CL-20 | Both | RWA understated | S | Backlog |
| P7.20 | issuer_type 'institution' rejected by DQ006 although the engine routes it; Art. 197(4) unsupported | CL-21 | Both | RWA overstated | S | Backlog |
| P7.21 | Declared original_maturity_years never reaches the CRR Annex I maturity split | CM-04 | CRR | Either direction | S | Backlog |
| P7.22 | Non-revolving, delayed-draw and expired facilities recount repaid or lapsed headroom | CM-05, SF-10 | Both | RWA overstated | M | Backlog |
| P7.23 | CRR F-IRB: MR/OC contingents default to issued-item ladder 50% instead of 166(8)(d) 75% | CM-09 | CRR | RWA understated | S | In this PR if time |
| P7.24 | CRR F-IRB Art. 166(9) commitment-on-commitment lower-of missing; 166(9) mis-cited | CM-10 | CRR | RWA overstated | S | Backlog |
| P7.25 | Documented obs_product synonyms raise false DQ006 | CM-12 | Both | No RWA effect | S | In this PR if time |
| P7.26 | Deductible / payment-threshold protection cannot be represented; B31 says it shall be tranched | GT-04 | Basel 3.1 | RWA understated | M | Backlog |
| P7.27 | guarantee_type is never read: letters of comfort and keepwells get full substitution | GT-07 | Both | RWA understated | S | In this PR |
| P7.28 | Unknown eligibility inputs (maturity, cancellability, currency) give silent full recognition | GT-08 | Both | RWA understated | S | In this PR if time |
| P7.29 | Art. 214 counter-guarantees cannot be represented; counter-guarantee rows silently dropped | GT-11 | Both | RWA overstated | M | Backlog |
| P7.30 | PS1/26 Art. 216(3) corporate restructuring derogation not implemented | GT-13 | Basel 3.1 | RWA overstated | S | Backlog |
| P5.87 | Credit-insurer guarantors: no insurer entity type and no guidance; financial_institution mis-entry | GT-14 | Both | Either direction | S | Backlog |
| P7.31 | CIU look-through / mandate-based RW not capped at 1,250% fall-back | IV-07 | Basel 3.1 | RWA overstated | S | Backlog |
| P7.32 | No input route for securitisation positions: tranches, ABCP liquidity, warehouse lines go silently corporate | IV-08 | Both | Either direction | M | Backlog |
| P7.33 | Missing slotting category silently treated as 'satisfactory' 115% | IV-09 | Both | Either direction | S | In this PR if time |
| P7.34 | Prudential-regulation status of FSE counterparties not representable (fund finance) | IV-10 | Both | Either direction | M | Backlog |
| P7.35 | Long-term issue-specific ratings cannot attach to an exposure | IV-11 | Both | Either direction | M | Backlog |
| P7.36 | No carrier for Art. 48(4) 250% threshold-exempt deferred tax assets | IV-12 | Both | RWA understated | S | Backlog |
| P7.37 | Cross-counterparty netting granted on agreement-reference equality alone (G05/T41) | NT-01 | Both | RWA understated | M | Backlog |
| P7.38 | Null-counterparty deposit still nets under shared reference (T43) | NT-02 | Both | RWA understated | S | Backlog |
| P7.39 | A-IRB and slotting exposures get zero on-BS netting relief | NT-04 | Basel 3.1 | RWA overstated | M | Backlog |
| P7.40 | Deposit under a facility enlarges the undrawn commitment (net-limit assumption) | NT-07 | Both | RWA overstated | S | Backlog |
| P7.41 | B31 whole-loan CRE LTV numerator is net of netting (not run) | NT-08 | Basel 3.1 | RWA understated | S | Backlog |
| P7.42 | Org JV/multi-parent resolved by row order; cycles silent | RC-03 | Both | Either direction | M | Backlog |
| P7.43 | Joint-and-several / co-borrower obligations not representable | RC-09 | Both | RWA understated | M | Backlog |
| P7.44 | Mapping tables lack referential checks; null child_type silently ignored | RC-13 | Both | RWA overstated | M | Backlog |
| P7.45 | Duplicate book_code mapping resolves last-wins | RC-14 | Both | Either direction | S | Backlog |
| P5.88 | Docs misdescribe inheritance traversal, lending-group purposes, SME metric | RC-15 | Both | No RWA effect | S | Backlog |
| P7.46 | Art. 123B scope/representation: no natural-person gate, no permitted draw currencies, hedge carriers loan-only | RE-06 | Basel 3.1 | Either direction | M | Backlog |
| P7.47 | Valuation date/type never read; stale or indexed valuations keep preferential RE weights | RE-11 | Both | Either direction | M | Backlog |
| P7.48 | Retail-threshold residential exclusion uses capped collateral value, not the RRE exposure | RE-13 | Both | Either direction | S | Backlog |
| P7.49 | Self-build lending unrepresentable; non-self-build NP construction treated as regulatory RE | RE-19 | Basel 3.1 | Either direction | M | Backlog |
| P7.50 | CRR ignores explicit is_managed_as_retail=False (Art. 123(b)) | RE-20 | CRR | RWA understated | M | Backlog |
| P7.51 | retail_mortgage class includes CRE-secured NP loans; IRB retail floors keyed on class | RE-21 | Basel 3.1 | Either direction | S | Backlog |
| P7.52 | No control when selected regime is not in force at the reporting date | RG-05 | Both | No RWA effect | S | Backlog |
| P7.53 | Slotting/SA permission matches only via a rating model_id; unrated SL silently SA | RG-07 | Both | Either direction | S | Backlog |
| P7.54 | FSE status has no unknown state; missing flag keeps A-IRB | RG-08 | Basel 3.1 | Either direction | S | Backlog |
| P5.89 | B31 supporting-factor removal cited to non-existent PS1/26 Art. 501 | RG-09 | Basel 3.1 | No RWA effect | S | Backlog |
| P7.55 | No riskiest-member election inside an MOF sub-facility with several borrowers | SF-04 | Both | RWA understated | M | Backlog |
| P7.56 | Eligible borrowers with no drawings cannot be share members; no borrower schedule or role input | SF-05 | Both | RWA understated | L | Backlog |
| P7.57 | Borrower caps not representable; every candidate carries the full headroom | SF-06 | Both | RWA overstated | L | Backlog |
| P7.58 | MOF residual emitted even when only sublimit products are permitted | SF-09 | Both | RWA overstated | S | Backlog |
| P5.90 | No syndication/participation inputs and no documented pre-scaling convention | SF-13 | Both | Either direction | S | Backlog |
| P7.59 | Funded trade-finance loans cannot carry the trade flag | TR-06 | Basel 3.1 | RWA overstated | M | Backlog |
| P7.60 | Missing obs_product keys for common trade/receivables instruments | TR-07 | Both | No RWA effect | S | In this PR |
| P7.61 | Dilution-risk M ignores Art 157(4) | TR-08 | Both | RWA overstated | S | Backlog |
| P7.62 | Dilution leg double-counted; default-risk EAD not reduced | TR-09 | Both | RWA overstated | M | Backlog |
| P5.91 | B31 'less than one year' trade boundary coded <=1.0; citation slips | TR-10 | Basel 3.1 | RWA understated | S | In this PR |

## Action detail (P0 and P1)

### P0 — capital understated, exposure lost or unjustified relief

#### P1.401 — SA-CCR alpha=1.0 NFC/pension carve-out applied under current CRR

*Review IDs:* CC-01 · *Regime:* CRR · *Effect:* RWA understated · *Size:* S · *Status:* In this PR

- *Current:* packs/common.py:72-78 regime-invariant carve-out; ccr/pipeline_adapter.py:423,670-715 sets alpha 1.0 under CRR. Probe: CRR NFC IRS alpha_applied 1.0, EAD 2.219m vs 3.107m. Pinned by test_ccr_alpha_carveout.py (CRR config).
- *Required:* Current PRA CCR Part Art 274(2): 'alpha = 1.4.' PS1/26 Annex R Art 274(2) adds ', unless the counterparty is a non-financial counterparty...' as new (underlined) text from 1-1-2027.
- *Fix:* Cited pack Feature sa_ccr_alpha_nfc_carve_out_applicable (crr False, b31 True) read in ccr_rows_to_exposures; _attach_alpha_applied returns 1.4 when off; move P8.28 test to B31 date and add CRR leg.
- *Verification (confirmed):* The PRA CCR Part Art. 274(2) in force says only α=1.4. PS1/26 Art. 274(2) adds the NFC/pension carve-out from 1-1-2027. No regime gate in _attach_alpha_applied. A full pipeline run under CRR 2026-03-31 gave an NFC IRS alpha_applied 1.0, EAD 2.219m vs 3.107m. test_ccr_alpha_carveout.py pins it under a CRR config.

#### P1.402 — CCR collateral never read: c_net always 0 (posted collateral, VM, NICA, haircuts ignored)

*Review IDs:* CC-02 · *Regime:* Both · *Effect:* Either direction · *Size:* M · *Status:* In this PR

- *Current:* ccr/pipeline_adapter.py:366 guards on 'collateral_value', absent from CCR_COLLATERAL_SCHEMA (schemas.py:1772-1795, declares market_value). Probe: posted 1.5m cash, V=-1m gives EAD 41,802 vs 1,006,994; received collateral ignored (overstated).
- *Required:* CCR Part Art 275(1) RC=max{CMV-NICA,0}; Art 276(1)(c) posted collateral negative sign; 276(1)(d) volatility-adjusted per Art 223; 276(1)(g) segregated excluded; 276(2) posted C(1+HC+Hfx). Unchanged by PS1/26.
- *Fix:* New engine/ccr/collateral.py computing signed, haircut (regime table) VM/NICA per NS from market_value/is_posted_by_firm/is_segregated; add collateral_role vm/im; delete dead guard.
- *Verification (rescoped):* Confirmed: the guard reads 'collateral_value', which the loaded schema never has, so c_net is always 0. Direction is mixed, not purely understated. Received collateral/VM is ignored, so EAD is overstated in the common lender case. Posted collateral is ignored, so EAD is understated (probe 41,802 vs 1,006,994). P0 kept for the posted leg.

#### P1.403 — Margin-agreement terms dead; Art 274(3) cap and Art 275(3) multi-NS margin agreements missing

*Review IDs:* CC-03 · *Regime:* Both · *Effect:* Either direction · *Size:* M · *Status:* In this PR

- *Current:* ccr/rc.py:44-79 reads TH/MTA/NICA from netting set only; MARGIN_AGREEMENT_SCHEMA terms unused; number_of_trades user-supplied (maturity_factor.py:186). Probe: MA-only terms EAD 1.49m; NS terms 14.79m; correct cap 1.71m.
- *Required:* CCR Part Art 274(3) margined exposure 'shall be capped at the exposure value of the same netting set not subject to any form of margin agreement'; Art 275(2)/(3); Art 278(2); CRR Art 285(3)(a) >5000 trades MPOR 20 BD.
- *Fix:* Coalesce NS and MA terms (warn on conflict); compute margined and unmargined EAD, take min; implement RC_MA for NS sharing margin_agreement_id; number_of_trades = max(input, counted trades).
- *Verification (confirmed):* MARGIN_AGREEMENT_SCHEMA TH/MTA/NICA/mpor_days have no reader. With terms on the MA only, they count as 0 (max_horizontal ignores null), giving 1.49m vs a correct 1.71m (understated). There is no Art. 274(3) unmargined cap (NS terms 14.79m, overstated). number_of_trades is input only. Mixed direction; P0 justified by the understated leg.

#### P1.404 — SA-CCR IR add-on pools all currencies into one hedging set

*Review IDs:* CC-04 · *Regime:* Both · *Effect:* RWA understated · *Size:* S · *Status:* In this PR

- *Current:* ccr/pfe.py:242-283 groups IR effective notionals by (netting_set, asset_class, maturity_bucket) without currency. Probe: GBP 100m long + USD 100m short 5y in one NS gives add-on 0, EAD 0.
- *Required:* CCR Part Art 277a(1)(a): IR trades in same hedging set 'only where their primary risk driver ... is denominated in the same currency'; inflation in separate hedging sets; Art 280a(1) sum over hedging sets.
- *Fix:* Group IR by currency (plus is_inflation flag) hedging set, compute three-bucket EffNot per hedging set, sum per-currency add-ons. Test: GBP+USD(0.8) add-on 3,947,061; EAD 5,525,886.
- *Verification (confirmed):* pfe.py groups IR effective notionals by (NS, asset_class, bucket) with no currency key. Probe: GBP 100m long + USD 100m short gives add-on 0, EAD 0. PRA Art. 277a(1)(a) allows one hedging set only for the same currency. Pooling can only understate or tie. The test value depends on CC-05.

#### P1.405 — CCR and SFT amounts never converted to reporting currency

*Review IDs:* CC-05 · *Regime:* Both · *Effect:* Either direction · *Size:* M · *Status:* In this PR

- *Current:* ccr/adjusted_notional.py:57-108,225-386 and mtm_value unconverted; synthetic rows minted after FXConverter (pipeline_adapter.py:458-462; sft/fccm.py:420-430). Probe: JPY 10bn IRS EAD 419m 'GBP' vs 2.10m; USD repo E* 100m in USD.
- *Required:* CCR Part Art 279b(2): adjusted notional converted 'into the institution's reporting currency at the prevailing spot exchange rate'; RC/NICA (Art 275, 276) on one currency basis.
- *Fix:* Convert notional, market_price, mtm_value, collateral and SFT notional to base_currency via run FX table at adapter entry; keep original currency for hedging sets/FX haircuts; missing rate -> DQ error.
- *Verification (confirmed):* Only FX-class notionals are converted. FXConverter runs before the CCR/SFT stages, and the SFT stage has no FX. A pipeline run put a JPY 10bn IRS EAD of 419m (JPY) into the GBP totals. PRA Art. 279b(2) requires spot conversion to reporting currency. Direction is mixed by currency.

#### P1.406 — SA-CCR silently zeroes PFE for unknown/incomplete inputs; CCR/SFT validation dormant

*Review IDs:* CC-06 · *Regime:* Both · *Effect:* RWA understated · *Size:* M · *Status:* In this PR

- *Current:* No error and add-on 0 for asset_class 'inflation', null credit_quality, null commodity_type, missing FX rate; orphan trades dropped; unknown NS counterparty -> 'other' 100%. validation.py:464-470 keys 'ccr.trades' vs schemas.py:2917 'trades'.
- *Required:* CCR Part Art 277(1) institutions 'shall map each transaction ... to one of the following risk categories'; Art 278(1) include add-on where a transaction is mapped; Art 280f other risks category.
- *Fix:* Register ccr/sft table keys in COLUMN_VALUE_CONSTRAINTS (asset_class, settlement_type, credit_quality, commodity_type); declare FKs; conservative engine fallbacks (Art 280f other, highest credit SF, OTHER commodity) plus errors.
- *Verification (confirmed):* Re-run probes, all with zero errors: null/'BBB' credit_quality, null commodity_type, 'Interest_Rate', and a missing FX rate each give add-on 0; orphan trades are dropped. COLUMN_VALUE_CONSTRAINTS keys 'trades'/'sft_trades' never match the registered 'ccr.trades'/'sft.trades' and self-declare as dormant. Nullable columns make this a normal-input path.

#### P1.407 — Settlement-risk and default-fund own-funds rows routed to IRB and reduced by CRM

*Review IDs:* CC-08 · *Regime:* Both · *Effect:* RWA understated · *Size:* S · *Status:* In this PR

- *Current:* stages/ccr.py:170-262 mints ft__/dfc__ rows; 12.5 pin only in SA chain (sa/risk_weights.py:1124-1129). Probe: IRB-permissioned CP FT1 RWA 45,764 (CRR) vs 625,000; CP-level cash collateral -> 0; sovereign guarantee -> 50,000.
- *Required:* CRR Art 378: price difference x factor is the 'own funds requirement for settlement risk'; Art 92(3)(ca); CCR Part Art 308(3)/309(2) RWEA = own funds x 12.5 — no CRM or IRB formula.
- *Fix:* classify/approach.py: force SA for SETTLEMENT_FAILED_TRADE and CCR_DEFAULT_FUND; exclude from collateral/guarantee/provision/supporting factors; longer term emit as own-funds lines like cva_rwa.
- *Verification (confirmed):* Re-run probes: FT1 with own funds 50,000 is routed F-IRB, RWA 45,764 (CRR) / 265,881 (B31) vs 625,000. CP-level cash takes it to RWA 0; a sovereign guarantee gives 50,000. Only cp_entity_type=='ccp' forces SA, so dfc rows escape but ft rows do not. Art. 378 and Art. 308(3)/309(2) define own-funds amounts, not credit exposures.

#### P1.408 — Failed trades: non-DvP Column 3 lost, buy-side DvP loss ignored, settlement_type unvalidated

*Review IDs:* CC-09 · *Regime:* Both · *Effect:* RWA understated · *Size:* M · *Status:* In this PR if time

- *Current:* ccr/failed_trades.py:124-135 price diff max(0, agreed-MV) seller only; :155-186 non-DvP <5 days -> 0 labelled dvp_pre_t5; 'DVP' -> 0. Probe: buy-side FT2, non-DvP 2-day FT3, 'DVP' FT5 all 0.
- *Required:* CRR Art 378 price difference 'where the difference could involve a loss'; Art 379(1) Table 2 Column 3 'From first contractual payment or delivery leg up to four days after second ... Treat as an exposure'.
- *Fix:* Add is_purchase/direction column, loss by side; non-DvP Column 3 emits ordinary credit exposure row (SA/IRB per Art 379(2)); constrain settlement_type. Test FT2 RWA 625,000; FT3 CQS2 inst 500,000 CRR / 300,000 B31.
- *Verification (confirmed):* Buy-side loss is lost (MV>agreed gives 0; MV<agreed is overcharged). Non-DvP Column 3 gives 0 and is mislabelled; 'DVP' silently gives 0. Column 3 is documented out-of-scope with no ticket. The finding's FT3 test values are wrong: short-term institution CQS2 is 20% in both regimes, so RWA is 200,000, not 500k/300k.

#### P1.409 — Default-fund capital: non-QCCP K=DF+UC, QCCP DF_CCP denominator and floor, unfunded QCCP 0%

*Review IDs:* CC-10 · *Regime:* Both · *Effect:* RWA understated · *Size:* S · *Status:* In this PR

- *Current:* ccr/default_fund.py:109-112 K=K_CCP*DF_i/DF_CM for every branch; no DF_CCP column; pinned by test_ccr_b2_b4_default_fund.py:19-21. Non-QCCP DF 10m gives RWEA 12.5m vs 125m.
- *Required:* CCR Part Art 308(2) K_i=max{K_CCP*DF_i/(DF_CCP+DF_CM), 8%*2%*DF_i}; Art 309(1) 'K = DF + UC'; Art 310 0% for unfunded QCCP contributions.
- *Fix:* Add df_ccp_prefunded; implement 308(2) with cited pack floor scalars; non-QCCP K=DF or UC; QCCP unfunded K=0; fix pinning test. QCCP example RWEA 4,166,667 (engine 5,000,000).
- *Verification (confirmed):* Probe: non-QCCP DF 10m gives RWEA 12.5m vs (DF+UC)x12.5 = 125m (Art. 309(1)). On QCCPs: the missing DF_CCP overstates (5m vs 4.17m), the missing 0.16% floor understates, and unfunded contributions are charged where Art. 310 gives 0%. Existing open P8.26 states the same wrong Art. 309 reading; re-scope it rather than file anew.

#### P1.410 — FCCM SFT engine always uses CRR haircut table under Basel 3.1

*Review IDs:* CC-12 · *Regime:* Basel 3.1 · *Effect:* RWA understated · *Size:* S · *Status:* In this PR

- *Current:* sft/fccm.py:603-613 hardcodes is_basel_3_1=False for HE and HC. Probe: cash lent 100m vs 120m equity gives E* 1,213,203 in both regimes.
- *Required:* PS1/26 Art 224 Table 1 (five maturity bands, revised equity/gold haircuts) applied via Art 223(1) volatility adjustments.
- *Fix:* Pass is_basel_3_1 from run pack Feature collateral_haircut_maturity_bands_revised into _lookup_haircut_unscaled. Test B31 E* = 5,455,844.12; CRR stays 1,213,203.44.
- *Verification (confirmed):* fccm.py hard-codes is_basel_3_1=False although stages/sft.py passes the run pack. Re-run probe: cash 100m vs 120m equity gives E* 1,213,203 in both regimes. The B31 pack has equity 20/30%, gold 20% and five maturity bands per PS1/26 Art. 224.

#### P1.411 — FCCM: ineligible securities lent take HE=0; property/receivables/unknown collateral recognised

*Review IDs:* CC-13 · *Regime:* Both · *Effect:* RWA understated · *Size:* S · *Status:* In this PR

- *Current:* sft/fccm.py:636-638 HE 0 when security ineligible; crm/haircut_tables.py:515-523 0% for real_estate/receivables, 40% for unknown types. Probe: unrated bond lent 100m vs 95m cash E* 5m; property collateral E* 0.
- *Required:* CRR & PS1/26 Art 224(4) non-eligible securities lent take the non-main-index equity haircut; FCCM values financial collateral only (Art 223(1); PS1/26 Art 220(2) eligible per Arts 197/198).
- *Fix:* Exposure side None -> equity_other haircut; collateral side whitelist Art 197/198 types, zero recognition plus warning otherwise. Test E* 22,677,670 CRR / 26,213,203 B31; property case 100m.
- *Verification (confirmed):* An ineligible security lent takes HE 0 (unrated corp / CQS5 govt bond: E* 5m). CRR and PS1/26 Art. 224(4) require the non-main-index equity haircut. Property/receivables collateral is fully recognised (E* 0), though Art. 223(1) is financial collateral only. HE is the material leg; the B31 value needs CC-12; CIU collateral overlaps P1.199.

#### P1.412 — BA-CVA divides all netting sets by alpha 1.4 and uses post-CRM ead_final incl. SFTs

*Review IDs:* CC-15 · *Regime:* Basel 3.1 · *Effect:* RWA understated · *Size:* S · *Status:* In this PR

- *Current:* cva/ba_cva.py:129 alpha=sa_ccr_alpha (1.4) for every NS; EAD = ead_final of ccr__ rows (stages/aggregate.py:66,150) incl. CCR_SFT. Probe NFC EAD 10m M5 OTHER/IG RWEA 12,837,455.
- *Required:* PS1/26 CVA Part 4.3 'alpha = the value of alpha as specified in the Counterparty Credit Risk (CRR) Part' (1 for NFC/pension); SFTs only if fair-valued and CVA risk material.
- *Fix:* Carry alpha_applied and ead_ccr on synthetic rows and use per NS; restrict to CCR_DERIVATIVE unless SFT in-scope flag. Test NFC RWEA 17,972,436.
- *Verification (confirmed):* ba_cva.py divides every counterparty by sa_ccr_alpha 1.4. PS1/26 CVA Part 4.3 says 'α = the value of α as specified in the CCR Part' (1 for NFC/pension), so NFC SCVA is understated by 28.6%. It uses post-CRM ead_final where 4.3 wants the CCR EAD. SFT rows share the ccr__ prefix and are included.

#### P1.413 — Collateral maturity_date ignored; maturity mismatch reads only residual_maturity_years

*Review IDs:* CL-02 · *Regime:* Both · *Effect:* RWA understated · *Size:* S · *Status:* In this PR

- *Current:* haircuts.py:751 fill_null(10.0) on residual_maturity_years, haircuts.py:492 same; 1y deposit vs 5y loan with maturity_date only: SA RWA 0 (should be 84,208 CRR / 84,211 B31).
- *Required:* CRR/PS1-26 Art. 237(1)/238(1): protection maturity = time to earliest termination date; mismatch adjustment must apply.
- *Fix:* Derive residual_maturity_years from maturity_date via exact_fractional_years_expr (guarantee twin precedent, guarantees.py:1443) in HaircutCalculator; warn on conflict or absence.
- *Verification (confirmed):* Re-ran t9: a cash deposit with only maturity_date gives SA EAD 0 and FIRB LGD 0. With residual 1.0 it gives 84,208 and CRM002. Nothing derives residual_maturity_years from maturity_date; the mismatch path fills null with 10y. PS1/26 Art. 238(1) verbatim matches. The guarantee path's helper exists (guarantees.py:1443).

#### P1.414 — Loan-table collateral reduces SA-CCR derivative and SFT EAD again

*Review IDs:* CL-04, CC-07 · *Regime:* Both · *Effect:* RWA understated · *Size:* M · *Status:* In this PR

- **CL-04** *Current:* collateral.py:901-910,944-960,1216-1224 pool counterparty-level collateral over CCR rows; CCR-A1 EAD 5,480,018 to 0 (CRR), 5,044,928 to 0 (B31); SFT A12 also zeroed.
- *Required:* CRR Art. 111(2), 223(6); PS1/26 Art. 111(2)-(3), 191A(4): derivative collateral recognised only inside the CCR method; SFT set value computed once.
- *Fix:* Exclude rows with ccr_method set from collateral pools and pro-rata denominators; CRM024 warning when a loan-table pledge targets a counterparty with CCR rows.
- *Verification (confirmed):* Re-ran t6: CCR-A1 EAD falls from 5,480,018 to 0 (CRR) and from 5,044,928 to 0 (B31), and there is no CCR exclusion in engine/crm. Rule holds, but the correct CRR citation is Art. 223(5A), not 223(6). PS1/26 Art. 191A(4) verbatim limits CRM articles on derivative funded protection to cross-referenced use.
- **CC-07** *Current:* crm/collateral.py:876-905 pro-rates counterparty-level collateral over ccr__ rows; no risk_type exclusion in engine/crm. Probe: 3m cash CP-level collateral cut derivative EAD 3.16m to 0.88m (CRR); 10m wipes it to 0.
- *Required:* CRR & PS1/26 Art 223(5A): SA-CCR firms take collateral into account per CCR Part Sections 3-5; PS1/26 Art 191A(4): Arts 192-239 apply to derivative funded protection only via cross-reference.
- *Fix:* Exclude CCR_DERIVATIVE, CCR_SFT, SETTLEMENT_FAILED_TRADE, CCR_DEFAULT_FUND rows from funded collateral allocation and direct links (warn); keep guarantees for CCR rows; add collateral_reference to SFT/CCR collateral with duplicate check.
- *Verification (rescoped):* FCCM on ccr__ rows breaches Art. 223(5A)/191A(4), but the collateral is shared pro rata, not double-counted (721k+2,279k=3m). If the pledge secures all obligations (the engine's semantics), SA-CCR C gives more relief, so the engine is conservative. It understates only for lending-only pledges. The own-funds-row CRM belongs to CC-08.

#### P1.415 — FIRB property collateral not reduced for prior or pari-passu claims

*Review IDs:* CL-05 · *Regime:* Both · *Effect:* RWA understated · *Size:* M · *Status:* Backlog

- *Current:* prior_charge_ltv read only by SA (splitter.py:407); crm/ never reads it. Loan 50k, MV 100k, prior 60k: LGD 0.35 CRR / 0.20 B31, same as no prior claim.
- *Required:* PS1/26 Art. 229(1)(b)-(c): reduce value by P/(1-HC-Hfx), pro-rata for pari passu; CRR Art. 229(1): 'take account of any prior claims'.
- *Fix:* In apply_haircuts reduce real-estate value by prior claims (B31 gross-up via cited pack Feature); expected B31 RWA 41,068 (LGD 0.40), CRR 48,628 (LGD 0.3929).
- *Verification (confirmed):* Nothing in engine/crm reads prior_charge_ltv. Re-ran t11: prior 0.0 and 0.6 give the same result (CRR LGD 0.35 / 43,323; B31 0.20 / 28,750). PS1/26 Art. 229(1)(b)-(c) P/(1-HC-Hfx) and CRR 229(1) 'take account of any prior claims' both read verbatim. The input is already populated on the same row for SA.

#### P1.416 — MORTGAGE-labelled loan with no property collateral gets real-estate weights

*Review IDs:* CL-08, RE-10 · *Regime:* Both · *Effect:* RWA understated · *Size:* M · *Status:* In this PR

- **CL-08** *Current:* attributes.py:633-647 is_mortgage from product_type alone; risk_weights.py:810 CRR ltv fill_null(0.0) gives 35% (RWA 35,000 vs 75,000); B31 0.56 vs 1.00.
- *Required:* CRR Art. 125(1) 'fully and completely secured by mortgages'; PS1/26 Art. 124A(1)(a) 'secured by immovable property'.
- *Fix:* RE weight branch requires property collateral evidence or a populated LTV; otherwise counterparty class plus warning; CRR null LTV fills 1.0.
- *Verification (rescoped):* Confirmed (t13: 35,000 vs 75,000 CRR, no warning), and the defect is broader. New probe v08b: with RE collateral present but property_ltv null, LTV is never derived from EAD/value. Loan 150k on a 100k property gives CRR 0.35 (52,500 vs 98,000) and B31 0.56 (84,000 vs 106,000). Fix: derive LTV, do not fill CRR null with 0.0, and require security evidence.
- **RE-10** *Current:* risk_weights.py:810 ltv.fill_null(0.0)<=0.80 -> 35%; B31 fill_null(1.0) (b31_risk_weight_tables.py:895-905); market_value unused for LTV, no DQ error. Measured null LTV -> CRR 0.35.
- *Required:* CRR Art. 125(2)(d): 35% only on part not exceeding 80% of market value; PS1/26 Art. 124C(1): loan amount divided by property value.
- *Fix:* Derive ltv=(drawn+undrawn committed)/sum property value when property_ltv null; if no value use 1.0 plus DQ warning both regimes. Test 95k/100k: CRR 0.41316 / 39,250; B31 0.43158 / 41,000.
- *Verification (rescoped):* Confirmed and broader. A null LTV row is dropped before the lookup. CRR fill_null(0)->35%. A product_type 'mortgage' loan with no collateral at all -> CRR retail_mortgage 0.35/28,000 with zero errors, B31 0.4475. Class comes from the product name. The fix must also stop RE weights when no property is linked; deriving LTV from MV alone is insufficient.

#### P1.417 — Basel 3.1 FCM omits Hfx on non-financial collateral

*Review IDs:* CL-09 · *Regime:* Basel 3.1 · *Effect:* RWA understated · *Size:* S · *Status:* In this PR

- *Current:* haircuts.py:259 restricts fx_haircut to financial types; B31 FIRB EUR property for a GBP loan gives LGD 0.28, RWA 57,496, the same as GBP collateral.
- *Required:* PS1/26 Art. 230(1): ES after '(b) a volatility adjustment for any currency mismatch ... (Hfx)'; Art. 229(1)(b) applies Hfx to immovable property.
- *Fix:* B31 pack Feature fcm_hfx_applies_to_non_financial; expected ES 52,000, LGD 0.296, RWA 60,781. CRR unchanged.
- *Verification (confirmed):* Verbatim PS1/26 Art. 230(1): ES is after '(b) a volatility adjustment for any currency mismatch ... (Hfx)', with no financial-only limit. 231(1)(b) and 231(2)(a) say the same, and 229(1)(b) applies Hfx to property. haircuts.py:259 restricts Hfx to financial collateral. This is the verbatim confirmation P1.198 set as its condition for re-opening. CRR is unchanged.

#### P1.418 — committed=False silently deletes accepted unconditionally cancellable commitments (Doc B G01)

*Review IDs:* CM-01 · *Regime:* Basel 3.1 · *Effect:* RWA understated · *Size:* S · *Status:* In this PR

- *Current:* facility_undrawn.py:206-216 (and MOF :767-791) emits no undrawn row when committed=False; input-schemas.md:206 says False = unconditionally cancellable. Probe: GBP10m, committed=False+LR -> no row, no error (B31 should be 1m).
- *Required:* PS1/26 Art. 111 Table A1 row 7: accepted UCC commitments take 10%; glossary 'commitment' includes unconditionally cancellable arrangements. Only no-offer/not-accepted limits create no exposure.
- *Fix:* Redefine committed=False as 'no commitment offered and accepted'; keep the undrawn row when risk_type is LR (CRR-neutral, 0%); DQ warning for committed=False with other risk_type; fix docs, fixture and pinning test.
- *Verification (confirmed):* Probe reproduced: committed=False+LR gives no row; committed=True+LR gives B31 EAD 1,000,000. input-schemas.md:206 and hierarchy-classification.md:149-150 define False as unconditionally cancellable. Table A1 row (7) sets 10%, and the glossary 'commitment' includes UCC arrangements. CRR is 0%, so no CRR effect.

#### P1.419 — Facility headroom subtracts drawings in other currencies before FX conversion

*Review IDs:* CM-02, SF-01 · *Regime:* Both · *Effect:* Either direction · *Size:* M · *Status:* In this PR

- **CM-02** *Current:* unify.py:93 computes undrawn before resolver.py:133 FX conversion; facility_undrawn.py:302-311,344-347,386-392 sum raw amounts. Probe: GBP10m limit, USD6.5m draw -> undrawn 3.5m, not 5m.
- *Required:* PS1/26 Art. 111(1)(b) / CRR Art. 111(1): nominal value of the undrawn commitment, measured against the advised limit (glossary 'conversion factor'), in one currency.
- *Fix:* Pass fx_rates into calculate_facility_undrawn; convert child drawn/nominal into facility currency before root and MOF per-sub aggregation; DQ warning and no silent zero when a rate is missing.
- *Verification (rescoped):* Confirmed: headroom nets raw units before the FX conversion step, with no DQ (probe: 3.5m vs 5m). The error runs both ways. Headroom is understated when the drawing currency is worth less per unit (USD/EUR/JPY on a GBP line; JPY clips the commitment to 0) and overstated in the reverse case. P0 rests on the lost-commitment case.
- **SF-01** *Current:* facility_undrawn.py:389-391 subtracts unconverted child drawn/nominal from limit; it runs in unify.py:92-101, before FX at resolver.py:133. GBP10m limit with JPY1bn loan: undrawn row vanishes; EUR5m loan: 0.75m headroom lost. No warning.
- *Required:* CRR Art. 4(1)(56) and the PS1/26 glossary define the CF on the undrawn amount of the commitment measured against the advised limit, so limit less utilisation must be in one currency. Exposure value = nominal x CF (Art. 111(1)).
- *Fix:* Convert child utilisation into facility currency before aggregation (thread fx_rates into calculate_facility_undrawn, reuse engine/fx). MOF sub rows keep the sub currency and convert headroom for the cap. New HIE warning when no rate exists.
- *Verification (confirmed):* Re-run confirmed. Headroom is computed in unify before the FX step at resolver.py:133. A GBP 10m facility with a EUR 5m loan gives 5.0m undrawn instead of 5.75m. With a JPY loan the undrawn row disappears, with no warning. The error runs both ways: a non-GBP facility drawn in GBP overstates. The usual UK book understates. No open P-code covers it.

#### P1.420 — B31 A-IRB grants own-estimate CCFs to issued items under a revolving facility

*Review IDs:* CM-03 · *Regime:* Basel 3.1 · *Effect:* RWA understated · *Size:* S · *Status:* In this PR

- *Current:* ccf.py:639-646 own-estimate gate is is_revolving & SA CCF<1, ignores is_obs_commitment; contingents inherit is_revolving (enrich.py:61-92). Probe: issued MLR LC, ccf_modelled 0.05 -> B31 CCF 10% (SA 20%).
- *Required:* PS1/26 Art. 166D(1)(a) own estimates only for revolving loan commitments; (b) all other OBS items use the SA CCF. Glossary: a commitment is not itself an issued OBS item.
- *Fix:* Add is_obs_commitment to the B31 own-estimate eligibility (optionally exclude rows with underlying_risk_type); test B31 issued LC -> 20%, EAD 200,000.
- *Verification (confirmed):* Probe reproduced: an issued MLR LC under a revolving RCF with ccf_modelled 0.05 gives B31 CCF 0.10 (CRR 0.20). The B31 gate at ccf.py:639 ignores is_obs_commitment. Art. 166D(1)(a) allows own estimates only for revolving loan commitments, and the glossary excludes issued items. Loss is capped by the 50% floor.

#### P1.421 — Art. 234 tranched protection (attachment_amount>0) gets RWSM substitution instead of Chapter 5

*Review IDs:* GT-03 · *Regime:* Both · *Effect:* RWA understated · *Size:* M · *Status:* In this PR

- *Current:* guarantees.py:752-813 substitutes the mezzanine band and keeps first-loss and senior tranches at the obligor RW. Loan 10 with protection on [2,6): RWA CRR 8.0 / B31 7.2. Pinned by test_p1_30e (800k on 1m).
- *Required:* Art. 234 (both regimes): tranched transfer follows Chapter 5. Art. 235(2): substitution only for equal seniority. Art. 268 cap ⇒ RWA 10.0 in both regimes.
- *Fix:* Decline substitution for tranched or first-loss protection (new loss_allocation field); emit a CRM error; leave at obligor RW pending SEC-SA (P7.4); rewrite the P1.30(e) test; rescope P5.16.
- *Verification (confirmed):* Measured 8.0 (CRR) / 7.2 (B31). Art. 234 in both regimes sends tranched transfer to Chapter 5, and Art. 235(2) allows RWSM only for equal seniority. Correct RWA is 10.0: no relief without SRT, or SEC-SA ≈20.4 capped by Art. 268. The reviewer's K_A reasoning is wrong (the slice straddles K_A) but the result holds. The P1.30(e) test pins the defect.

#### P1.202 — No-restructuring CDS entered as percentage_covered escapes the Art. 233(2) 40% cut

*Review IDs:* GT-05 · *Regime:* Both · *Effect:* RWA understated · *Size:* S · *Status:* In this PR

- *Current:* guarantees.py:1146-1160 gates on amount_covered>0 and rewrites only the amount. CDS at 100% with no restructuring on 8 is recognised in full: RWA CRR 4.0 / B31 2.4.
- *Required:* Art. 233(2)(a) CRR and PS1/26: reduce protection value by 40%, so G = 4.8 and RWA CRR 5.6 / B31 4.64.
- *Fix:* Extend the haircut to percentage_covered (gate on amount OR pct > 0), mirroring the FX sibling; implement together with GT-06.
- *Verification (confirmed):* Reproduced: a 100% percentage CDS with no restructuring gets RWA CRR 4.0 / B31 2.4, against 5.6 / 4.64 for the amount control. guarantees.py:1146-1150 gates on amount_covered only. Art. 233(2)(a) reads the same in both regimes. Duplicate of the open P1.202, whose line pointers are stale.

#### P1.201 — Art. 233(2)(b) 60%-of-exposure cap missing for an over-sized no-restructuring CDS

*Review IDs:* GT-06 · *Regime:* Both · *Effect:* RWA understated · *Size:* S · *Status:* In this PR

- *Current:* guarantees.py:1146-1160 applies G×0.6 and then the cap at EAD (:686-699). Notional 16 on 8 is recognised in full: RWA CRR 4.0 / B31 2.4.
- *Required:* Art. 233(2)(b) CRR and PS1/26: value no higher than 60% of the exposure value, so G = 4.8 and RWA CRR 5.6 / B31 4.64.
- *Fix:* Join ead_for_crm in _prepare_guarantees; when G > E set G = 0.6E, else 0.6G; apply before the FX haircut per PS1/26 233(3).
- *Verification (confirmed):* Reproduced: a CDS of 16 on 8 with no restructuring is recognised at 8 (RWA CRR 4.0 / B31 2.4). PS1/26 and CRR Art. 233(2)(b) cap protection at 60% of exposure, giving 4.8 cover and RWA 5.6 / 4.64. PS1/26 233(3) applies Hfx after paragraph 2. Duplicate of the open P1.201.

#### P1.422 — B31 SA project-finance phase dropped: pre-operational 130% / high-quality 80% unreachable

*Review IDs:* IV-01 · *Regime:* Basel 3.1 · *Effect:* RWA understated · *Size:* S · *Status:* In this PR

- *Current:* classify/attributes.py:285 join_specialised_lending never selects project_phase; b31_risk_weight_tables.py:816-831 reads always-null sl_project_phase and defaults to operational 100%. Run: pre-op and high-quality PF both RW 1.0.
- *Required:* PS1/26 Art. 122B(2)(c): 130% pre-operational, 100% operational; Art. 122B(4): 80% high-quality operational. Operational status must be evidenced per Art. 122B(3).
- *Fix:* Select project_phase AS sl_project_phase in the SL join; null/unknown PF phase takes the pre-operational pack weight plus a new SL001 warning. Test via loader: pre-op 1.3m, HQ 0.8m, null 1.3m; CRR stays 1.0m.
- *Verification (confirmed):* Re-ran: B31 SA pre-op/HQ/null PF all RW 1.0, sl_project_phase null. Join selects 4 cols only, SA edge injects null. Art. 122B(2)(c) 130% pre-op, (4) 80% HQ verified. HQ limb overstated. Null->pre-op default is an owner decision. Slotting preop table = operational, so SA only.

#### P1.423 — B31 forces IPRE/HVCRE to slotting even for SA-only firms and Art. 148/150 SA permissions

*Review IDs:* IV-02, RG-01 · *Regime:* Basel 3.1 · *Effect:* RWA understated · *Size:* S · *Status:* In this PR

- **IV-02** *Current:* classify/approach.py:309-329 forces slotting on sl_type ipre/hvcre gated only by a pack Feature, above all permission checks. Run: PermissionMode.STANDARDISED B31 HVCRE -> slotting 140%.
- *Required:* PS1/26 Art. 147A(1)(c): SA where Art. 148/150 permission granted, slotting only for other IPRE/HVCRE of IRB firms; a firm without IRB permission uses SA (ADC 150% Art. 124K).
- *Fix:* AND the forced-slotting predicate with 'firm holds IRB/slotting permission for SL' and no standardised (PPU) model permission. Test: SA-only firm, HVCRE strong ADC 1m -> SA 1.5m (today 0.95m).
- *Verification (confirmed):* Forced slotting has no permission gate. Default STANDARDISED: HVCRE strong ADC slotted 0.95 vs sa_rwa 1.5; IPRE strong 0.70 vs 1.0. HVCRE satisfactory is overstated (1.40 vs 1.0). Art. 147A(1)(c) is an IRB-Part rule with an Art.148/150 SA limb. Pins all use IRB mode.
- **RG-01** *Current:* approach.py:309-314,328-329 forces slotting on sl_type alone. Measured: B31 SA-only firm IPRE strong 1,000,000 -> slotting 70%, RWA 700,000; PPU SA permission row also overridden (700,000).
- *Required:* PS1/26 Art. 107(1)/143(2A): slotting is an IRB approach needing permission; Art. 147A(1)(c)(i): SA where Art. 148/150 permission. Expected SA 100% -> 1,000,000.
- *Fix:* Gate branch 4 on firm_has_irb_permission & ~model_sa_permitted (keep _sa_block as edge column); Feature stays the regime gate. Drop 'slotting' from SA-only stress assertion.
- *Verification (confirmed):* Re-measured: default B31 SA-only IPRE strong 1m -> slotting 700,000; an Art.150 SA-permission row is overridden too. Art.107(1) says IRB, including slotting under Art.143(2A), needs permission. Art.147A(1)(c)(i) keeps SA under 148/150. Weak 250% overstates, but the common case understates. Not filed.

#### P1.424 — B31 Art. 133(5) 150% subordinated-debt weight misses specialised-lending rows

*Review IDs:* IV-03 · *Regime:* Basel 3.1 · *Effect:* RWA understated · *Size:* S · *Status:* In this PR

- *Current:* sa/risk_weights.py:1560-1574 _is_b31_subordinated_debt matches only INSTITUTION/CORPORATE strings; SL rows keep class specialised_lending. Run: subordinated PF loan B31 RW 1.0.
- *Required:* PS1/26 Art. 133(5): 150% for an exposure that is a subordinated debt instrument; Art. 112(2) Table A2 ranks class (p) above corporates (incl. SL subclass).
- *Fix:* Key predicate on exposure_class_sa (CORPORATE incl. SL) not exposure_class string; owner decision on PSE/RGLA/MDB. Test: B31 subordinated operational PF 1m -> 1.5m (today 1.0m); CRR unchanged.
- *Verification (confirmed):* B31 run gives subordinated PF RW 1.0 vs corporate 1.5. Predicate string-matches INSTITUTION/CORPORATE, so the SL class misses. Art. 133(5) quoted. 'Subordinated debt instrument' is undefined; the engine already treats subordinated loans as in scope for corporates. No test pins SL at 100%.

#### P1.425 — Securitisation allocator excludes exposures even when significant_risk_transfer=False

*Review IDs:* IV-04 · *Regime:* Both · *Effect:* RWA understated · *Size:* S · *Status:* In this PR

- *Current:* schemas.py:1519-1522 SRT default True, comment says carve-out applied when False; securitisation/allocator.py never reads the flag. Run: 1m loan, SRT False, 100% allocated -> RWA 0, both regimes.
- *Required:* CRR Art. 244(1)/245(1): originator may exclude underlying exposures only if SRT achieved or all retained positions are 1250%/deducted.
- *Fix:* Allocator: SRT False/null rows give no carve-out and raise new SEC006; make column nullable without default; optional limb-(b) attestation. Test: SRT False -> RWA 1.0m (today 0); SRT True -> 0.
- *Verification (confirmed):* SRT=False with 100% allocation gives ead/rwa 0 in both regimes, with only SEC005. The flag is never read. Art. 244(1) allows exclusion only with SRT or all retained positions at 1250%/deducted. Distinct from P7.4's condition assessment. Changing the null default is a separate owner decision.

#### P1.426 — CIU look-through: unsupported underlying classes silently weighted 100%

*Review IDs:* IV-05 · *Regime:* Both · *Effect:* RWA understated · *Size:* M · *Status:* In this PR

- *Current:* equity/calculator.py:487-490 fill_null(_DEFAULT_HOLDING_RW=1.00, :154); CIU_HOLDINGS_SCHEMA.exposure_class (schemas.py:1386) unvalidated. Run: high_risk, sub debt, securitisation, nested CIU holdings -> fund RW 1.0 both regimes.
- *Required:* PS1/26 Art. 132A(1): weight underlyings as if directly held; Art. 132(5) nested CIU else fall-back 1250%; Art. 128 150%, Art. 133(5) 150%; CRR Art. 254(7) securitisation 1250%.
- *Fix:* Value-constrain holding class; class-keyed holding weights from cited pack entries; securitisation/CIU 1250% unless holding_risk_weight supplied; unknown -> 1250% + warning. Test B31: high_risk 150, sub debt 150, securitisation 1250 per 100.
- *Verification (rescoped):* Confirmed: nested 'ciu' holding 100% vs Art.132(5) fall-back 1250% (both regimes); B31 'high_risk' 100% vs 150%. But CRR high_risk 100% is right (Art.128 omitted from UK CRR). 'securitisation'/'subordinated_debt' are not ExposureClass values, so that is a validation gap. Retail/RE holdings are overstated.

#### P1.427 — CRR equity ignores is_significant_investment (Art. 48(4) 250%)

*Review IDs:* IV-06 · *Regime:* CRR · *Effect:* RWA understated · *Size:* S · *Status:* In this PR

- *Current:* equity/calculator.py:629-660 CRR SA chain: central bank, CIU, else 100%; IRB-simple :715-790 likewise. Run: CRR SA significant investment RW 1.0 (IRB simple 2.9/3.7, overstated).
- *Required:* CRR Art. 133(2): equity 100% 'unless ... assigned a 250% risk weight in accordance with Article 48(4)'; Art. 48(4) 250% is approach-agnostic.
- *Fix:* Cited CRR pack scalar (2.50, Art. 133(2)/Own Funds 48(4)); first branch after central bank in CRR SA, IRB-simple and PD/LGD chains. Test: CRR SA listed sig. investment 100 -> 250 (today 100); IRB simple -> 250.
- *Verification (confirmed):* CRR SA significant investment RW 1.0. The chain's own docstring quotes Art.133(2)'s 250% clause but does not apply it. Art.155(1) excludes 250% items from IRB equity, so IRB-simple 290/370 is overstated. P1.393 covers B31 only. Applies only to non-deducted FSE CET1 amounts.

#### P1.428 — SME and B31 LFSE size tests use entity-own, not consolidated-group figures

*Review IDs:* RC-05, RC-06 · *Regime:* Both · *Effect:* RWA understated · *Size:* M · *Status:* In this PR

- **RC-05** *Current:* attributes.py:195-210 sme_size_metric = own revenue/assets; subtypes.py:218-219 LFSE own assets. SUB 10m in 1bn group: B31 85% (850k) with CLS011 same run; CRR SF 0.7619 (761,900).
- *Required:* PS1/26 SME glossary 'highest consolidated accounts of the group'; Art. 153(4) both regimes 'consolidated group'; CRR 501(2)(b)/4(1)(128D); PS1/26 LFSE glossary 'highest level of consolidation'.
- *Fix:* group_annual_revenue/group_total_assets = max over self+ancestors; sme_size_metric from group figures; LFSE via b31 Feature lfse_assets_at_highest_consolidation.
- *Verification (confirmed):* p9 re-run: SUB (own 10m, group 1bn) gets B31 85% (850,000) with CLS011 in the same run, and CRR SF 0.7619 (761,900). The PS1/26 SME glossary says 'highest consolidated accounts of the group'; Art. 153(4) uses the consolidated group in both regimes. The LFSE limb is B31-only and the apply_fi_scalar override can cover it.
- **RC-06** *Current:* attributes.py:248-275 max(own, ultimate parent) only; TOPFUND(null)→MIDCO(1bn)→SUB(300m): A-IRB RWA 568,750; without fund apex: SA 1,000,000 + CLS011.
- *Required:* PS1/26 Art. 147(4C)(b)(ii): revenue 'at the highest level of consolidation which is performed and at which audited financial statements are available'.
- *Fix:* Compute group revenue as max over full org ancestor closure (shared with RC-03/RC-05). Adjacent P1.321, P2.92.
- *Verification (rescoped):* Reproduced (p15): with TOPFUND(null)->MIDCO(1bn)->SUB(300m) the result is A-IRB 568,750; without TOPFUND it is SA 1,000,000 + CLS011. max(own, ultimate) skips the mid-level consolidator, against 147(4C)(b)(ii). The population is narrow (B31, A-IRB permission, a null-revenue apex above a >GBP440m mid-parent), so P1. It shares RC-05's closure fix.

#### P1.429 — Solo/sub-consolidated runs aggregate retail and SME-SF thresholds on scoped books only

*Review IDs:* RC-07, RG-02, RE-12 · *Regime:* Both · *Effect:* RWA understated · *Size:* M · *Status:* In this PR

- **RC-07** *Current:* registry.py:47-49 scope before hierarchy; scope/resolver.py:368-369 filter; enrich.py:535-553 sums remainder. SME 500k+500k across entities, individual run: B31 375,000 (should 425,000); CRR 285,712.5 (should 380,950).
- *Required:* PS1/26 Art. 123(1)(b)(ii)/123A: amount owed 'to the institution, its parent undertakings, its subsidiaries and subsidiaries of its parent undertakings'; CRR Art. 123(c), Art. 501(1) E*.
- *Fix:* Scope stage publishes unscoped threshold_population artifact; enrich_with_lending_group sums over it (FX-converted, intragroup excluded), then filtered rows keep group totals.
- *Verification (confirmed):* p14 re-run on an individual SUBBANK run: aggregate 500k gives B31 375,000 (consolidated 425,000) and CRR 285,712.50 (consolidated 380,950), with no error. PS1/26 123(1)(b)(ii)/123A verbatim: 'owed to the institution, its parent undertakings, its subsidiaries and subsidiaries of its parent undertakings'. CRR 123(c) says the same. Scope runs before hierarchy. Not in plan (P1.364 is a different item).
- **RG-02** *Current:* registry.py:47 + scope/resolver.py:212-223 filter books before hierarchy. Measured PARENT-individual: 600k loan retail 75% (450,000) vs 600,000; CRR SME SF 0.7619 (1,523,800) vs 0.80192 (1,603,838.85).
- *Required:* PS1/26 Art. 123(1)(b)(ii)/123A(1)(b)(ii)/147(5)(a)(ii) and CRR Art. 123(c), 501(1): amount owed to institution, parent undertakings and their subsidiaries.
- *Fix:* Scope stage aggregates out-of-scope in-registry lending per obligor into cp_group_owed_out_of_scope(_ex_rre) on counterparties; hierarchy and compute_e_star add once per obligor; unscoped runs unchanged.
- *Verification (confirmed):* Re-measured: PARENT-individual run gives LA retail 75% (450,000) vs 600,000 on consolidated/unscoped, both regimes; CRR SME factor 0.7619 vs 0.80192. The rules (PS1/26 123/123A/147(5), CRR 123(c)/501(1)) count amounts owed to group entities, and every registry entity is in that group. Not filed.
- **RE-12** *Current:* registry.py:47-49 scope before hierarchy; scope/resolver.py:367-370 filters rows; hierarchy/enrich.py:546-553 sums filtered frame. Measured NP 500k BANK_A + 500k BANK_B: BANK_A solo RW 0.75, RWA 375,000 (both regimes).
- *Required:* PS1/26 Art. 123(1)(b)(ii)/123A(1)(b)(ii) and CRR Art. 123(c): amount owed to institution, parents, subsidiaries and parent's subsidiaries.
- *Fix:* Compute per-counterparty/lending-group aggregate over whole registry pre-filter in resolve_scope; hierarchy uses max(local, group); add optional group_retail_threshold_exposure input. Test: BANK_A 1.00 / 500,000 both regimes.
- *Verification (confirmed):* Re-run with the multi-entity registry: unscoped aggregate 1,000,000 -> non-retail 1.00. BANK_A individual: aggregate 500,000, retail 0.75/375,000 in both regimes. resolve_scope filters rows before the hierarchy sums. Art. 123A(1)(b)(ii) and CRR Art. 123(c) (parents and subsidiaries; 'reasonable steps') quoted. The data is in the bundle and discarded; sub-consolidated runs are affected too.

#### P1.430 — Cross-table exposure_reference collisions merge rows and double CRM relief

*Review IDs:* RC-10 · *Regime:* Both · *Effect:* RWA understated · *Size:* M · *Status:* In this PR

- *Current:* schemas.py:2720-2725 per-table uniqueness only; guarantees.py:612-623/660-667 join on reference ignoring type. Loan+contingent 'X1' + 1m loan guarantee: EAD 2m→1m, RWA 1m→0, no error.
- *Required:* PS1/26 & CRR Art. 213(1)(a): 'the credit protection is direct'; Art. 111(1): each item measured.
- *Fix:* Cross-table namespace uniqueness (loans, contingents, equity, CCR/SFT, _UNDRAWN refs) as DQ004 ERROR; type-aware beneficiary joins in guarantees/collateral/provisions. Adjacent P5.52.
- *Verification (confirmed):* p8 reproduced: 1m vanishes and the guarantee covers both rows. New probe, no CRM, IRB permissions: loan X1 + contingent X1 produce ONE row (EAD 1m vs 2m; CRR RWA 1.11m vs 2.23m), with no error. Cause: permissions.py:261 unique(exposure_reference). Per-table keys are the only stated contract.

#### P1.431 — Collateral-level is_adc/is_presold silently dropped; ADC loans priced as regulatory RE

*Review IDs:* RE-01 · *Regime:* Both · *Effect:* RWA understated · *Size:* M · *Status:* In this PR

- *Current:* hierarchy/enrich.py:638-643 copies no is_adc; classify/attributes.py:550-565 derives ADC only from loan flag/product_type. Measured: corporate dev loan 500k, collateral is_adc=True -> B31 RW 0.20 (100k), CRR 0.35 (175k).
- *Required:* PS1/26 Art. 124(3)/124K(1): ADC exposure 150%. CRR Art. 125(1)(a)/124(1): residential not occupied/let by owner -> 100%.
- *Fix:* Propagate collateral is_adc/is_presold (any-True per beneficiary), declare on HIERARCHY_EXIT_EDGE, OR into _build_is_adc_expr. Test: B31 750,000; CRR 500,000.
- *Verification (confirmed):* Re-measured: collateral is_adc=True -> B31 split 0.20/100,000, CRR 0.35/175,000, output is_adc=false; loan-level flag gives 1.50/750,000 and 1.00/500,000. enrich.py:637-643 copies no is_adc; classifier comment admits it never arrives. Docs tell users to set is_adc, and only COLLATERAL_SCHEMA carries it. Art. 124(3)/124K(1) quoted.

#### P1.432 — B31 reclassifies non-regulatory natural-person retail to CORPORATE, losing Art. 123B multiplier

*Review IDs:* RE-03 · *Regime:* Basel 3.1 · *Effect:* RWA understated · *Size:* M · *Status:* In this PR

- *Current:* classify/subtypes.py:247-252 un-gated 'retail not qualifying -> CORPORATE'; rw_adjustments.py:493-504 scopes 123B by class. Measured NP EUR loan 1m, GBP income -> corporate RW 1.00, RWA 1,000,000; omitted is_managed_as_retail -> corporate.
- *Required:* PS1/26 Art. 123(1)(a): natural persons are retail; Art. 123(3)(c) 100%; Art. 123B(1) applies 1.5x to unhedged retail.
- *Fix:* Pack Feature non_qualifying_retail_leaves_retail_class (CRR on, B31 off) gating the branch; keep SME limb. Test B31 retail_other 1.50 / 1,500,000; CRR corporate 1,000,000 unchanged.
- *Verification (confirmed):* Measured B31: natural person, EUR 1m loan, GBP income -> corporate 1.00/1,000,000, no multiplier; expected retail 1.50. PS1/26 Art. 123(1)(a) makes every natural-person exposure retail; 123(3)(c) gives 100%; 123B(1) applies. CRR exclusion text confirmed, so CRR stays. A feed omitting is_managed_as_retail (loader default False) sends all B31 natural-person loans to corporate.

#### P1.433 — Null borrower income currency never triggers Art. 123B; 123B(3) fallback unimplemented and mis-cited

*Review IDs:* RE-05 · *Regime:* Basel 3.1 · *Effect:* RWA understated · *Size:* M · *Status:* In this PR

- *Current:* rw_adjustments.py:506 requires non-null income ccy; :443-472 cites 123B(3) for a reporting-date gate. Measured GB NP EUR mortgage 80k: income null RW 0.20 (16,000); income GBP 0.30 (24,000).
- *Required:* PS1/26 Art. 123B(3): if mismatch unidentifiable (pre-2027 exposures), apply 1.5x unless lending currency is the domestic currency of residence/employment.
- *Fix:* When income null compare lending ccy with cp local_currency/country currency; apply 1.5x (Feature cited 123B(3)); DQ warning for post-2027 exposures. Test 0.30 / 24,000; GBP control 0.20.
- *Verification (confirmed):* Measured: GB natural person, EUR mortgage, income null -> 0.20/16,000, no error; income GBP -> 0.30/24,000. Art. 123B(3) quoted: pre-2027 unidentifiable exposures take 1.5x unless lending currency equals domestic currency of residence or employment. @cites 123B.3 sits on a commencement gate. The 2027 opening book is all pre-2027.

#### P1.292 — Null is_qualifying_re treated as qualifying (Art. 124A)

*Review IDs:* RE-16 · *Regime:* Basel 3.1 · *Effect:* RWA understated · *Size:* M · *Status:* Blocked (existing item)

- *Current:* b31_risk_weight_tables.py:519-537 and hierarchy/enrich.py:418-420 fill_null(True); null is the default input state.
- *Required:* PS1/26 Art. 124A(1): regulatory RE only if all requirements met, including institution attestations (b),(d),(f).
- *Fix:* As P1.292 (five sites, after P1.353, surgical golden regen). Test: B31 NP LTV 0.5 null -> 0.75 / 75,000; CRR unmoved.
- *Verification (confirmed):* Re-measured: B31 natural person LTV 0.5 with is_qualifying_re null -> 0.20/20,000 (CRR 0.35). This is the existing open item P1.292: unblocked 2026-09-10, sequenced after P1.353, five sites, operator-signed surgical golden regeneration. Not a new filing.

#### P1.434 — Committed sub-facilities dropped under an uncommitted MOF/umbrella parent

*Review IDs:* SF-02 · *Regime:* Both · *Effect:* RWA understated · *Size:* S · *Status:* In this PR

- *Current:* Sub waterfall rows inherit the parent's committed column (facility_undrawn.py:855-867), and the :214 filter drops them. P(committed=False) with two committed subs of 8 headroom emits zero rows: CRR EAD 8.0 and B31 6.4 lost, silently.
- *Required:* A committed sub-facility is a commitment: CRR Art. 111(1)/Annex I; PS1/26 Art. 111(1)(b) Table A1 rows 4-5. Even an unconditionally cancellable line is 10% under Table A1 row 7, never omitted.
- *Fix:* Carry _sub_committed onto waterfall rows as committed (the residual keeps the parent flag). Add a DQ warning for a committed sub under an uncommitted ancestor.
- *Verification (confirmed):* Re-run case A (B31): the parent has committed=False and the subs are committed; zero undrawn rows are emitted and 6.4 EAD is lost silently. With a null parent limit and committed=True the sub rows appear, so the inherited parent flag (:855-867, filter :214) is the cause. No test pins this shape. The Table A1 row 7 point belongs to G01, not here.

#### P1.435 — Trade-LC flag broadcast per counterparty leaks onto every loan

*Review IDs:* TR-01 · *Regime:* Both · *Effect:* RWA understated · *Size:* S · *Status:* In this PR

- *Current:* enrich.py:93-104,1135-1183 ORs is_short_term_trade_lc over all facilities of a counterparty onto all its loans (unify.py:169 nulls loans). B31 SA 40%->20%, CRR IRB M 1y->1 day (RWA 488,073->370,573) measured.
- *Required:* PS1/26 Art 120(2A)/121(4) need exposure 'arose from the movement of goods'; CRR 162(3)(b)/PS1/26 162(3)(e) need self-liquidating trade finance. A counterparty's other loans do not qualify.
- *Fix:* Delete _broadcast_trade_lc_flag; inherit flag only from parent facility via parent_facility_reference (add to _join_facility_qrre_columns fac_specs). Fix P1.128 fixture (relies on leak). Sequence before P1.326.
- *Verification (confirmed):* Reproduced: _broadcast_trade_lc_flag joins on counterparty only and lands on every loan (contingents and undrawn legs keep their own value). B31 SA 40%->20%; CRR F-IRB M 1.0->1/365; B31 sovereign-floor exemption also leaks. Art 121(4)/120(2A) require 'arose from the movement of goods'. No plan item. P1.128 test reaches 20% only through the leak (C1).

#### P1.436 — Art 166A(5) IRB 40% purchased-receivables CCF applied to SA rows and A-IRB own estimates

*Review IDs:* TR-02 · *Regime:* Basel 3.1 · *Effect:* RWA understated · *Size:* S · *Status:* In this PR

- *Current:* ccf.py:584-587,805-845 overrides SA carrier to 40% when flag+revolving, even risk_type FR/FRC (measured SA 0.4 vs 1.0); A-IRB then takes own estimate 0.25 (ccf.py:639-646). schemas.py:537-544 cites Row 5.
- *Required:* PS1/26 Art 166A(5) (IRB Part) mandates 40%/10% for IRB; SA Table A1 Row 2(a) 'transactions with recourse (including factoring and invoice discount facilities)' = 100%.
- *Fix:* Gate override to FIRB/AIRB/slotting via pack Feature; make IRB value final (no own-estimate limb); flagged SA blank risk_type resolves to FRC. Fix schema comment and 166E citation.
- *Verification (rescoped):* Confirmed: the IRB-Part Art 166A(5) override rewrites SA rows' explicit bucket (FR/FRC 1.0->0.4, MR 0.5->0.4) and opens A-IRB own estimates (0.25 vs a mandatory 0.40). Not demonstrated: a blank flagged SA row is 0.40 with or without the flag (Row 5 residual). Remapping it to FRC is design, because not every purchase commitment is 'with recourse'.

#### P1.437 — Retail dilution risk priced with retail correlation, not Art 153(1)

*Review IDs:* TR-03 · *Regime:* Both · *Effect:* RWA understated · *Size:* S · *Status:* In this PR

- *Current:* irb/transforms.py:720-745 and formulas.py:632-645 pick correlation/MA by exposure_class only; retail dilution row R=0.0946, RWA 102,443 vs required 169,195 (CRR, PD 2%, LGD 75%).
- *Required:* CRR & PS1/26 Art 157(1): RWEA for dilution risk of purchased corporate and retail receivables 'in accordance with the formula set out in Article 153(1)'.
- *Fix:* In apply_all_formulas and formulas.py twin, route purchased_receivables_subtype=='dilution_risk' to Art 153(1)(c) corporate correlation (no SME/FSE adjustments) and corporate MA; keep class for reporting.
- *Verification (rescoped):* Retail half confirmed: correlation is chosen by class only. A retail dilution row gets R=0.0946 and RWA 102,443; Art 153(1) gives 169,195 (-39.5%). Art 157(1) says the same in CRR and PS1/26. Not a dup of P1.305/P1.351 (LGD). Unproven: stripping the SME/FSE adjustments from corporate dilution rows. Removing the 1.25 FSE multiplier is RWA-reducing.

### P1 — capital overstated, common structure not representable, or missing control

#### P1.438 — QCCP 2%/4% pin applied to non-trade exposures; non-QCCP treated as institution not corporate

*Review IDs:* CC-11 · *Regime:* Both · *Effect:* RWA understated · *Size:* S · *Status:* In this PR

- *Current:* sa/risk_weights.py:1144-1154 and 1350-1360 pin any ccp row; sa/cqs_lift.py:66-80 non-QCCP -> institution ladder. Probe: 1m term loan to QCCP RW 2% both regimes (expected 100% CRR / 150% B31 unrated).
- *Required:* CRR & PS1/26 Art 107(2): other exposures '(a) as exposures to an institution ... qualifying CCP; (b) as exposures to a corporate ... non-qualifying CCP'; CCR Part Art 306(1)(b) non-QCCP trade exposures use 107(2)(b).
- *Fix:* Add trade-exposure term (CCR_DERIVATIVE/CCR_SFT or new is_ccp_trade_exposure flag for posted IM) to both pins, reusing sovereign_floor.py:193-199 predicate; classify non-QCCP as corporate.
- *Verification (rescoped):* Code confirmed: the 2%/4% pin covers any ccp row; cqs_lift cites 107(2)(a) for non-QCCP where 107(2)(b) is correct. But non-trade exposures to CCPs are uncommon, since posted IM and DF are trade/Section 9 items where 2% is right. The institution-vs-corporate swap moves both ways (B31 SCRA C 150% vs 100%). Downgraded to P1.

#### P1.439 — SFT netting set pools trades without master-netting eligibility; multi-counterparty sets merged

*Review IDs:* CC-14 · *Regime:* Both · *Effect:* RWA understated · *Size:* M · *Status:* In this PR

- *Current:* sft/fccm.py:410-427 nets E and collateral across trades in netting_set_id with no enforceability flag; :163-167 counterparty first(). Probe: two trades E* 52.1m vs 100m; two counterparties merged into CP1.
- *Required:* CRR & PS1/26 Art 220(1) netted E* only for 'exposures subject to an eligible master netting agreement'; PS1/26 Art 111(2A) single netting-set value only where an MNA is taken into account.
- *Fix:* Add is_legally_enforceable to SFT trades; split ineligible multi-trade sets per trade with optional trade_id on SFT collateral; DQ error for >1 counterparty per netting set.
- *Verification (rescoped):* Code confirmed: netting has no MNA gate, under_master_netting_agreement is read only for maturity, and the counterparty is taken with first(). But the schema documents a single-CP single-trade NS scope, and repo books are mostly under GMRA, so this is a missing eligibility/DQ gate. A multi-CP set keeps its EAD and misattributes it to the first counterparty's RW; nothing is lost.

#### P1.440 — BA-CVA completeness: missing or partial CVA counterparty input silently gives no CVA charge

*Review IDs:* CC-16 · *Regime:* Basel 3.1 · *Effect:* RWA understated · *Size:* S · *Status:* In this PR

- *Current:* stages/aggregate.py:142-145 returns None when cva_counterparties absent; cva/ba_cva.py:225-226 inner join drops uncovered counterparties; DEBUG log only.
- *Required:* PS1/26 CVA Risk Part: own funds for CVA risk on all covered transactions (QCCP/client-clearing exclusions and 7.1 transitional aside).
- *Fix:* WARNING CalculationError per CCR_DERIVATIVE counterparty without CVA input (excluding QCCP trades); optional conservative default sector/rating behind config.
- *Verification (confirmed):* aggregate.py returns None without a log when cva_counterparties is absent. The ba_cva inner join silently drops derivative counterparties missing from the CVA table. This is a missing DQ control, correctly P1.

#### P1.441 — Specific wrong-way risk: netting-set split only; no jump-to-default EAD, LGD 100% never consumed

*Review IDs:* CC-18 · *Regime:* Both · *Effect:* RWA understated · *Size:* M · *Status:* Backlog

- *Current:* ccr/wwr.py docstring: 'does not modify the SA-CCR EAD calculation'; wwr_lgd_override has no IRB reader (only re_split/carriers.py:67).
- *Required:* CRR Art 291(5)(b) CDS EAD = full expected loss assuming underlying in liquidation; (c) IRB LGD 100%; (e) other single-name trades consistent with jump-to-default.
- *Fix:* For is_specific_wwr trades compute JTD EAD (needs underlying fair value/recovery inputs) instead of SA-CCR; IRB LGD chain reads wwr_lgd_override.
- *Verification (confirmed):* wwr_lgd_override has no IRB reader. P8.53 deferred IRB use 'blocked on P8.31', which has since shipped, so the item is unowned (B7). Art. 291(5)(c) LGD 100% applies only to single-name CDS, yet the gate tags every specific-WWR trade. JTD EAD needs new inputs.

#### P1.442 — Engine-only risk types CCR_DERIVATIVE/CCR_SFT accepted on lending tables

*Review IDs:* CC-19 · *Regime:* Both · *Effect:* Either direction · *Size:* S · *Status:* In this PR

- *Current:* schemas.py:2492-2502 accepts them. Probe: 10m contingent CCR_SFT gets CCF 100% CRR / 50% B31, label standardised_ccr; CCR_SFT loan becomes repo-style in IRB (irb/transforms.py:993-1003,1117-1124).
- *Required:* CRR Art 271(2) / PS1/26 Art 111(2)-(2A): derivative and SFT exposure values come from the CCR Part or FCCM, not an Annex I/Table A1 CCF.
- *Fix:* Remove both values from the lending-table accepted risk_type domain (DQ006); keep in canonical vocabulary for engine-minted rows only.
- *Verification (confirmed):* Probe: contingents with CCR_DERIVATIVE/CCR_SFT get CCF 100% (CRR) / 50% (B31), labelled standardised_ccr, with no DQ006. Removing them loses no capability, because lending tables carry is_sft for repo-style Art. 162(1) M.

#### P1.443 — SA FCCM E* accepts any collateral type flagged is_eligible_financial_collateral

*Review IDs:* CL-01 · *Regime:* Both · *Effect:* RWA understated · *Size:* S · *Status:* In this PR

- *Current:* collateral.py:677-681 SA predicate is the flag alone; flagged CRR receivables/RE give EAD 0 (RWA 0), B31 other physical 40,000, life policy RWA 0. No warning.
- *Required:* Only Art. 197 financial collateral reduces SA E* (CRR/PS1-26 Art. 197(1), 199(1) is IRB/FCM-only); life policies use Art. 232(3) RW mapping.
- *Fix:* AND the flag with an Art.197 type predicate from normalise_collateral_type_expr; rolled-up CRM023 warning. No fixture flags non-financial rows, so goldens stay put.
- *Verification (rescoped):* Re-ran t14: flagged receivables/RE give RWA 0 (CRR), 40,000 (B31); life policy goes to 0 (unflagged it is 70,000, not 35,000). Mechanism is real. P1 because the input breaks the documented 'Meets SA eligibility (CRR Art 197)' contract and no fixture flags a non-financial row. The engine already overrides this flag by type (haircuts.py:285-313).

#### P1.444 — Duplicate collateral_reference undetected; same asset credited in full per row

*Review IDs:* CL-03 · *Regime:* Both · *Effect:* RWA understated · *Size:* M · *Status:* Backlog

- *Current:* schemas.py:2720 TABLE_UNIQUE_KEYS omits collateral; one 100k asset on two rows covers two 100k loans (RWA 0, no DQ). link_allocation.py:362-364 join multiplies slices.
- *Required:* PS1/26 Art. 193(7)(b): allocate each portion of eligible collateral to one exposure 'without any double-counting'; Art. 193(2).
- *Fix:* Add collateral to TABLE_UNIQUE_KEYS (DQ004); convert duplicate rows to implicit links so the finite allocator conserves value; unique() on allocator value/attr lookups.
- *Verification (rescoped):* TABLE_UNIQUE_KEYS has no collateral entry, and the allocator joins fan out on a repeated key. Both confirmed. But it only triggers on input that breaks the documented 'Unique identifier' contract, and no fixture has duplicates, so this is a missing DQ control (P1). Minimal fix: DQ004 plus unique() on the allocator lookups. The implicit-links conversion is speculative.

#### P1.445 — FIRB recognises financial collateral the firm marked as failing Art. 207

*Review IDs:* CL-06 · *Regime:* Both · *Effect:* RWA understated · *Size:* M · *Status:* Backlog

- *Current:* collateral.py:798-803 waterfall ignores is_eligible_financial_collateral; flag False/null/True all give CRR RWA 64,374 and B31 57,500 (unsecured 111,402 / 82,137). SA honours it.
- *Required:* PS1/26 Art. 207(1) names the Foundation Collateral Method: financial collateral eligible only where paras 2-4 (incl. enforceability) are met; CRR Art. 207(1) 'all approaches'.
- *Fix:* Gate fin/cash waterfall categories on the SA eligibility predicate with a warning; fix input-schemas doc; measure fixture blast radius before choosing null handling.
- *Verification (rescoped):* Confirmed: the FIRB waterfall filters by category only. But the flag is documented as SA eligibility, and Boolean null is filled to False at the seal, so an FIRB book that leaves it unset is following the contract. The fix needs a contract decision (a new Art. 207 FIRB attestation) and moves unit tests. PS1/26 207(1) names the FCM.

#### P1.446 — CRR SA real estate ignores is_qualifying_re=False

*Review IDs:* CL-07, RE-09 · *Regime:* CRR · *Effect:* RWA understated · *Size:* S · *Status:* In this PR

- **CL-07** *Current:* sa/risk_weights.py:797-816 CRR RE branch never reads is_qualifying_re; LTV 0.5 mortgage gets 35% (RWA 35,000) with flag False.
- *Required:* CRR Art. 125(2)(c) requires Art. 208/229(1) met; Art. 124(1): 100% where Art. 125/126 conditions are not met.
- *Fix:* CRR pack Feature routing explicit False to the Art. 124(1) 100% weight; null stays permissive (P1.292 handles B31 null). Expected RWA 100,000.
- *Verification (rescoped):* The CRR branch does ignore the flag, but on purpose: c07.py:1726-1739 records that is_qualifying_re is the B31 Art. 124A flag that no CRR risk-weight path reads. 124A(2) charge-ranking and ADC have no CRR 125/126 analogue, so mapping False to 100% can over-charge. Needs a CRR-specific attestation. CRR sunsets 31 Dec 2026.
- **RE-09** *Current:* risk_weights.py:768-819 and re_split/flagging.py:259-268 never read qualification under CRR. Measured NP mortgage 80k, is_qualifying_re=False: CRR 0.35 / 28,000 (B31 0.75).
- *Required:* CRR Art. 124(1): 100% where Art. 125/126 conditions not met; Art. 125(2)(a)/(c) value independence, Art. 208 and 229(1) requirements.
- *Fix:* Pack Feature crr_re_qualification_gate: explicit False (CRR attestation or reused field) routes secured part to 100% in branch and split eligibility; null unchanged pending P1.292. Test CRR 1.00 / 80,000.
- *Verification (rescoped):* Mechanism true, but is_qualifying_re is documented as the Basel 3.1 Art. 124A attestation, so no CRR input is dropped. The real gap: no carrier for CRR Art. 125(2)/126(2) conditions. That is schema enablement with about 6 weeks of CRR left. UK derogations 125(3)/126(3) from limb (b) also exist, so blanket reuse of the B31 flag would over-reach.

#### P1.447 — B31 Art. 124H(3) whole-loan CRE overwrites the 124C LTV and drops the 124I(3) junior weights

*Review IDs:* CL-10 · *Regime:* Basel 3.1 · *Effect:* RWA understated · *Size:* S · *Status:* In this PR

- *Current:* splitter.py:767-779 sets ltv=EAD/value; b31_risk_weight_tables.py:716 caps on base table only. CQS5 corporate, prior 20k, own 70k: RW 1.00, RWA 70,000.
- *Required:* PS1/26 Art. 124C(3) LTV includes prior/pari-passu loans; Art. 124H(3)(b)(ii) uses the RW 'under Article 124I', including 124I(3) junior weights.
- *Fix:* Keep the input ltv in whole mode; the cap uses the full income_rw. Expected RW 1.10 (77,000) from the LTV fix, 1.375 (96,250) with 124I(3). Only material where counterparty RW exceeds 100%.
- *Verification (rescoped):* Re-ran t10: input LTV 0.9 is overwritten with 0.7, RW 1.00. 124H(3)(b)(ii) 'under Article 124I' covers 124I(3), so the code comment's base-table-only reading is weaker. It binds only where the counterparty RW is above the 124I weight (135%/150% corporates with CRE security), so the population is narrow: P1, not P0.

#### P1.448 — Canonical collateral type 'bond' is not financial collateral on the FIRB path

*Review IDs:* CL-11 · *Regime:* Both · *Effect:* RWA overstated · *Size:* S · *Status:* In this PR

- *Current:* schemas.py:2274-2283 FINANCIAL_COLLATERAL_TYPES lacks 'bond'; expressions.py:227-246 maps to 'other'. FIRB RWA 111,402 CRR / 82,137 B31 vs 56,815 / 57,450 as government_bond. Spurious CRM014/021 on SA.
- *Required:* CRR/PS1-26 Art. 197(1)(b)-(d): rated debt securities are eligible under all methods; PS1/26 Art. 230(2) financial collateral LGDS 0%.
- *Fix:* Derive the waterfall category from normalise_collateral_type_expr (bond plus issuer_type) so haircut, eligibility and category agree.
- *Verification (confirmed):* Re-ran t4: FIRB bond gives CRR LGD 0.45 / 111,402 vs government_bond 0.2295 / 56,815, and B31 0.3265 vs 0.204. CRM014/021 also fire spuriously on SA. FINANCIAL_COLLATERAL_TYPES has no 'bond'. P1.233's fix line also prescribed this categorisation change, but only the haircut half shipped.

#### P1.449 — Single prior_charge_ltv cannot carry the B31 claim stack; loan-split share double-counts it

*Review IDs:* CL-12, RE-08, SF-11 · *Regime:* Basel 3.1 · *Effect:* RWA overstated · *Size:* L · *Status:* Backlog

- **CL-12** *Current:* b31_risk_weight_tables.py:916-926 share=(0.55-prior)/ltv with 124C LTV that already includes prior; own 30k, third-party prior 30k, value 100k: RWA 20,000 (should be 10,000). is_junior fires on pari-passu (:645,:694).
- *Required:* PS1/26 Art. 124F(2)(a)/(b), 124G(2), 124I(3): reductions and junior weights apply to charges 'not held by the institution', with pari-passu proportioning.
- *Fix:* Amount columns: third-party prior, third-party pari passu, own prior, own pari passu. Compute the band from value and own EAD, never the 124C LTV; junior triggers read third-party prior only.
- *Verification (confirmed):* Re-ran t21: under the input contract (LTV includes prior charges), share=(0.55-prior)/ltv gives RW 0.667 / 20,000 against a correct 0.333 / 10,000. is_junior also fires on pari-passu and own-held charges, which 124I(3) excludes. A defect-pinning test exists (test_b31_re_junior_charges.py:313-329). If the LTV excludes prior charges instead, the LTV bands understate.
- **RE-08** *Current:* b31_risk_weight_tables.py:916-928 share=(0.55-prior)/ltv with stacked ltv (input-schemas.md:499-500). Measured 200k junior, V 1m, prior 500k: RW 0.7107, RWA 142,143. CRR ignores prior charges.
- *Required:* PS1/26 Art. 124F(2)(a)/(b), 124H(2): 55% of value reduced by external prior charges; pari-passu product formula; Art. 124C(3) stacked LTV for 124G/124I.
- *Fix:* share=(0.55-p_ext)/(ltv-p_all); add pari-passu external/total fields; split own vs external prior; record CRR Art.125(2)(d) reading. Test 0.6125 / 122,500; pari-passu 73,750.
- *Verification (confirmed):* Measured own 200k, V 1m, external prior 0.5, stacked LTV 0.7 -> 0.7107/142,143. Art. 124F(2) is in money terms and only for charges not held by the institution. The 124C(3) stacked LTV serves 124G/124I only. Correct share 0.25 -> 0.6125/122,500. The CRR leg is a design decision, not a defect. Pari passu unrepresented, which is conservative.
- **SF-11** *Current:* re_split/params.py:43-46 and splitter.py:405-409 compute the cap as max(0, 0.55 minus prior_charge_ltv), which the schema documents as covering pari passu. Own 30 of a 150 pari-passu loan on 200: eligible 0 vs 22; RWA 30.0 vs 12.4 (code-read).
- *Required:* PS1/26 Art. 124F(2)(b): the 55% is reduced by the product of 55% value and other pari-passu charges divided by all pari-passu charges, not by subtraction. Also Art. 124C(3) for the LTV.
- *Fix:* Split the input into prior_charge_ahead_ltv and pari_passu_others plus an own-share input. Implement the (2)(a)/(b) formula in re_split/params.py. Cross-check with the real-estate dimension.
- *Verification (rescoped):* Demonstrated: the documented convention prior_charge_ltv=0.6 gives RWA 30.0 against Art. 124F(2)(b)'s 12.4, and RE002 fires, so it is not silent. An exact workaround exists (pro-rate the value to the own share). Scope is wider than claimed: 124H(2)(b) too, and pari passu charges set is_junior, wrongly triggering the 124G(2)/124I(3) junior weights.

#### P1.450 — Real-estate attributes ignore collateral_links

*Review IDs:* CL-13 · *Regime:* Both · *Effect:* RWA overstated · *Size:* M · *Status:* Backlog

- *Current:* enrich.py:593-698,753-811 use only the collateral row's own beneficiary; linked loan B gets ltv null and property value 0. B31 RW 0.56 vs 0.4133 (total 69,333 vs 62,000).
- *Required:* PS1/26 Art. 193(7): subdivide an item across the exposures it covers; Art. 124F/H apply per exposure against the securing property value.
- *Fix:* Expand links before hierarchy property enrichment so every linked beneficiary gets LTV, qualifying and prior-charge attributes plus a share of property value.
- *Verification (confirmed):* collateral_links is read only in CRM, never in hierarchy property enrichment. Re-ran t12: in B31 linked loan B has ltv null and RW 0.56, total 69,333 vs 62,000 at counterparty level. CRR matches only by accident (null LTV filled with 0.0, see CL-08). Link splitting is on by default (config.py:738).

#### P1.451 — Null collateral currency: no FX conversion and no Hfx, silently

*Review IDs:* CL-14 · *Regime:* Both · *Effect:* Either direction · *Size:* S · *Status:* In this PR

- *Current:* haircuts.py:249-263: null coll_ccy makes the mismatch test null, so Hfx is 0; value left unconverted. EUR loan, null-currency cash 100k is credited as GBP 100k, no warning (CRM020 exists only for life policies).
- *Required:* CRR Art. 223(2) 'Hfx = the volatility adjustment appropriate to currency mismatch'; PS1/26 Art. 230(1)(b). An unknown currency cannot prove no mismatch.
- *Fix:* Treat a null currency as a mismatch (apply Hfx) and raise a rolled-up CRM026 warning.
- *Verification (confirmed):* coalesce(original_currency, currency) null makes the mismatch test null, so Hfx is 0. fx/converter.py leaves the value unconverted. Life policies already have the conservative CRM020 precedent; ordinary collateral has no warning. An unknown currency cannot establish that there is no mismatch.

#### P1.452 — MOF sub-limit rows inherit the parent's CCF modifiers instead of their own

*Review IDs:* CM-06, SF-08 · *Regime:* Both · *Effect:* Either direction · *Size:* M · *Status:* Backlog

- **CM-06** *Current:* facility_undrawn.py:767-775 reads only risk_type/limit/committed from subs; underlying_risk_type, is_obs_commitment, trade-LC, ccf_modelled come from parent (:585-599). Probe B31: LC sub 40% not 20%; cash sub under MLR parent 20% not 40%.
- *Required:* PS1/26 Art. 111(1)(c): commitment to issue an OBS item uses the lower of item and commitment CCF - a property of each sub-limit commitment.
- *Fix:* Select sub-level CCF modifiers in the waterfall and coalesce sub->parent on emitted rows; use effective lower-of CCF in waterfall ordering.
- *Verification (confirmed):* Probe reproduced (B31: LC sub 40% vs standalone 20%; cash sub under MLR-tagged parent 20% vs 40%). Subs supply only risk_type/limit/committed (facility_undrawn.py:767-775). Art. 111(1)(c) lower-of applies per commitment. The CRR IRB effect comes via the inherited trade-LC and ccf_modelled flags. Mixed direction; the overstated case is the realistic one.
- **SF-08** *Current:* Only risk_type, counterparty, limit and committed come from the sub (facility_undrawn.py:767-775, :855-867). Parent flags, dates, ccf_modelled, lgd and currency are kept. B31: a resi-commitment sub-line gets 40% (EAD 4.0), not 50% (5.0).
- *Required:* PS1/26 Art. 111(1)(b) Table A1 row 4(b): UK residential mortgage commitments 50%. CRR Art. 111(1)/Annex I MR/MLR split by original maturity. CRR Art. 166(8)-(10) trade-LC treatment follows the item.
- *Fix:* Select CCF-driving columns from the sub in sub_facilities and coalesce sub over parent on waterfall rows. Order the waterfall by the row's actual CCF.
- *Verification (confirmed):* Re-run (B31): a resi-commitment sub under an unflagged MOF parent gets 40% (EAD 4.0) instead of row 4(b) 50% (5.0). sub_facilities takes only risk_type, counterparty, limit and committed from the sub. Overstating pairings are as likely: a CRR 364-day OC sub under a 5y parent gets 50% instead of 20%, and parent ccf_modelled/is_revolving drive A-IRB eligibility. Direction is mixed.

#### P1.453 — Regime-invariant product map: shipping/customs/tax bonds and unsecured documentary credits wrong under CRR

*Review IDs:* CM-07, TR-04 · *Regime:* CRR · *Effect:* RWA understated · *Size:* M · *Status:* In this PR

- **CM-07** *Current:* packs/common.py:874-898 'framework-invariant' map: DOCUMENTARY_CREDIT/TRADE_LC->MLR both regimes; no shipping/customs/tax keys; CCF spec :60 maps them MLR. Probe: CRR DOCUMENTARY_CREDIT -> 20%.
- *Required:* CRR Annex I 2: documentary credits issued or confirmed and shipping guarantees, customs and tax bonds are medium risk (50%) unless shipment collateral (3(a)(i)); PS1/26 Table A1 row 6(a),(d): 20%.
- *Fix:* Split obs_product_to_risk_type into crr/b31 pack CategoryMaps; add SHIPPING_GUARANTEE, CUSTOMS_BOND, TAX_BOND and shipment-secured documentary credit keys; read from resolved pack.
- *Verification (confirmed):* CRR Annex I 2(a)/2(b)(i): documentary credits issued or confirmed, shipping guarantees and customs/tax bonds are medium risk (50%). 3(a)(i) gives 20% only for shipment-collateralised credits or self-liquidating transactions. Engine maps DOCUMENTARY_CREDIT to 20% in both regimes. The CRR spec line 60 steers shipping/customs/tax to MLR. TRADE_LC at 20% is defensible.
- **TR-04** *Current:* packs/common.py:893-895 maps DOCUMENTARY_CREDIT and TRADE_LC -> MLR as 'framework-invariant' (ccf.py:97-102); CRR SA DC CCF 0.20 measured.
- *Required:* CRR Annex I 2(a): 'documentary credits issued or confirmed' = medium risk 50%; only 3(a)(i) 'in which underlying shipment acts as collateral' = 20%. PS1/26 Table A1 Row 6(a) 20% for all.
- *Fix:* CRR pack override: DOCUMENTARY_CREDIT->MR, TRADE_LC (self-liquidating) ->MLR; widen _firb_ccf_for_col 166(8)(b) gate to MR|MLR with trade flag so F-IRB stays 20%.
- *Verification (confirmed):* Verified verbatim: CRR Annex I 2(a) gives 50% (medium risk) to 'documentary credits issued or confirmed'. 20% under 3(a)(i) only applies where the shipment acts as collateral. The common pack maps DOCUMENTARY_CREDIT to MLR as 'framework-invariant'; a CRR SA probe gives 0.20. This is silent: no DQ016 because the product is mapped. B31 Row 6(a) 20% is correct. No plan item.

#### P1.454 — risk_type guidance mis-maps SBLCs, commitments and performance bonds

*Review IDs:* CM-08 · *Regime:* Both · *Effect:* RWA understated · *Size:* S · *Status:* In this PR

- *Current:* enums.py:464-478, input-schemas.md:252, standardised-approach.md:81, api/domain.md:229: MR='standby LCs, committed undrawn', MR_ISSUED='performance bonds...'; crr.md:186-187 MR/MLR maturity encoding, no OC; LR doc 0%; b31.py:386 'Row 6'.
- *Required:* Table A1 row 1(e) credit-substitute SBLC 100%; row 5 other commitments 40%; row 6(b) performance/tender bonds, warranties 20%; CRR Annex I 1(f) and 3(a)(ii) likewise.
- *Fix:* Rewrite enum docstrings and doc tables as per-regime product matrix (OC for ordinary commitments); B31 DQ warning when a commitment row carries FR/MR_ISSUED/MLR without underlying_risk_type.
- *Verification (confirmed):* All cited texts verified. Following them understates in two cases: a credit-substitute SBLC as MR gets 50% vs 100% (Table A1 1(e) / CRR 1(f)), and the CRR-guide MLR encoding of commitments up to one year gives 20% under B31 vs Row 5 40%. Some overstatements too (MR_ISSUED performance bonds; MR commitments under B31). b31.py:386 cites 'Row 6' for UCC; it is Row 7.

#### P1.455 — Committed facility with null limit silently yields no commitment exposure

*Review IDs:* CM-11, SF-12 · *Regime:* Both · *Effect:* RWA understated · *Size:* S · *Status:* In this PR

- **CM-11** *Current:* schemas.py:494 limit optional; null undrawn dropped by facility_undrawn.py:214; DQ016 (validation.py:1407-1431) only checks rows with an amount. Probe: committed OC facility, limit=None -> no row, no error.
- *Required:* PS1/26 Art. 111(1)(b) and glossary 'conversion factor': commitment extent determined by the advised limit; unknown limit cannot silently mean zero.
- *Fix:* DQ warning on facilities where committed and limit is null.
- *Verification (confirmed):* Probe reproduced: a committed OC facility with limit=None emits no row and no error in either regime. DQ016 tests only rows with an amount, and only for a null risk_type. The commitment is measured by the advised limit (glossary 'conversion factor'), so an unknown limit silently becomes zero. The fix is a DQ warning only; no number moves.
- **SF-12** *Current:* limit is optional (schemas.py:494). A null limit gives a null undrawn (facility_undrawn.py:389-391), dropped by the :214 filter; the run shows no warning.
- *Required:* CRR Art. 4(1)(56) / PS1/26 glossary: the extent of the commitment is determined by the advised limit. Unknown is not zero; the project accumulates DQ errors rather than dropping silently.
- *Fix:* Validation warning (new DQ code) for committed=True facilities with a null limit, excluding MOF parents, where null is meaningful.
- *Verification (confirmed):* Re-run (B31): a committed facility with a null limit emits only the loan row. The errors list holds only SA004 and CLS008, and no null-limit check exists (limit is covered only by the DQ012 negative-amount domain). The commitment is lost silently, against the error-accumulation convention. The fix is a DQ warning only, and no numbers move.

#### P1.456 — Aggregate guarantee cap repeated across beneficiary rows is double-counted; no shared-cap representation (G08)

*Review IDs:* GT-01 · *Regime:* Both · *Effect:* RWA understated · *Size:* M · *Status:* In this PR

- *Current:* guarantees.py:507-509 aggregates per (beneficiary, guarantor); guarantees are not in TABLE_UNIQUE_KEYS (schemas.py:2720) and have no link table. Cap 5 on two loans (8, 6): 10 covered, RWA CRR 9.0 / B31 7.0, no error.
- *Required:* Art. 233(1) both regimes: G is the amount the provider undertook to pay; Art. 213(1)(b) extent incontrovertible. Total cover must be ≤ 5 (20/7 + 15/7): RWA CRR 11.5 / B31 10.5.
- *Fix:* Add a guarantee_links M:N table (mirroring COLLATERAL_LINK_SCHEMA) or aggregate_cap_amount + cap_scope; allocate pro-rata per guarantee_reference after multi-level expansion; DQ warning on a repeated reference with no scope, defaulting to the conservative cap.
- *Verification (rescoped):* Reproduced the 10.0 cover (RWA CRR 9.0 / B31 7.0), but the probe reuses guarantee_reference, which the docs define as a unique identifier. The engine reads the input faithfully. The real gaps are that guarantees are missing from TABLE_UNIQUE_KEYS, so duplicates go unflagged, and that a shared cap across obligors in different counterparty or facility trees cannot be stated. Representation gap, not P0.

#### P1.457 — Percentage-plus-amount-cap guarantee: amount_covered overrides percentage instead of min()

*Review IDs:* GT-02 · *Regime:* Both · *Effect:* RWA understated · *Size:* S · *Status:* In this PR

- *Current:* guarantees.py:963-985 uses the percentage only when amount is null or 0. 50% capped at 5 on a loan of 8 is recognised as 5: RWA CRR 5.5 / B31 4.5, no warning.
- *Required:* Art. 233(1) CRR and PS1/26: G = the amount undertaken = min(0.5×8, 5) = 4, giving RWA CRR 6.0 / B31 5.2.
- *Fix:* In _resolve_guarantee_amount_expr take min_horizontal(pct×_crm_basis, amount) when both are present; update input-schemas.md; check tests pinning 'amount wins'.
- *Verification (rescoped):* Reproduced (5.0 cover, RWA CRR 5.5 / B31 4.5 against 6.0 / 5.2). 'Amount wins' is documented (input-schemas.md:578), so the engine behaves as specified. But all 17 rows of the main fixture and the docs example fill both fields, so where pct×E < amount it over-recognises. Change the contract to min() or warn. Design defect, P1.

#### P1.458 — Multi-guarantor non-beneficial redistribution is half-applied; RWEA can exceed unprotected

*Review IDs:* GT-09 · *Regime:* Both · *Effect:* RWA overstated · *Size:* M · *Status:* Backlog

- *Current:* guarantees.py:1242-1251 mixes CCF bases; :1298-1318 moves ead_after_collateral, but rw_adjustments.py:398-413 blends on the unmoved ead_final. Loan: CRR 91.67 / B31 81.67. Contingent: CRR 58.33, above unprotected 50.
- *Required:* CRR Art. 193(1): CRM must never raise RWEA; PS1/26 Art. 193(2A) allows disregarding protection. Correct: loan 75.0 / 65.0; contingent 37.5 / 32.5.
- *Fix:* Drop non-beneficial guarantors before pro-rata scaling, or redistribute on the CCF=100% basis and rewrite ead_final and the portions consistently; add an invariant test that guaranteed RWA ≤ unprotected RWA.
- *Verification (confirmed):* Reproduced the loan at 91.67 / 81.67 (A-only 75 / 65). The contingent is CRR 58.33 / B31 48.33 (A-only 37.5 / 32.5), and the CRR figure exceeds the unprotected 50. redistribute_non_beneficial moves ead_after_collateral, but the SA blend divides by the unmoved ead_final. That breaches CRR Art. 193(1); PS1/26 193(2A) permits disregarding B.

#### P1.459 — Collateral plus guarantee: cover fraction taken on the gross exposure wastes the guarantee

*Review IDs:* GT-10 · *Regime:* Both · *Effect:* RWA overstated · *Size:* M · *Status:* Backlog

- *Current:* guarantees.py:676-712 computes the fraction G/ead_for_crm (pre-collateral) and applies it to post-FCCM EAD. Loan 100, cash 60, guarantee 40: guaranteed 16, RWA CRR 32.0 / B31 28.8.
- *Required:* Art. 193(5) CRR and PS1/26: subdivide the exposure into parts covered by each CRM form and calculate separately. Guarantee part 40 gives RWA CRR 20.0 / B31 12.0.
- *Fix:* For SA rows size Eg = min(GA, E* on the CCF=100% basis) using a new ead_for_crm_after_collateral carrier from collateral.py; IRB unchanged.
- *Verification (confirmed):* Reproduced: loan 100 with cash 60 and guarantee 40 gives 16 guaranteed and RWA CRR 32.0 / B31 28.8. Art. 193(5), same text in both regimes, subdivides the exposure into parts per CRM form. Reading Art. 235 E as the FCCM E* gives the same answer. Either way the guarantee covers the 40 residual: RWA 20 / 12.

#### P1.460 — Demand deposit with null maturity nets fully against term loans

*Review IDs:* NT-03 · *Regime:* Both · *Effect:* RWA understated · *Size:* S · *Status:* In this PR

- *Current:* netting.py:243-254,321-330 leaves the residual null and haircuts.py:751 fills 10y, so no mismatch. Measured: null-maturity deposit 4,000 vs 2032 loan gives EAD 2,000; the same deposit dated overnight gives 6,000.
- *Required:* PS1/26 Art 238(1): netting protection maturity is the earlier of agreement termination and 'the date when the deposit ... can be withdrawn'. CRR Art 238(1)/237(1): under 3 months and shorter than the exposure is ineligible.
- *Fix:* netting.py: a null deposit maturity means on demand (t=0), kept per deposit through the pool min. Stay permissive only when the loan maturity is also null. Raise CRM002. Document maturity_date as the earliest withdrawal date; add an agreement termination_date later.
- *Verification (confirmed):* Re-measured: a null-maturity deposit nets in full (EAD 2,000), while the same deposit dated overnight gives 6,000 with CRM002, so the null is the most favourable input. PS1/26 Art. 238(1) takes the deposit's withdrawal date, and CRR Art. 238(1) the earliest termination date. Art. 237(1) then refuses relief. A current-account balance is naturally null. No plan item.

#### P1.461 — Output-floor S-TREA ignores netting on IRB/slotting rows

*Review IDs:* NT-05, RG-04 · *Regime:* Basel 3.1 · *Effect:* RWA overstated · *Size:* M · *Status:* Backlog

- **NT-05** *Current:* sa/calculator.py:139-149 sets sa_rwa = unreduced ead_final x SA RW. Measured: F-IRB 1,000,000 loan with a 200,000 netted deposit gives sa_rwa and s_trea 1,000,000. User cash collateral behaves the same.
- *Required:* PS1/26 Art 92(3A): S-TREA computed 'as if permission to use ... the IRB Approach has not been granted'. Under SA, Art 219(4) netting sets the exposure value, so SA-equivalent here is 800,000.
- *Fix:* Compute an SA-equivalent E* (max(0, ead_for_crm x (1+HE) - collateral_adjusted_value) x CCF) for IRB/slotting rows and have sa_rwa read it. Remove the 'floor basis unchanged' statement from the b31.py citation and crm.md. Hand off the broader collateral half.
- *Verification (rescoped):* Re-measured: sa_rwa and s_trea are 1,000,000 with or without netting, and the Art. 92(3A) reading is right. But this is the netting slice of regime-floor RG-04 (S-TREA ignores SA funded CRM on IRB rows; same sa_rwa = ead_final x RW carrier), already confirmed and folded into the P2.27 promotion. Add netting as a test case there.
- **RG-04** *Current:* sa/calculator.py:141-147 uses F-IRB gross ead_final. Measured: 1m loan, 500k cash: S-TREA 1m, floor binds, TREA 575,000; correct S-TREA 500k, TREA 410,683.27.
- *Required:* PS1/26 Art. 92(3A)(b)(ii): S-TREA as if IRB not permitted, so SA comprehensive method (Art. 223) exposure value applies.
- *Fix:* Part of RG-03: run SA haircut/E* for IRB rows into ead_sa_equivalent only; IRB LGD* path untouched.
- *Verification (confirmed):* Re-measured: F-IRB 1m with 500k cash gives sa_rwa 1,000,000, the floor binds and TREA is 575,000; the SA run gives ead_final 500,000, so the correct TREA is 410,683.27. Art.92(3A)(b)(ii) applies SA CRM. P2.27's prescribed fix covers CCF only, so this CRM half is new. Same carrier as RG-03.

#### P1.462 — FCSM election: netted deposits skip maturity mismatch; B31 routes netting via FCSM

*Review IDs:* NT-06 · *Regime:* Both · *Effect:* RWA understated · *Size:* M · *Status:* In this PR if time

- *Current:* simple_method.py treats NETTING_ cash as FCSM 0% cash. The Art 239(1) gate (:746-773) needs an exposure residual_maturity_years that is never present. Measured: 2y deposit vs 6y loan gives RWA 2,000 in both regimes; FCCM gives 4,525.16.
- *Required:* CRR Art 239(1): mismatched FCSM collateral 'does not qualify', so 6,000. PS1/26 defines netting as 'determining the exposure value in accordance with Article 219'; Art 238(1A)(a) and 239(2) apply CVAM, so 4,525.16.
- *Fix:* Pack Feature on_bs_netting_always_art219 (B31 on, CRR off): SIMPLE excludes NETTING_ rows from FCSM and keeps the E* reduction. Fix the FCSM gate to derive exposure T from maturity_date (general, cross-reference collateral review).
- *Verification (confirmed):* Re-measured: 2y deposit vs 6y loan gives 2,000 under SIMPLE (both regimes) against 4,525.16 under FCCM. The FCSM Art. 239(1) gate needs an exposure residual_maturity_years that no CRM-stage frame carries. CRR Art. 239(1) gives 6,000. PS1/26 Art. 238(1A)(a)/239(2) and the flowchart route netting to Art. 219 (4,525.16). The general FCSM gate is shared with the collateral review.

#### P1.463 — Child mapped to >1 facility consumes every parent's headroom

*Review IDs:* RC-01, RC-02, SF-03 · *Regime:* Both · *Effect:* Either direction · *Size:* S · *Status:* In this PR

- **RC-01** *Current:* facility_undrawn.py:291-312 + graph.py:358 dedup only (child,parent); loan 3m mapped to two sublimits under 20m umbrella: EAD 11.5m→10.0m both regimes, no error.
- *Required:* PS1/26 & CRR Art. 111(1): OBS exposure = nominal value x CCF; one drawing reduces the commitment's nominal once.
- *Fix:* Dedup child per aggregation root in facility_undrawn; child resolving to two different roots -> new HIE004 ERROR and conservative (no) reduction.
- *Verification (rescoped):* Mechanism reproduced (p1 2.5m->2.0m, p2 FCCY headroom 4m->1m, no error). But Doc A §11.2 says overlapping sublimits can cut capacity BELOW umbrella headroom, so the 11.5m 'correct' answer is not shown. What survives: a child double-mapped to independent facilities is malformed input with no DQ signal. Art. 111(1) sets no graph rule.
- **RC-02** *Current:* graph.py:205-217 unordered unique + :562-565 dict last-wins: same bundle gave RWA 4.3m or 3.5m across runs; cycle F1<->F2 anti-joined (facility_undrawn.py:396-401): EAD 2.25m→0.5m; no errors.
- *Required:* PS1/26 & CRR Art. 111(1): every committed facility's nominal enters exposure value; results must be reproducible (Doc B T57).
- *Fix:* validate_facility_graph in graph.py: HIE004 multi-parent (sorted deterministic tie-break), HIE005 cycle (break at smallest member as root), facility HIE003; unique(maintain_order=True).
- *Verification (rescoped):* Confirmed: root lookup for S->U1,S->U2 gave U1 19x / U2 21x in 40 calls; an F1<->F2 cycle drops both undrawn rows (EAD 2.25m->0.5m), with no error either way. Both shapes are malformed input and Art. 111(1) is a generic citation. It is a real reproducibility and DQ-control defect, but P1, not P0.
- **SF-03** *Current:* facility_undrawn.py:291-312 joins the loan to every mapping, then sums per root without (loan, root) dedup. G100 with REG and CCY both holding a 20 loan: headroom 60, not 80 (B31 EAD 24 vs 32). No multi-parent DQ check (schemas.py:2720).
- *Required:* CRR Art. 4(1)(56) / PS1/26 glossary: undrawn amount is measured against the advised limit, so one drawing reduces a given limit once.
- *Fix:* Add unique(subset=[child_ref, aggregation_facility]) before group_by in the loan and contingent aggregators. Add a validation warning for a child with more than one parent. Make graph.py's facility-edge unique deterministic (maintain_order).
- *Verification (rescoped):* Confirmed: same-root double mapping gives headroom 60 instead of 80 (B31 EAD 24 vs 32). No multi-parent check exists. But the shape is a DAG in a tree model (unify keeps the first parent; graph is last-wins). Distinct-root mapping overstates instead (case E). Bounded by double-mapped drawn x CCF. The key fix is the warning, so P1.

#### P1.464 — Unrated subsidiary silently inherits parent's internal PD and model

*Review IDs:* RC-04 · *Regime:* Both · *Effect:* RWA understated · *Size:* S · *Status:* Backlog

- *Current:* ratings.py:172-195 coalesces ultimate parent's internal_pd/model_id; unrated SUB: SA 1,000,000 → F-IRB 686,834 (CRR), 585,000 final (B31); no warning.
- *Required:* PS1/26 & CRR Art. 172(1)(d): 'each separate legal entity to which the institution is exposed shall be separately rated.'
- *Fix:* Config election inherit_parent_internal_rating default False; WARNING + internal_rating_source when used; update TestInheritanceTruthTable and docs. Owner sign-off (documented feature).
- *Verification (rescoped):* Reproduced: CRR F-IRB 686,834 and B31 585,000, against SA 1,000,000, with no warning. Art. 172(1)(d) is verbatim in both regimes, and the cited 171(1)/175(3) do not support inheritance. But input-schemas says 'rating and turnover inheritance', the spec and TestInheritanceTruthTable lock it, and SA fallback is not the IRB answer. Owner decision: P1.

#### P1.465 — Connected-client grouping single-level, first-membership-wins, no closure

*Review IDs:* RC-08 · *Regime:* Both · *Effect:* RWA understated · *Size:* M · *Status:* Backlog

- *Current:* enrich.py:507-531 unique(keep=first), no transitive closure, org control ignored. Nested G1→X→Y: RWA 825,000 vs 1,100,000 (both regimes); SME B31 825,000 vs 935,000.
- *Required:* CRR Art. 4(1)(39)(a): single risk where one 'directly or indirectly, has control'; thresholds by 'group of connected clients' (PS1/26 Art. 123/123A, CRR 123(c)).
- *Fix:* Union-find closure over lending edges (sorted, deterministic) in enrich.py; HIE006 WARNING on multi-membership; optional union of org control edges with opt-out.
- *Verification (rescoped):* Confirmed: single level, first membership wins. Nested G1->X->Y under CRR gives 825,000 against 1,100,000 flat. The B31 825k needs granularity off (p4 with granularity on gives 1.1m). Closure along control chains matches 4(1)(39)(a). The fix over-reaches: 4(1)(39) does not require merging two groups that share a member, so count the member toward each group.

#### P1.466 — Missing FX rate silently treated as 1:1

*Review IDs:* RC-11 · *Regime:* Both · *Effect:* Either direction · *Size:* S · *Status:* In this PR

- *Current:* fx/converter.py:124-160 otherwise(x) keeps source amounts; KWD 1,000,000 loan with no rate → EAD/RWA 1,000,000, currency 'KWD', no error. Pinned by test_fx_converter.py:219.
- *Required:* GBP thresholds (PS1/26 Art. 123 GBP 880k, 147(4C) GBP 440m, 153(4) GBP 44m) need reporting-currency amounts; Doc B T63 visible outcome.
- *Fix:* convert_resolved_frames collects unconverted non-base currencies across five frames; FX001 ERROR per currency with count/amount; fx_unconverted carrier.
- *Verification (rescoped):* Confirmed: converter.py otherwise(x), amounts kept and currency left unconverted, with no error code anywhere. The direction is not one-way. The pinned test case is ZAR, which is weaker than GBP, so keeping 1m ZAR as GBP overstates about 20x, while KWD understates. The defect is the silence, not a bias.

#### P1.467 — Null entity_type silently classified 'other' at 100%

*Review IDs:* RC-12 · *Regime:* Both · *Effect:* Either direction · *Size:* S · *Status:* In this PR

- *Current:* attributes.py:362-368 replace_strict default OTHER; null raises nothing (unknown → DQ006 warning). CQS6 corporate: 1,500,000 → 1,000,000.
- *Required:* PS1/26 Art. 112(2): assign exposures to classes per Table A2 criteria; corporate ECAI weights Art. 122 (both regimes).
- *Fix:* Null-value gate for classification-driving required columns (DQ001-family ERROR); UNKNOWN_FALLBACK branch reason so BR001 names rows; conservative fallback is owner decision.
- *Verification (rescoped):* Reproduced (p7): entity_type=None gives class other at RW 1.0 with errors [], and the obligor's ECAI rating is discarded. The direction depends on the true class: a CQS6 corporate is understated (1.5m->1.0m), a CQS1 corporate or an individual overstated. This is the same two-faced shape as the DQ005 unknown-counterparty reason in schemas.py. Not in plan.

#### P1.468 — B31 SME test uses assets fallback and strict < not in PS1/26 definition

*Review IDs:* RC-16 · *Regime:* Basel 3.1 · *Effect:* Either direction · *Size:* S · *Status:* In this PR

- *Current:* b31.py:632 sme_balance_sheet_threshold + attributes.py:503-504: null revenue, 10m assets → 85% (850,000) silently; revenue exactly 44,000,000 → 100%.
- *Required:* PS1/26 SME glossary: 'annual turnover of not more than GBP 44 million'; assets substitution only Art. 153(4) IRB, consolidated group, when revenue not meaningful.
- *Fix:* Assets branch behind CRR-only pack Feature; B31 inclusive bound via cited pack entry; null B31 revenue → not SME + CLS WARNING.
- *Verification (rescoped):* Confirmed: the b31 pack holds a EUR43m x 0.8732 balance-sheet threshold with no PS1/26 basis, and the test uses strict <. The glossary sets turnover only, 'not more than GBP 44 million'. The direction splits: null revenue with the assets fallback reaching 85% understates (P1), while strict < at exactly GBP 44m overstates and its fix is RWA-reducing (P2, needs sign-off).

#### P1.469 — Art. 124K(2) 100% residential ADC unreachable; equity-at-risk limb unrepresented

*Review IDs:* RE-02 · *Regime:* Basel 3.1 · *Effect:* RWA overstated · *Size:* S · *Status:* In this PR

- *Current:* b31_risk_weight_tables.py:728-749 reads is_presold; no producer (edges.py:1859 injects null, netting.py:371). Measured presold ADC 500k -> RW 1.50, RWA 750,000.
- *Required:* PS1/26 Art. 124K(2): 100% if prudent underwriting and (pre-sale/pre-lease contracts OR substantial borrower equity at risk).
- *Fix:* Propagate is_presold with RE-01; add adc_borrower_equity_at_risk and adc_prudent_underwriting attestations (null=not established). Test: B31 1.00 / 500,000; commercial stays 1.50.
- *Verification (confirmed):* No producer of is_presold (edges inject null; netting literal null). Measured construction loan plus collateral is_presold=True gives 1.50/750,000. Art. 124K(2) is permissive ('may assign 100%'), conditions (a) underwriting, (b)(i) pre-sale or (ii) equity at risk, quoted. Same root cause as RE-01, so fix them together.

#### P1.470 — 0.2% retail granularity limb enforced by default but absent from PS1/26 Art. 123A

*Review IDs:* RE-04 · *Regime:* Basel 3.1 · *Effect:* RWA overstated · *Size:* S · *Status:* In this PR

- *Current:* classify/attributes.py:697-740; packs/b31.py:1292-1296 cites 123A(1)(b)(ii); config.py:694-701 default True. Measured 10 NPs x 20k -> all corporate 1.00, RWA 200,000.
- *Required:* PS1/26 Art. 123A(1)(b)(ii) is only the GBP 880k aggregate test; (iii) 'significant number of exposures' is qualitative. No 0.2% limb.
- *Fix:* Default enforce_retail_granularity=False (optional firm method), fix/delete pack citation, update pinned tests (test_facility_share_granularity_denominator.py). Test B31 0.75 each, 150,000.
- *Verification (confirmed):* PS1/26 Art. 123A(1)(b)(ii) is verbatim the GBP 880k test; (iii) is qualitative; Appendix 1 has no 0.2% limb, so the pack citation is wrong (BCBS CRE20.66). Measured 10 natural persons x 20k: B31 all corporate 1.00/200,000; with the limb off, 0.75/150,000. Every portfolio under 500 obligors fails. Many fixtures and tests pin it (LESSONS C1/E1).

#### P1.471 — Mortgage-class rows with several properties take arbitrary first collateral row; mixed-use never split

*Review IDs:* RE-07 · *Regime:* Both · *Effect:* Either direction · *Size:* L · *Status:* Backlog

- *Current:* re_split/flagging.py:198-212 excludes mortgage classes; kernels/allocation.py:566-593 keep-first unsorted. Measured NP 500k, resi 600k + comm 400k: B31 100,000 or 300,000; CRR 175,000 or 500,000 by row order.
- *Required:* PS1/26 Art. 124(4) split by RRE/CRE value ratio; Art. 124F(1)(a) 55% of property value; CRR Art. 124(1) 'any part of an exposure'.
- *Fix:* Route multi-type mortgage rows through splitter; derive LTV = exposure/sum of values; all/any flag aggregation; deterministic sort. Test B31 180,000; CRR 183,000; two-resi case 88,250.
- *Verification (rescoped):* Keep-first order dependence re-measured: B31 193,500 vs 333,750 by row order (correct 180,000); two properties 80,000 vs 172,632. The mixed-use half is a documented limitation (D3.59; the user guide says pre-split). D3.59 is stale because the splitter handles corporates. New: undocumented, unwarned arbitrary-row attributes on mortgage-class rows with several properties.

#### P1.472 — Undrawn UK residential mortgage commitments get 40% unless manually flagged

*Review IDs:* RE-14 · *Regime:* Basel 3.1 · *Effect:* RWA understated · *Size:* S · *Status:* In this PR

- *Current:* ccf.py:756-800 applies row 4(b) only when is_uk_residential_mortgage_commitment=True; never derived. Measured B31 mortgage facility undrawn 100k, risk_type null -> CCF 0.40, EAD 40,000, RWA 8,000.
- *Required:* PS1/26 Art. 111(1) Table A1 row 4(b): UK residential mortgage commitments 50% (row 5 other commitments 40%).
- *Fix:* Under B31 derive flag for undrawn rows secured by residential RE (class or facility property collateral) unless explicitly False or CCF 10%/100%; DQ info note. Test CCF 0.50, EAD 50,000, RWA 10,000.
- *Verification (confirmed):* Measured B31 mortgage facility, undrawn 100k, risk_type null: CCF 0.40, EAD 40,000; flagged 0.50/50,000. Table A1 row 4(b) 50% vs row 5 40% quoted. The flag defaults False, is never derived, and is absent from docs/data-model/input-schemas.md. Derivation must respect 'UK' (no property-country column; cp country is a proxy only) and the 10%/100% carve-outs.

#### P1.262 — RRE exposures with no Art. 124E exception (e.g. corporates) default to not-materially-dependent

*Review IDs:* RE-15 · *Regime:* Basel 3.1 · *Effect:* RWA understated · *Size:* M · *Status:* In this PR if time

- *Current:* has_income_cover defaults False (hierarchy/enrich.py:693; classify/attributes.py:594-599). Measured non-SME corporate 400k on RRE 1m (LTV 0.4) -> B31 RW 0.20, RWA 80,000.
- *Required:* PS1/26 Art. 124E(1): RRE is materially dependent unless (a)-(e) exceptions; Art. 124E(6) CRE dependent unless own-use.
- *Fix:* As P1.262: B31 materially dependent where no engine-verifiable exception (non-NP, not social housing/coop/attested SPV) plus DQ warning. Test 124G 0.30 / 120,000; CRR 140,000 unchanged.
- *Verification (rescoped):* Understatement re-measured (corporate RRE LTV 0.4 -> 0.20/80,000) and is P1.262. But the fix overshoots: the same row with is_income_producing=True -> corporate 1.00/400,000, not 124G 30%. Income rows skip the splitter and nothing reclassifies non-retail obligors. Defaulting to 'dependent' must also route rows to the 124G/124I class.

#### P1.263 — CRR Art. 126 50% gate inverted; owner-occupied CRE gets 100%

*Review IDs:* RE-17 · *Regime:* CRR · *Effect:* Either direction · *Size:* M · *Status:* In this PR

- *Current:* risk_weights.py:798-805 grants 50% only when has_income_cover (materially dependent) is True. Measured NP CRE row, has_income_cover False -> 1.00.
- *Required:* CRR Art. 126(2)(b): 50% only where repayment does not materially depend on property cash flows (Art. 126(3) derogation separate).
- *Fix:* As P1.263: separate CRR attestation crr_art_126_conditions_met; explicit Feature for 126(3) derogation. Test SME owner-occupied 400k/1m -> 0.50 / 200,000.
- *Verification (confirmed):* risk_weights.py:798-805 grants 50% only when materially dependent; CRR Art. 126(2)(b) quoted requires the opposite. 126(3) UK derogation makes the income-producing half derogation-dependent. Measured natural-person CRE not dependent -> 1.00. Existing P1.263. Side note: the CRR splitter's 1.5x rental-cover gate is not in the UK Art. 126 text fetched.

#### P1.473 — No primary-residence carrier; landlord's own home re-routed to Art. 124G

*Review IDs:* RE-18 · *Regime:* Basel 3.1 · *Effect:* RWA overstated · *Size:* S · *Status:* Backlog

- *Current:* classify/attributes.py:569-599 re-routes every NP RRE exposure when count>3; schemas.py:944-951 count 'including the financed one'. Measured count 5, 300k/500k -> 0.35 / 105,000.
- *Required:* PS1/26 Art. 124E(1)(a): single property that is obligor's primary residence not materially dependent; Art. 124E(2) qualifying property excludes primary residence.
- *Fix:* Add is_primary_residence (null=unknown); exclude primary-residence single-property exposures from count re-route; correct schema/docs. Test 0.245833 / 73,750; BTL stays 0.35.
- *Verification (confirmed):* Re-measured count 3 -> 0.2458/73,750, count 5 -> 0.35/105,000. Explicit False cannot override (explicit OR derived). Art. 124E(1)(a) primary-residence exception and 124E(2) 'is not the primary residence' quoted. The schema comment 'including the financed one' contradicts them. No primary-residence field exists in src.

#### P1.474 — S-TREA uses A-IRB own-estimate EAD instead of SA Art. 111 exposure value

*Review IDs:* RG-03 · *Regime:* Basel 3.1 · *Effect:* Either direction · *Size:* L · *Status:* Backlog

- *Current:* sa/calculator.py:141-147 sa_rwa = IRB ead_final x SA RW. Measured: 10m undrawn, own CCF 25%: S-TREA 2.5m, TREA 2,053,416.33; correct S-TREA 5m, TREA 2,875,000 (-821,583.67).
- *Required:* PS1/26 Art. 92(3A)(b)(ii): S-TREA calculated as if IRB permission not granted, i.e. SA Table A1 CCF exposure value.
- *Fix:* CRM stage computes ead_sa_equivalent (on-BS + sa_ccf_expression x off-BS, then SA funded CRM) for IRB/slotting rows; sa_rwa uses it; rebase P2.27 cols together; measure with P1.367/P1.212.
- *Verification (rescoped):* Mechanism confirmed (sa_rwa = IRB ead_final x SA RW). Not one-sided: my QRRE card probe (own CCF 60%) gives sa_rwa 9,000 vs SA-basis 1,500, so S-TREA is overstated 6x. P2.27 already records that col 0276 assumes EAD_SA==EAD_IRB and prescribes the engine recomputation. Promote it; do not re-file.

#### P1.475 — One flag conflates Art. 122(6) IG permission with Art. 122(8)(b) floor-only election

*Review IDs:* RG-06 · *Regime:* Basel 3.1 · *Effect:* Either direction · *Size:* M · *Status:* Backlog

- *Current:* config.py:716 use_investment_grade_assessment read at risk_weights.py:1229-1240 for all rows: floor election forces 65% on SA-routed corporates (1,000,000 -> 650,000), else floor overstated.
- *Required:* PS1/26 Art. 122(6): 65%/135% only with prior PRA permission; Art. 122(8)(b): floor-only election with notice for IRB-approach exposures.
- *Fix:* Split into sa_investment_grade_permission and output_floor_investment_grade_election; separate sa_floor_risk_weight for IRB rows feeds sa_rwa; deprecate old flag as alias.
- *Verification (rescoped):* Verified: one flag drives both SA-routed RWs and IRB rows' sa_rwa. Art.122(6) needs PRA permission; 122(8)(b) is a floor-only notice. Two-sided whichever way it is set: on gives SA IG 65% (understated) and non-IG 135% (overstated); off misprices S-TREA in reverse. The 122(6)+122(8)(a) combination is inexpressible. Not filed.

#### P1.476 — Share candidates dilute facility-level collateral/guarantees; losers' portions discarded

*Review IDs:* SF-07 · *Regime:* Both · *Effect:* RWA overstated · *Size:* M · *Status:* Backlog

- *Current:* crm/collateral.py:1343-1384 and guarantees.py:461-466 share protection over every row including N full-headroom candidates. _facility_share.py:305-320 drops losers without re-allocating. G10: only 6.25 of 10 cash recognised; B31 RWA 11.825 vs 8.6.
- *Required:* PS1/26 Art. 193(7): allocate each portion of eligible collateral to an exposure it covers without double-counting. Portions given to deleted rows are recognised nowhere. Not double-counted, so T59's understatement risk is refuted.
- *Fix:* Weight candidates 1/candidate_count in the facility subtree denominators (collateral, guarantees, provisions), and give each candidate the single-slot share. Carry candidate_count from the hierarchy.
- *Verification (confirmed):* Re-measured G10 (B31): the collateral basis 4+4+12+12 counts the undrawn slot twice, so only 6.25 of 10 cash is recognised and RWA is 11.825 against 8.6. CRM has no candidate awareness. This does not breach Art. 193(7), since under-recognition is allowed. It still breaks the fan-out's own 'as if this member drew the whole line' intent, has no workaround and grows with N.

#### P1.477 — B31 Art 162(3)(e) one-day M floor for self-liquidating trade disabled

*Review IDs:* TR-05 · *Regime:* Basel 3.1 · *Effect:* RWA overstated · *Size:* S · *Status:* In this PR

- *Current:* packs/b31.py:108-114 one_day_maturity_floor=False; irb/transforms.py:1054-1077 derivation off; pinned by test_maturity_double_default_features.py:31. B31 6m DC M=1.0 measured.
- *Required:* PS1/26 Art 162(3): M at least one day for '(e) self-liquidating trade finance transactions ... with a residual maturity of less than one year'.
- *Fix:* Enable Feature in b31 pack citing 162(3)(e); regime-correct boundary (B31 '<1', CRR '<=1') via pack scalar; update pin test.
- *Verification (rescoped):* The premise holds: PS1/26 162(3)(e) exists, and the B31 Feature is off and pinned. The fix is unsafe as proposed. The engine sets M to exactly 1/365, not a floor (TR-11), so enabling it imports an understatement. The reviewer's expected 62,150.55 is that collapsed value; with M=0.5 the rule gives 71,976.75 (today 81,857.10). B31 must use a strict '<1y' boundary.

## Refuted findings

- **CL-22** Null issuer_counterparty_reference is permissive with no warning — Treating null as permissive is deliberate and documented (schemas.py:1087-1096). The proposed warning would fire on every security row: 21 of 21 fixture bond/equity rows have a null issuer reference, and most issuers are not counterparties at all. An always-firing alarm has no discriminating power (LESSONS B9), and no understatement was measured.
- **GT-12** Principal-only cover cannot be stated; percentage applied to EAD including accrued interest — The measurement is right but the premise is wrong. percentage_covered is documented as a fraction of the exposure, and the exposure includes interest. Art. 215(1)(c)(ii) puts the value adjustment on the institution. amount_covered expresses it, and the reviewer's own amount control gives the correct 60 / 40. Principal-only cover is representable; at most a docs note.

## Product coverage register

Status per product family as traced through the current code (catalogue IDs from the
second reference, section 3). *silent misroute* means the product can be input but is
forced into an unsuitable treatment, lost, or relieved without a visible outcome.

| Family | Catalogue ID | Product | Status | Note |
|---|---|---|---|---|
| Commitments, CCFs and facility lifecycle | 005 | Credit and store card | supported conditional | UCC retail line via risk_type LR (B31 10%) only when committed=True (CM-01). |
| Commitments, CCFs and facility lifecycle | 006 | Charge card | supported conditional | Needs advised/shadow limit; null limit dropped silently (CM-11). |
| Commitments, CCFs and facility lifecycle | 007 | Arranged overdraft | supported conditional | Facility plus loan; UCC via LR, committed=False trap (CM-01). |
| Commitments, CCFs and facility lifecycle | 008 | Unarranged overdraft | supported | Loan row without facility; full debit balance in exposure. |
| Commitments, CCFs and facility lifecycle | 020 | Revolving credit facility | supported conditional | Doc B 9.1 reproduces (B31 7.4m, CRR 7.7m); foreign-currency drawings mis-net headroom (CM-02). |
| Commitments, CCFs and facility lifecycle | 021 | Business overdraft | supported conditional | As 007; set-off via netting_agreement_reference. |
| Commitments, CCFs and facility lifecycle | 022 | Working capital and seasonal loan | supported conditional | No availability-date or clean-down inputs; limit must equal current commitment (CM-05). |
| Commitments, CCFs and facility lifecycle | 023 | Business credit or charge card | supported conditional | As 005/006. |
| Commitments, CCFs and facility lifecycle | 024 | Delayed draw term facility | silent misroute | Repaid or post-availability headroom recounted as commitment (CM-05, overstated). |
| Commitments, CCFs and facility lifecycle | 025 | Acquisition bridge finance | supported conditional | Committed bridge as OC (B31 40%); underwriting take-out needs its own row. |
| Commitments, CCFs and facility lifecycle | 027 | Capex and expansion facility | silent misroute | Staged non-revolving draws: same headroom defect as 024 (CM-05). |
| Commitments, CCFs and facility lifecycle | 033 | Accordion and incremental facility | supported conditional | Unaccepted accordion = committed=False (no exposure) correct once CM-01 semantics fixed; accepted increase raises limit. |
| Commitments, CCFs and facility lifecycle | 048 | Documentary LC issuance | supported conditional | B31 20% right; CRR DOCUMENTARY_CREDIT 20% even unsecured (CM-07); MOF LC sub-limit loses lower-of (CM-06). |
| Commitments, CCFs and facility lifecycle | 050 | Standby LC and demand guarantee | supported conditional | FR vs MLR expressible, but docs steer SBLCs to MR 50% (CM-08). |
| Commitments, CCFs and facility lifecycle | 051 | Tender, performance and advance payment bonds | supported conditional | Performance family right via obs_product; shipping/customs/tax bonds cannot be right in both regimes (CM-07). |
| Commitments, CCFs and facility lifecycle | 052 | Acceptances and avals | supported | ACCEPTANCE -> FR 100% both regimes; avals via risk_type FR. |
| Commitments, CCFs and facility lifecycle | 080 | Securities underwriting and NIF/RUF | supported conditional | NIF/RUF = MR (SA 50%); CRR F-IRB 75% only if is_obs_commitment=True on contingents (CM-09). |
| Shared / multi-borrower facilities, limits, MOF, syndication | 019 | Business term loan | supported conditional | Loan row correct; a facility record re-opens repaid headroom (SF-10). |
| Shared / multi-borrower facilities, limits, MOF, syndication | 026 | Acquisition term loan and LBO | supported conditional | Holdco obligor via counterparty; subordination via seniority; sponsor support only as guarantee rows. |
| Shared / multi-borrower facilities, limits, MOF, syndication | 028 | Multi option facility | supported conditional | Waterfall counts common headroom once (Doc B 9.5 ok); defects SF-02, SF-04, SF-08, SF-09. |
| Shared / multi-borrower facilities, limits, MOF, syndication | 029 | Multi borrower facility | supported conditional | Correct only if every eligible borrower has a mapped instrument and no caps (SF-05, SF-06, SF-07). |
| Shared / multi-borrower facilities, limits, MOF, syndication | 030 | Multi currency facility | silent misroute | Headroom netted in raw currency units; commitment can vanish without warning (SF-01). |
| Shared / multi-borrower facilities, limits, MOF, syndication | 031 | Swingline and ancillary facility | supported conditional | Ancillary as MOF sub-line; fronting only approximated via participant guarantee rows (SF-13). |
| Shared / multi-borrower facilities, limits, MOF, syndication | 032 | Syndicated and club loan | supported conditional | User must pre-scale every amount incl. collateral; Art. 124F(2)(b) pari-passu gap (SF-11, SF-13). |
| Shared / multi-borrower facilities, limits, MOF, syndication | 034 | Mezzanine and unitranche debt | supported conditional | seniority=subordinated drives B31 150% / subordinated LGD; first-out/last-out AAL economics not representable. |
| Shared / multi-borrower facilities, limits, MOF, syndication | 093 | Funded participation | supported conditional | Book against underlying borrower; no grantor counterparty-risk leg or transfer-effectiveness input. |
| Shared / multi-borrower facilities, limits, MOF, syndication | 104 | Advisory, arranging and agency | supported conditional | No exposure created from roles; underwriting hold as facility; agent-system totals would overstate. |
| Shared / multi-borrower facilities, limits, MOF, syndication | T09/9.4 | Eligible borrower with no drawings | silent misroute | Omitted from member set; only a fabricated zero loan includes it (SF-05). |
| Shared / multi-borrower facilities, limits, MOF, syndication | T10/9.3 | Shared facility with borrower caps | silent misroute | Full headroom assigned to one member; overstated 20% (SF-06). |
| Shared / multi-borrower facilities, limits, MOF, syndication | T12 | Joint and several loan | supported conditional | One obligor per row; engine never duplicates principal; no co-obligor relation. |
| Shared / multi-borrower facilities, limits, MOF, syndication | T15 | MOF plus shared borrowers | silent misroute | Waterfall rows attributed to sub owner only (SF-04). |
| Shared / multi-borrower facilities, limits, MOF, syndication | T16 | Overlapping global/regional/currency caps | silent misroute | Root double-count (SF-03) or duplicated headroom across roots (SF-09); no multi-parent warning. |
| Shared / multi-borrower facilities, limits, MOF, syndication | T17 | Independent facilities under one reporting parent | supported conditional | Counted once, unless the parent facility is committed=False (SF-02). |
| Shared / multi-borrower facilities, limits, MOF, syndication | T20 | Multiple group memberships | supported | No row duplication; DQ004 on org multi-parent. |
| Shared / multi-borrower facilities, limits, MOF, syndication | T21 | FX limit movement | silent misroute | SF-01; over-limit excess not flagged (deferred, no capital effect). |
| Shared / multi-borrower facilities, limits, MOF, syndication | T23/9.12 | Syndicated own share | supported conditional | Works only by pre-scaling all amounts (SF-13). |
| Shared / multi-borrower facilities, limits, MOF, syndication | T24 | Fronting and unsettled participation | supported conditional | Approximation via guarantee rows; no settlement-date or reimbursement carrier. |
| Shared / multi-borrower facilities, limits, MOF, syndication | T59 | Protection scarcity across share candidates | supported conditional | No double-count; protection over-diluted and partly discarded (SF-07). |
| Shared / multi-borrower facilities, limits, MOF, syndication | T60 | Threshold crossing by candidates | supported conditional | Retail threshold and SME E* are drawn-only; QRRE aggregate path owned by P5.62. |
| Shared / multi-borrower facilities, limits, MOF, syndication | DocA-11.2 | Common limit with overlapping sublimits | supported conditional | Residual emitted for non-permitted use, overstated (SF-09). |
| On-balance-sheet netting and cash pooling | 011 | Offset / current-account mortgage (netting aspect) | supported conditional | Capital netting only if the netting reference is set; works for SA/F-IRB. Lost for A-IRB retail (NT-04). B31 124C(2) pledged-deposit LTV not representable (NT-08). |
| On-balance-sheet netting and cash pooling | 071 | Nostro / correspondent balance | supported conditional | Vostro entered as a negative-drawn loan with a reference nets the nostro for the same institution counterparty. Both sides on demand are treated as matched. |
| On-balance-sheet netting and cash pooling | 096 | Current / savings / term deposit | supported | No reference: DQ010, clamped to 0, no exposure. With a reference: pool source. Null maturity treated permissively (NT-03). |
| On-balance-sheet netting and cash pooling | 097 | Escrow / trust / client-money account | supported conditional | Correct only if the user leaves the reference null. No fiduciary-capacity flag or validation prevents netting a trust balance. |
| On-balance-sheet netting and cash pooling | 098 | Physical cash concentration | supported conditional | User inputs post-sweep legal balances. Header account is an ordinary loan/deposit; intercompany claims correctly excluded. Intraday bridge balances not modelled. |
| On-balance-sheet netting and cash pooling | 099 | Notional cash pool | silent misroute | Pool id as netting reference nets across participants with only a CRM016 warning (NT-01). Null-CP participants also net (NT-02). |
| On-balance-sheet netting and cash pooling | 100 | Payments clearing / intraday credit | not applicable | Not a netting product. Intraday overdrafts and prefunding are ordinary short-term exposures outside this dimension. |
| On-balance-sheet netting and cash pooling | T41 | Separate-company pool without qualifying rights | silent misroute | Measured: B overdraft 6,000 becomes EAD 2,000 in both regimes (NT-01). |
| On-balance-sheet netting and cash pooling | T42 | Same-counterparty loan/deposit netting | supported | Measured 6,000 to 2,000. CRR same-currency only; B31 H_fx 8% at 10 days. Gaps for A-IRB/slotting (NT-04) and FCSM (NT-06). |
| On-balance-sheet netting and cash pooling | T43 | Null counterparty under shared netting reference | silent misroute | Relief applied with DQ001+CRM016 warnings (NT-02). |
| On-balance-sheet netting and cash pooling | T44 | Netting with undrawn and contingent siblings | supported | Only exposure_type loan with on_bs_for_ead>0 benefits (netting.py:262-274). Facility headroom side effect is NT-07. |
| On-balance-sheet netting and cash pooling | FX | Currency mismatch on netted deposits | supported | CRR Art 219 same-currency only (CRM003). B31 Art 219(2) Table 4 H_fx at 10 BD. Non-daily MTM scale-up open as P1.388; RUNS coverage P1.386. |
| On-balance-sheet netting and cash pooling | MM | Maturity mismatch on netted deposits | supported conditional | Art 237-239 via synthetic row (P1.241). Gaps: null deposit maturity (NT-03), no agreement termination date, FCSM path (NT-06). |
| On-balance-sheet netting and cash pooling | SEP | Separation from derivative close-out and SFT master netting | supported | CCR/SFT rows are exposure_type ccr_netting_set with no reference, so they cannot source or receive on-BS netting. Art 196/220 netting stays in the SFT/CCR engines. |
| Collateral and security | 018 | Lombard and bespoke wealth lending | supported conditional | Bonds/listed equity OK with flags; fund units unrepresentable (CL-19); art/yachts other_physical F-IRB only; margin lending via SFT engine. |
| Collateral and security | 044 | Inventory and warehouse finance | supported conditional | inventory maps to other_physical, F-IRB with Art. 199(6) attestation; SA no relief (correct); duplicate pledges undetected (CL-03). |
| Collateral and security | 5.1-cash-own | Cash with lending bank | supported | 0% haircut / LGDS 0%; maturity_date ignored for mismatch (CL-02). |
| Collateral and security | 5.1-cash-3p | Deposit with third-party bank | supported conditional | SA RW substitution works; F-IRB gives zero benefit (CL-18); no Art. 212 attestation (CL-20). |
| Collateral and security | 5.1-debt | Debt securities | silent misroute | SA correct; F-IRB treats canonical 'bond' as non-financial (CL-11); unknown-issuer bond recognised on SA via flag (CL-01). |
| Collateral and security | 5.1-equity | Listed equities | supported conditional | is_main_index / is_listed flags with conservative nulls; PS6/26 index lists are user-supplied. |
| Collateral and security | 5.1-ciu | Fund units / CIU | silent misroute | No type; mapped to equity or 'other' (CL-19). |
| Collateral and security | 5.1-rre | Residential property | supported conditional | B31 loan-split works but prior charges double-counted (CL-12); F-IRB ignores prior claims (CL-05); CRR ignores is_qualifying_re=False (CL-07). |
| Collateral and security | 5.1-cre | Commercial and mixed-use property | supported conditional | 124H(3) LTV overwrite (CL-10); mixed RE per D3.59; F-IRB prior claims ignored (CL-05). |
| Collateral and security | 5.1-receivables | Receivables | supported conditional | F-IRB with attestation and 1-year original-maturity cap; SA none, except the flag bug (CL-01). |
| Collateral and security | 5.1-inventory | Inventory and commodities | supported conditional | other_physical; F-IRB attested only. |
| Collateral and security | 5.1-equipment | Equipment and vehicles | supported conditional | other_physical; F-IRB attested; Art. 211 lease route supported. |
| Collateral and security | 5.1-ships | Ships and aircraft | supported conditional | other_physical collateral; object finance itself routed elsewhere (slotting). |
| Collateral and security | 5.1-agri | Agricultural assets | supported conditional | Land as real_estate, crops and livestock as other_physical. |
| Collateral and security | 5.1-ip | IP and contractual rights | supported conditional | Only via 'other' (treated as other_physical) with attestation; not physical collateral, so the firm must not attest. |
| Collateral and security | 5.1-fundcalls | Fund commitments and distributions | supported conditional | Only as receivables with F-IRB attestation. |
| Collateral and security | 5.1-life | Life policy | supported | Art. 232(3) RW mapping with CRM020; no Art. 212 attestation (CL-20); a flagged policy zeroes RWA (CL-01). |
| Collateral and security | 5.1-groupshares | Shares in borrower or group company | supported conditional | CRM015 only when issuer_counterparty_reference is populated (CL-22). |
| Collateral and security | T25/9.6 | One security pool, two loans, per-link cap | supported | Measured: A 5, B 1, total 6; cap respected. |
| Collateral and security | T27/9.7 | Competing collateral items | supported | Most-constrained tie-break: Y to A 5, X to B 5. |
| Collateral and security | T26 | Duplicate asset IDs | silent misroute | Full value credited per row; total RWA 0 instead of 100,000; no DQ (CL-03). |
| Collateral and security | T28/11.5 | Third-party asset supporting only A | supported | Counterparty and parent pledges do not leak via org or lending groups (measured). |
| Collateral and security | T29/9.8/11.4 | Prior and pari-passu external liens | silent misroute | SA single scalar double-counted (CL-12); F-IRB ignored (CL-05); 124H(3) LTV overwrite (CL-10). |
| Collateral and security | T30 | Unperfected or legally unknown security | silent misroute | SA financial and F-IRB non-financial need attestation; F-IRB financial (CL-06), CRR RE (CL-07) and OFCP (CL-20) do not; B31 RE null is P1.292. |
| Collateral and security | T31 | Valuation fall, FX and maturity mismatch | silent misroute | maturity_date ignored (CL-02); null currency (CL-14); no staleness control (CL-15); B31 non-financial Hfx missing (CL-09). |
| Collateral and security | T32 | Shared loan, derivative and SFT collateral | silent misroute | Loan collateral zeroes CCR/SFT EAD (CL-04); no cross-table conservation (CL-16). |
| Collateral and security | 11.14 | Dependent collateral (property, owner shares, rents) | supported conditional | Additive unless the issuer reference triggers CRM015; no dependency record (deferred). |
| Collateral and security | G07 | Asset vs security-interest identity | supported conditional | M:N links with per-link caps work; no security agreement, aggregate cap or release dates (CL-17 / deferred). |
| Guarantees, credit derivatives and risk transfer | 035 | Government-supported business loan (GGS / CBILS / RLS / UKEF) | supported conditional | Sovereign guarantor with pct 0.7 gives RWA 30 on 100 in both regimes; borrower keeps 30%. Scheme portfolio caps hit GT-01; pct+cap hits GT-02. |
| Guarantees, credit derivatives and risk transfer | 086 | CDS / TRS as purchased protection | silent misroute | protection_type credit_derivative. Restructuring haircut gaps (GT-05, GT-06); B31 216(3) derogation missing (GT-13); TRS 204(2) and 216(2) mismatch not modelled. |
| Guarantees, credit derivatives and risk transfer | 094 | Unfunded risk participation (received / provided) | supported conditional | Received: guarantee from the participant; portfolio caps hit GT-01. Provided: contingent with risk_type FR; a DQ warning fires if risk_type and obs_product are both null. |
| Guarantees, credit derivatives and risk transfer | 095 | Credit-linked note / synthetic transfer | supported conditional | Art. 218 cash treatment only with is_own_issued_cln=True (CRM019 otherwise). Tranched CLN or synthetic securitisation needs Chapter 5 (GT-03, P7.4). |
| Guarantees, credit derivatives and risk transfer | 105 | Insurance distribution / premium finance | supported conditional | Premium loan is an ordinary exposure; the insurer refund is not CRM. Life policies use Art. 232 life_insurance collateral; insurer guarantors see GT-14. |
| Guarantees, credit derivatives and risk transfer | 6.2-pool | Pool guarantee across borrowers (G08, Doc A 11.7) | silent misroute | Repeated rows duplicate the cap (GT-01). A single-borrower pool via beneficiary_type=counterparty is correct: 20/7 and 15/7, RWA 11.5 / 10.5. |
| Guarantees, credit derivatives and risk transfer | 6.2-facility | Facility-level guarantee over loans and undrawn | supported | Pro-rata by post-CCF EAD, Σ allocation = G, no double count; allocation basis deferred. |
| Guarantees, credit derivatives and risk transfer | 6.2-prorata | Pro-rata percentage guarantee | supported | pct × CCF=100% basis, CCF re-applied (Art. 235(1)). |
| Guarantees, credit derivatives and risk transfer | 6.2-pctcap | Percentage plus amount cap | silent misroute | Amount overrides percentage (GT-02). |
| Guarantees, credit derivatives and risk transfer | 6.2-firstloss | First-loss / tranched guarantee (T38) | silent misroute | Substitution applied to the mezzanine band, contrary to Art. 234 / 235(2) (GT-03). |
| Guarantees, credit derivatives and risk transfer | 6.2-tci | Trade credit insurance with deductible | silent misroute | No deductible field; B31 Art. 234 'shall' treat as tranched (GT-04). |
| Guarantees, credit derivatives and risk transfer | 6.2-counter | Counter-guarantee chain (T39) | silent misroute | beneficiary_type='guarantee' rows silently dropped (conservative); no Art. 214 path (GT-11, P7.5). |
| Guarantees, credit derivatives and risk transfer | 6.2-cross | Cross-guarantee cycle (T39) | supported | Single-level resolution, no recursion; guarantor and obligor identities kept. |
| Guarantees, credit derivatives and risk transfer | 6.1-comfort | Letter of comfort / keepwell | silent misroute | guarantee_type ignored, so full substitution (GT-07). |
| Guarantees, credit derivatives and risk transfer | 6.2-personal | Natural-person guarantor | explicit reject | CRM013 on SA, slotting and F-IRB in both regimes (P1.384); A-IRB limb open (P1.394, P1.395). |
| Guarantees, credit derivatives and risk transfer | 6.2-parent | Parent / unrated corporate guarantor | supported conditional | Rated parent eligible; unrated corporate rejected with CRM013; intragroup dropped on consolidated runs; B31 internal-rating limb P1.397. |
| Guarantees, credit derivatives and risk transfer | T36 | Expired / revocable / conditional / unknown-term protection | supported conditional | Expired zeroed (Art. 237(1)); cancel/change flags give CRM012; null inputs silently permissive (GT-08); Rule 4.11 grandfathering open (P1.143). |
| Guarantees, credit derivatives and risk transfer | T35 | Currency and maturity mismatch on unfunded protection | supported | 8% Hfx on amount and pct; Art. 237(1)/(2)(a)/(b) gates and 239(3) scaling in both regimes. |
| Guarantees, credit derivatives and risk transfer | T37 | Guarantee plus collateral overlap | supported conditional | No double recognition, but the guarantee is under-recognised against Art. 193(5) (GT-10). |
| Guarantees, credit derivatives and risk transfer | T33-multi | Multiple guarantors incl. non-beneficial | silent misroute | Half-applied redistribution overstates; can exceed unprotected RWEA (GT-09). |
| Guarantees, credit derivatives and risk transfer | T34 | Principal-only cover | supported conditional | Correct in amount form; percentage form covers accrued interest (GT-12). |
| Guarantees, credit derivatives and risk transfer | T40 | Partial government / insured cover | supported conditional | Borrower liability retained on the __REM row; exclusions not represented; caps see GT-01 / GT-02. |
| Guarantees, credit derivatives and risk transfer | DD | Double default (CRR only) | supported conditional | Election off by default; gated off in B31 by the double_default_treatment Feature; eligibility defects P1.203. |
| Retail banking and real estate | 001 | Personal instalment loan | silent misroute | B31 non-regulatory NP reclassified corporate (RE-03); 0.2% limb (RE-04); CRR correct |
| Retail banking and real estate | 002 | Debt consolidation loan | supported conditional | Feed must exclude settled debts; no duplicate-exposure control |
| Retail banking and real estate | 003 | Point-of-sale finance / BNPL | supported conditional | Loan to natural person; merchant recourse via guarantee input |
| Retail banking and real estate | 004 | Student / professional loan | supported conditional | Art. 123A(1)(b)(i) product type fine; government scheme via guarantee |
| Retail banking and real estate | 009 | Owner-occupied mortgage | supported conditional | Needs is_qualifying_re (P1.292), single property (RE-07), property_ltv (RE-10), primary-residence (RE-18) |
| Retail banking and real estate | 010 | Interest-only mortgage | supported conditional | No SA distinction required; same conditions as 009 |
| Retail banking and real estate | 011 | Offset / current-account mortgage | supported conditional | Not netted unless netting_agreement_reference set; LTV user-supplied |
| Retail banking and real estate | 012 | Second charge / further advance | silent misroute | Stacked-LTV denominator; pari passu and own charges unrepresented (RE-08) |
| Retail banking and real estate | 013 | Buy-to-let mortgage | supported conditional | NP within three-property limit -> 124F correct; company BTL defaults non-dependent (RE-15/P1.262) |
| Retail banking and real estate | 014 | Bridging and self-build loan | silent misroute | Self-build valuation and non-self-build NP construction unrepresented (RE-19); corporate ADC flag gap (RE-01) |
| Retail banking and real estate | 015 | Lifetime / equity release mortgage | supported conditional | Roll-up via drawn+interest; drawdown reserve needs mortgage-commitment flag (RE-14) |
| Retail banking and real estate | 016 | Retirement interest-only mortgage | supported conditional | Same treatment and conditions as 009 |
| Retail banking and real estate | 059 | Owner-occupied commercial property | silent misroute | B31 124H fine; CRR 100% instead of 50% (RE-17/P1.263) |
| Retail banking and real estate | 060 | Investment commercial real estate | supported conditional | Requires is_income_producing=True; null routes to 124H (P1.262) |
| Retail banking and real estate | 061 | Land development and construction | silent misroute | Collateral ADC flag dropped (RE-01); presold 100% unreachable (RE-02) |
| Retail banking and real estate | 066 | Agricultural and livestock finance | supported conditional | Farmland as commercial RE; livestock as other physical collateral |
| Retail banking and real estate | T44 | Retail threshold across bank entities | silent misroute | Scoped solo runs aggregate only the solo book (RE-12) |
| Retail banking and real estate | T46 | Mixed-use property | silent misroute | Mortgage-class rows not split; first collateral row wins (RE-07) |
| Retail banking and real estate | T47 | One loan secured on several properties | silent misroute | Keep-first attributes, order-dependent RW (RE-07) |
| Retail banking and real estate | T48 | Construction to completed transition | supported conditional | Phase flags are as-of inputs; no stale-tag retention found |
| Retail banking and real estate | 123B | Currency mismatch multiplier | silent misroute | Null income currency -> no multiplier (RE-05); scope and multi-currency gaps (RE-06) |
| Retail banking and real estate | A1-4b | UK residential mortgage commitment CCF | supported conditional | 50% only when manually flagged, else 40% (RE-14) |
| Retail banking and real estate | CRR125 | CRR residential 35% treatment | silent misroute | No CRR qualification gate (RE-09); null LTV -> 35% (RE-10) |
| Retail banking and real estate | P2A | Pillar 2A SME/infrastructure adjustments | not applicable | No Pillar 2 logic in engine; correctly outside Pillar 1 |
| Trade finance, receivables, ABL and leasing | 017 | Vehicle HP and PCP | supported conditional | Loan with balloon in drawn; GMFV residual only via other_residual_lease leg (degenerate 100%, P1.360); RV guarantee limb P1.300. |
| Trade finance, receivables, ABL and leasing | 036 | Recourse factoring | supported conditional | Loan to seller + receivables collateral (F-IRB); undrawn line needs risk_type FRC; purchased-receivable flag drops SA to 40% (TR-02). |
| Trade finance, receivables, ABL and leasing | 037 | Non-recourse factoring | supported conditional | Claim on debtor; IRB senior/sub/dilution subtypes; retail dilution formula wrong (TR-03); dilution M/EAD issues (TR-08/09). |
| Trade finance, receivables, ABL and leasing | 038 | Invoice discounting | supported conditional | Secured advance to seller with receivables collateral; F-IRB LGD 35%/20%; no SA relief (correct). |
| Trade finance, receivables, ABL and leasing | 039 | Selective invoice finance | supported conditional | Per-invoice loans; no duplicate-funding control (design only). |
| Trade finance, receivables, ABL and leasing | 040 | Receivables purchase programme | silent misroute | B31 IRB 40%/10% correct for F-IRB, but SA rows get 40% not Row 2(a) 100% and A-IRB own estimates leak (TR-02). |
| Trade finance, receivables, ABL and leasing | 041 | Payables finance / reverse factoring | supported conditional | Book loan to buyer as obligor; supplier recourse via guarantee/second row; discretionary programme committed=False. |
| Trade finance, receivables, ABL and leasing | 042 | Forfaiting | supported conditional | Claim on importer + avalising-bank guarantee; no AVAL key (TR-07); funded trade flag unavailable (TR-06). |
| Trade finance, receivables, ABL and leasing | 043 | Distributor and dealer finance | supported conditional | Loan to dealer; manufacturer support recognised only as Art 201/213-eligible guarantee. |
| Trade finance, receivables, ABL and leasing | 044 | Inventory and warehouse finance | supported conditional | Other physical collateral under F-IRB (Art 199(6)); SA no relief (correct). |
| Trade finance, receivables, ABL and leasing | 045 | Pre-shipment finance | supported | Ordinary corporate loan; but TR-01 leak can wrongly flag it trade if CP has a trade facility. |
| Trade finance, receivables, ABL and leasing | 046 | Post-shipment finance | supported conditional | Loan/purchased claim; loans cannot carry trade flag (TR-06); B31 162(3)(e) floor off (TR-05). |
| Trade finance, receivables, ABL and leasing | 047 | Import and trust receipt loan | supported conditional | Funded loan; 162(3) only via has_one_day_maturity_floor override; TR-05/TR-06; TR-01 leak spills relief to non-trade loans. |
| Trade finance, receivables, ABL and leasing | 049 | LC confirmation and discounting | supported conditional | Confirmation = contingent on issuing bank (T51 OK), 20% CCF; CRR non-collateralised DC should be 50% (TR-04); discounting leg lacks trade flag (TR-06). |
| Trade finance, receivables, ABL and leasing | 052 | Acceptances and avals | supported conditional | ACCEPTANCE->FR 100% both regimes; aval/endorsement have no key, B31 residual 50% with DQ016 (TR-07). |
| Trade finance, receivables, ABL and leasing | 053 | Asset based revolving lending | supported | Undrawn = contractual limit - drawn (facility_undrawn.py:385-392); no borrowing-base input can reduce commitment (T49 OK). |
| Trade finance, receivables, ABL and leasing | 054 | Equipment hire purchase | supported conditional | Instalment loan + other physical collateral; title-transfer/purchase-fee not modelled. |
| Trade finance, receivables, ABL and leasing | 055 | Finance lease | supported conditional | Drawn must arrive as discounted MLP (schemas.py:637-653); residual 1/t leg degenerate (P1.360/361); RV guarantee (P1.300). |
| Trade finance, receivables, ABL and leasing | 056 | Operating lease and contract hire | supported conditional | Owned asset as other_tangible 100% (Art 134(1)); rentals as receivable loans. |
| Trade finance, receivables, ABL and leasing | 057 | Sale and leaseback or HP back | supported conditional | Financing claim on seller-lessee; substance input-determined. |
| Trade finance, receivables, ABL and leasing | 058 | Dealer floorplan finance | supported conditional | Per-unit loans to dealer; manufacturer repurchase as guarantee if eligible; no per-asset lifecycle. |
| Derivatives (SA-CCR), CCPs, SFTs, settlement and CVA | 081 | FX forward and FX swap | supported conditional | FX notional converted; needs fx_rates for both legs or PFE silently 0 (CC-06); CRR alpha (CC-01). |
| Derivatives (SA-CCR), CCPs, SFTs, settlement and CVA | 082 | Interest rate swap, FRA, cap, floor | silent misroute | Cross-currency offset in IR add-on (CC-04); non-GBP amounts unconverted (CC-05); options need price fields. |
| Derivatives (SA-CCR), CCPs, SFTs, settlement and CVA | 083 | Cross currency swap | silent misroute | Must split into FX + IR legs; IR legs pooled across currencies (CC-04) and unconverted (CC-05). |
| Derivatives (SA-CCR), CCPs, SFTs, settlement and CVA | 084 | Equity option and equity swap | supported conditional | BS delta and index/single-name correlation work; GBP only (CC-05); specific WWR understated (CC-18). |
| Derivatives (SA-CCR), CCPs, SFTs, settlement and CVA | 085 | Commodity derivative | supported conditional | Needs commodity_type else add-on 0 (CC-06); energy set split, no climatic (CC-23). |
| Derivatives (SA-CCR), CCPs, SFTs, settlement and CVA | 086 | CDS and total return swap | supported conditional | Needs credit_quality (CC-06); bought protection via guarantee CRM; sold banking-book CDS as FR contingent on reference entity; WWR (CC-18). |
| Derivatives (SA-CCR), CCPs, SFTs, settlement and CVA | 087 | Cleared derivative | silent misroute | QCCP trade pin works; DF formula wrong (CC-10); non-trade QCCP exposures 2% and non-QCCP as institution (CC-11). |
| Derivatives (SA-CCR), CCPs, SFTs, settlement and CVA | 088 | Repo and reverse repo | silent misroute | FCCM single-trade GBP works; B31 haircuts (CC-12), ineligible/property collateral (CC-13), no MNA gate (CC-14), FX (CC-05), loan CRM reapplied (CC-07). |
| Derivatives (SA-CCR), CCPs, SFTs, settlement and CVA | 089 | Securities lending and borrowing | silent misroute | Same FCCM defects as 088; agent-lender indemnity not representable. |
| Derivatives (SA-CCR), CCPs, SFTs, settlement and CVA | 090 | Margin lending and prime brokerage | supported conditional | Via SFT bundle (treated repo-style M, CC-22) or loans with financial collateral. |
| Derivatives (SA-CCR), CCPs, SFTs, settlement and CVA | 091 | Collateral swap and collateral upgrade | silent misroute | Securities-vs-securities representable but ineligible security lent takes HE 0 (CC-13). |
| Derivatives (SA-CCR), CCPs, SFTs, settlement and CVA | 092 | Long settlement and failed trade | silent misroute | Long settlement via SA-CCR OK; failed trades routed to IRB/CRM (CC-08), non-DvP col 3 and buy-side losses lost (CC-09). |
| Derivatives (SA-CCR), CCPs, SFTs, settlement and CVA | 100 | Payments clearing and intraday credit | supported conditional | No product-specific rule; balances as loans, committed daylight lines as contingents, pre-funding as settlement-agent exposure. |
| Derivatives (SA-CCR), CCPs, SFTs, settlement and CVA | 101 | Merchant acquiring | supported conditional | Advances as loans, chargeback contingency as contingent with user-chosen risk type, reserves as linked cash collateral. |
| Derivatives (SA-CCR), CCPs, SFTs, settlement and CVA | 102 | Custody and securities agency | supported conditional | Overdrafts as loans; settlement credit hits failed-trade defects (CC-08/09); indemnified agency lending not representable. |
| Derivatives (SA-CCR), CCPs, SFTs, settlement and CVA | 103 | Wealth management and brokerage | supported conditional | Lombard loans with financial collateral; margin financing as SFT (CC-22); held structured products as investments. |
| Investments, specialised lending and specialist products | 062 | Project and infrastructure finance | silent misroute | B31 SA phase dropped (IV-01); mezzanine not 150% (IV-03); null slotting grade 115% (IV-09). CRR correct. |
| Investments, specialised lending and specialist products | 063 | Shipping, aviation, object finance | supported conditional | Needs SL row object_finance: B31 SA 100%/rated Art. 122(2); slotting. Else corporate. |
| Investments, specialised lending and specialist products | 064 | Commodity and structured trade finance | supported conditional | commodities_finance SL row; trade-LC short-term windows supported. |
| Investments, specialised lending and specialist products | 065 | Reserve based lending | supported conditional | Corporate exposure; reserves give no CRM relief; borrowing base not modelled. |
| Investments, specialised lending and specialist products | 066 | Agricultural and livestock finance | supported conditional | Corporate/retail SME; livestock as other_physical only with Art. 199 attestation. |
| Investments, specialised lending and specialist products | 067 | Subscription and capital call finance | supported conditional | Fund is obligor; investors not inferred as guarantors (correct). Regulated-status gap IV-10. |
| Investments, specialised lending and specialist products | 068 | NAV hybrid and GP finance | supported conditional | Fund/LP-interest collateral gets no relief (CRM021/CRM014); IV-10 applies. |
| Investments, specialised lending and specialist products | 069 | Interbank deposit and money market loan | supported | B31 ECRA/SCRA and CRR Art. 120/121 short-term windows on original maturity, null -> long-term. |
| Investments, specialised lending and specialist products | 070 | Central bank reserve and placement | supported | central_bank / central_bank_ecb entity types; domestic 0%. |
| Investments, specialised lending and specialist products | 071 | Nostro and correspondent balance | supported conditional | Asset side only; without dates treated long-term (conservative). |
| Investments, specialised lending and specialist products | 072 | Sovereign and public sector lending | supported conditional | User-declared RGLA/PSE/MDB types; public purpose not inferred. PSE sub debt 150% owner decision (IV-03). |
| Investments, specialised lending and specialist products | 073 | Corporate bond and private placement | supported conditional | Issuer-level long-term rating only (IV-11); banking book only. |
| Investments, specialised lending and specialist products | 074 | Covered bond investment | supported conditional | Pseudo-counterparty entity_type covered_bond with issuer CQS/SCRA; B31 Table 7 and 129(5) correct; IRB class P1.322. |
| Investments, specialised lending and specialist products | 075 | Subordinated bank or corporate debt | silent misroute | B31 SL rows miss Art. 133(5) 150% (IV-03); CRR Art. 139(2) is P1.260. |
| Investments, specialised lending and specialist products | 076 | Equity and convertible investment | supported conditional | B31 Art. 133 + transitional (P1.389-393); CRR significant investment 100% (IV-06). |
| Investments, specialised lending and specialist products | 077 | Fund unit or CIU holding | silent misroute | Unsupported underlying classes 100% (IV-05); no 1250% cap (IV-07); IRB route P1.380. |
| Investments, specialised lending and specialist products | 078 | ABS RMBS CMBS and CLO tranche | silent misroute | No position route, corporate treatment (IV-08); SRT=False still carved out (IV-04). |
| Investments, specialised lending and specialist products | 079 | Warehouse and ABCP liquidity line | silent misroute | Booked as corporate facility with ordinary CCF; no tranching decision (IV-08). |
| Investments, specialised lending and specialist products | 060/061-SL | IPRE / HVCRE specialised lending | silent misroute | B31 forced slotting for SA-only firms (IV-02). |
| Investments, specialised lending and specialist products | T53 | Fund loan vs fund unit vs NAV | supported | Loan via loans table (corporate); unit via equity table equity_type ciu. |
| Investments, specialised lending and specialist products | T54 | Warehouse vs securitisation tranche | silent misroute | No structure decision possible (IV-08). |
| Investments, specialised lending and specialist products | DTA | Threshold-exempt DTAs / significant investments | silent misroute | DTA only via 100% other items (IV-12); CRR significant investments IV-06. |
| Investments, specialised lending and specialist products | 106 | Murabaha and commodity tawarruq | supported conditional | Deferred-sale receivable as loan; asset stage not representable (design). |
| Investments, specialised lending and specialist products | 107 | Ijara and diminishing musharaka | supported conditional | Lease or property-secured loan; co-ownership share via equity if equity-like. |
| Investments, specialised lending and specialist products | 108 | Salam and parallel salam | supported conditional | Prepayment credit exposure to seller as corporate; commodity risk is market-risk boundary. |
| Investments, specialised lending and specialist products | 109 | Istisna and parallel istisna | supported conditional | Stage payments as corporate/contingent; no stage model. |
| Investments, specialised lending and specialist products | 110 | Mudaraba and musharaka investment | supported conditional | Equity table; Art. 133(1) classification is the user's. |
| Investments, specialised lending and specialist products | 111 | Sukuk investment | supported conditional | As sovereign/corporate bond; tranched asset-backed sukuk hits IV-08. |
| Investments, specialised lending and specialist products | 112 | Tokenised deposit bond or fund | supported conditional | Input the underlying claim; no technology-risk carrier. |
| Investments, specialised lending and specialist products | 113 | Stablecoin and unbacked crypto | silent misroute | No explicit unsupported route; enters as equity/other item. No UK prudential rule yet (design). |
| Party relationships, groups and data-quality controls | 3.9-obligor-single | Bilateral loan, single obligor | supported | Baseline shape in all probes; both regimes. |
| Party relationships, groups and data-quality controls | 3.9-obligor-joint | Joint / co-borrower, joint-and-several (G09) | silent misroute | One counterparty per row; co-obligor threshold aggregate omits joint debt (RC-09). |
| Party relationships, groups and data-quality controls | 3.9-obligor-legal-form | Sole trader, LLP, partnership, trust, SPV, fund | supported conditional | Must map to valid entity_type; unknown → DQ006 + other 100%; null silent (RC-12). |
| Party relationships, groups and data-quality controls | 3.9-obligor-jv | JV with two sponsors (T18) | supported conditional | First parent by input order with DQ004 warning; B31 RWA order-dependent (RC-03). |
| Party relationships, groups and data-quality controls | 3.9-obligor-group | Subsidiary of corporate group | silent misroute | SME/LFSE on own figures (RC-05), ultimate-parent-only revenue (RC-06), silent PD inheritance (RC-04). |
| Party relationships, groups and data-quality controls | 3.9-recourse | Full / limited / non-recourse obligations | supported conditional | Obligor is borrowing entity; recourse caps not represented (SL/securitisation reviewers). |
| Party relationships, groups and data-quality controls | 3.9-perimeter-solo | Individual / sub-consolidated / consolidated runs | supported conditional | Scope validated (SCP001-006) but retail/SME-SF thresholds aggregate scoped books only (RC-07). |
| Party relationships, groups and data-quality controls | 3.9-perimeter-intragroup | Intragroup exposures | supported conditional | Eliminated on consolidated, Art 113(6) 0% on individual; equity/CCR/SFT untagged (P1.364). |
| Party relationships, groups and data-quality controls | 3.9-perimeter-book | Book to reporting-entity attribution | supported conditional | Unmapped book SCP001; duplicate book mapping last-wins silently (RC-14). |
| Party relationships, groups and data-quality controls | 3.9-currency | Draw / commitment / collateral currency | silent misroute | Missing FX rate converts 1:1 with no error (RC-11). |
| Party relationships, groups and data-quality controls | 3.9-lifecycle | Effective-dated relationships, as-of replay (T64) | not applicable | Mappings are point-in-time snapshots; no number moves within a run. Deferred design. |
| Party relationships, groups and data-quality controls | 3.9-distribution | Syndicated / participated / assigned lending | not applicable | Covered by participation/facility reviewer. |
| Party relationships, groups and data-quality controls | 3.9-availability-support-esg | Repayment/availability, credit support, sustainability labels | not applicable | Covered by other product-family reviewers. |
| Party relationships, groups and data-quality controls | B2.2 | Shared £20m agreement with borrower caps, LC sublimit, capped parent guarantee | silent misroute | Overlapping caps only expressible by double-mapping, which double-consumes headroom (RC-01); guarantee pool cap is G08 (CRM). |
| Party relationships, groups and data-quality controls | A10.3-11.2 | Umbrella with overlapping sublimits | silent misroute | Loan mapped to two sublimits: EAD 11.5m→10.0m (RC-01). |
| Party relationships, groups and data-quality controls | G06 | Overlapping relationship graphs | silent misroute | Facility multi-parent nondeterministic, cycles drop undrawn (RC-02); org order-dependent (RC-03); lending first-wins (RC-08). |
| Party relationships, groups and data-quality controls | T17 | Independent facilities under one reporting parent | supported | Org parent creates no commitment; each facility emits its own undrawn row. |
| Party relationships, groups and data-quality controls | T19 | Economic dependency without ownership | supported conditional | Via flat lending_mappings; if entered in org_mappings it triggers PD inheritance (RC-04). |
| Party relationships, groups and data-quality controls | T20 | Multiple group memberships | silent misroute | First membership kept silently; second group under-aggregated (RC-08). |
| Party relationships, groups and data-quality controls | T57 | Row-permutation invariance | silent misroute | Facility root nondeterministic even unpermuted (RC-02); org/lending/book mappings order-dependent. |
| Party relationships, groups and data-quality controls | T58 | Conservation of funded and contingent claims | silent misroute | Double-mapped child (RC-01) and cross-table reference collision (RC-10) lose exposure; no runtime identity. |
| Party relationships, groups and data-quality controls | T63 | Missing FX, cycles, orphans, impossible caps | silent misroute | FX (RC-11), cycles (RC-02/03), orphans (RC-13) silent; negative limit DQ012 works. |
| Party relationships, groups and data-quality controls | A13.3 | Unsupported type / reassuring 100% fallback | silent misroute | Null entity_type → other 100% with no error, CQS6 corporate understated (RC-12). |
| Party relationships, groups and data-quality controls | Art123-threshold | Retail / SME-SF threshold aggregation | supported conditional | Flat lending groups only (RC-08); solo runs (RC-07); joint debt (RC-09). |
| Party relationships, groups and data-quality controls | Art147-4C | B31 large-corporate revenue F-IRB restriction | silent misroute | Ultimate parent only (RC-06); JV order-dependent (RC-03). |
| Party relationships, groups and data-quality controls | Art172-1d | Separate rating per legal entity (IRB) | silent misroute | Parent internal PD/model inherited silently (RC-04). |
| Party relationships, groups and data-quality controls | DQ-duplicate-key | Duplicate exposure / counterparty references | supported conditional | Within table DQ004 ERROR; across tables silent and merges CRM (RC-10). |
| Party relationships, groups and data-quality controls | DQ-unknown-counterparty | Unknown counterparty reference | supported conditional | DQ005 ERROR; row kept at 100% other. |
| Party relationships, groups and data-quality controls | DQ-negative | Negative limits / amounts; excess drawings | supported conditional | DQ012 ERROR / DQ010 WARNING, values floored; over-limit loan measured in full. |
| Regime selection, permissions, output floor | DocB-3.9-bank-perimeter | Solo / sub-consolidated / consolidated runs | silent misroute | Run-per-scope works but group-wide obligor aggregates are truncated to scope (RG-02). |
| Regime selection, permissions, output floor | DocB-3.9-sustainability | Green / sustainability-linked labels | supported | No label-driven capital relief anywhere. |
| Regime selection, permissions, output floor | DocA-T44 | Retail threshold across bank entities | silent misroute | RG-02, measured CRR and B31 (450,000 vs 600,000). |
| Regime selection, permissions, output floor | DocA-T46 | A-IRB permission no longer applies (B31) | supported conditional | Art. 147A FSE/large-corp/institution/sovereign/equity limbs enforced regardless of permissions; FSE needs flag (RG-08). |
| Regime selection, permissions, output floor | DocA-T46-IPRE | IPRE / HVCRE routing | silent misroute | Forced slotting for SA-only firms and over Art. 148/150 SA permission (RG-01). |
| Regime selection, permissions, output floor | DocA-T46-SL | OF/PF/CF slotting permission without rating | silent misroute | Needs fabricated rating model_id; silent SA, no CLS006 (RG-07). |
| Regime selection, permissions, output floor | permission-absent | IRB mode without / unmatched model permissions | supported | missing_model_permissions warning and CLS006 (except SL rows, RG-07). |
| Regime selection, permissions, output floor | DocA-T47 | Output floor across two portfolios | supported conditional | Max taken once per run, not per exposure; but modelled subset (P1.367) and IRB-basis S-TREA (RG-03/RG-04). |
| Regime selection, permissions, output floor | DocA-T48 | Pillar 2A SME/infrastructure adjustment | supported | Nothing folded into Pillar 1; B31 supporting factors 1.0. |
| Regime selection, permissions, output floor | DocA-T49 | 31 Dec 2026 vs 1 Jan 2027 | supported conditional | User selects regime; dated schedules correct; no wrong-regime control, B31 pre-2027 floor 0% (RG-05). |
| Regime selection, permissions, output floor | DocA-T50 | 2028 large-exposure / market-risk changes | not applicable | Engine computes neither LE nor market risk. |
| Regime selection, permissions, output floor | DocB-8.3 | Regime, rule version, permission, reason on results | supported conditional | model_id, ppu_reason, approach_applied per row; pack hash only in opt-in manifest; no per-row routing reason. |
| Regime selection, permissions, output floor | DocB-T61 | Same facts under CRR vs B31 | supported | Separate runs on separate packs. |
| Regime selection, permissions, output floor | DocB-T62 | Floor vs shared-facility allocation | supported conditional | floor_aware metric evaluates both assignments end to end. |
| Regime selection, permissions, output floor | DocB-T64 | Historical replay | supported conditional | Content-hashed pack per regime/date; no dated amendment overlays beyond Schedules. |
| Regime selection, permissions, output floor | CRR-501 | SME supporting factor | supported conditional | Tiered E*, defaulted excluded, RRE carve-out; E* truncated on scoped runs (RG-02). |
| Regime selection, permissions, output floor | CRR-501a | Infrastructure supporting factor | supported conditional | Limb (a) only on product-name flag (P1.375). |
| Regime selection, permissions, output floor | B31-SF-removal | Supporting factors under Basel 3.1 | supported | Feature off, factor 1.0; citation wrong (RG-09). |
| Regime selection, permissions, output floor | B31-122(11) | SME corporate 85% | supported | Pack b31_corporate_sme_rw 0.85, unrated non-retail SMEs. |
| Regime selection, permissions, output floor | B31-122(6)/(8) | Investment-grade assessment | supported conditional | Single flag for permission and floor election (RG-06). |
| Regime selection, permissions, output floor | PS126-92 | Output floor x, OF-ADJ, entity carve-outs, transitional | supported conditional | 60/65/70/72.5% and OF-ADJ form correct; P1.367, P1.212, RG-03/04 open. |
| Regime selection, permissions, output floor | PS126-rules-4.1-4.10 | Equity transitional | supported conditional | SA firms correct; IRB firms keep Art. 133 with CFG003 (overstated, warned). |
| Regime selection, permissions, output floor | PS4/26-SDDT | SDDT simpler regime | not applicable | Not modelled; nothing treats SME borrowers as SDDT. |

## Design recommendations not required by regulation

Recorded for the product roadmap; none of these moves a number on its own.

**Commitments, CCFs and facility lifecycle**

- Replace the committed Boolean with a commitment_status state (not offered / offered unaccepted / accepted / accepted UCC / conditional / suspended / terminated); CM-01 is the interim fix.
- Borrowing-base availability vs legal commitment: keep limit as legal commitment; carry commercial availability separately for reporting only.
- Drawn-over-limit (T05): capital already correct; add informational breach DQ only.
- LC paid into reimbursement loan (T07/9.12): bs_type ONB flips the same row; optional replaces_contingent_reference link and duplicate-claim check; partial payment needs two rows.
- Overlapping sublimit constraint networks (T02/T16): MOF waterfall is a tree; belongs to the shared-limits dimension.
- Dated amendment/event replay (T06/T08) beyond CM-05's availability-end date; drawstops need no flag but must not be coded LR.
- A-IRB Art. 166D(3) facility-level single EAD: ead_modelled is per row; a facility-grain carrier would avoid splitting one estimate across drawn and undrawn rows.

**Shared / multi-borrower facilities, limits, MOF, syndication**

- Typed obligation-to-obligor relation for joint-and-several, several-only and limited-recourse obligations (T12, T13).
- General limit-constraint network beyond the facility tree; the SF-03 multi-parent warning is the interim control.
- Explicit fronting, swingline and risk-participation records with reimbursement rights (031, T24).
- Trade-date vs settlement-date participation share for unsettled sell-downs.
- Over-limit or excess flag after FX movement (T21); no capital effect since headroom clips at zero.
- Permitted draw currencies per facility for the Art. 123B currency-mismatch assessment of undrawn commitments (T22).
- Dated facility membership and amendments: accession, resignation, drawstop (Doc B 4.6).
- Commercial borrowing-base availability kept separate from the regulatory commitment (Doc A 11.3); engine already uses limit.
- Facility-share audit frame: record member provenance (owner, descendant or schedule).
- Guarantee cap shared across unrelated facilities (Doc B G08) belongs to the guarantees dimension.

**On-balance-sheet netting and cash pooling**

- Agreement-level netting_agreements input (governing law, opinion date, Art 205(a)-(d) attestations, termination date, revaluation frequency) to replace reference-only modelling.
- Link a user collateral row to the deposit account it represents, so one deposit cannot count as both pledged cash and netting.
- Cash-pool participant/sweep model (header account, intercompany loans, intraday bridge balances) for audit; capital uses actual legal balances.
- Fiduciary-capacity flag (escrow/client money/trust) with a validation refusing a netting reference on such balances.
- Record the offset-mortgage interest-offset relation separately from capital netting.
- Document that payment netting and IAS 32 accounting offset are not capital netting.
- Document the pro-rata allocation of the counterparty-level Art 219(1) net across loans with different risk weights as a design choice.
- Accrued interest payable on deposits is excluded from the pool (conservative); document it.
- One margin agreement over several netting sets (T45) belongs to the CCR review.

**Collateral and security**

- Separate asset, security-agreement and legal-evidence records (governing law, perfection route, opinion date) per Doc A 9.3 / Doc B 5.3.
- Tri-state legal certainty (perfected / unperfected / unknown), with unknown kept visible in output rather than folded into a Boolean.
- Effective and release dates on collateral links so a released asset stops counting without editing the item row.
- Dependency groups for economically dependent collateral (property, shares in its owner, assigned rents) to stop additive recovery assumptions (Doc A 11.14).
- Per-slice allocation-rationale column beyond the existing collateral_link_allocation audit frame.
- Small exhaustive / LP reference allocator in tests to bound the greedy heuristic on caps and differing haircuts (Doc B 9.7).
- CRR junior-lien reading of Art. 124(1) 'pledged amount of the market value' remains a documented interpretation (no 124C-style stacking); not filed.
- For the output-floor reviewer: a B31 F-IRB row with LGD 0 still showed RWA 60,000 on EAD 100,000 (CL-02 probe); the floor's SA-equivalent may not carry SA CRM. Not investigated.

**Guarantees, credit derivatives and risk transfer**

- Doc B 6.1 contract metadata (claim/waiting period, co-insurance terms, exclusions, governing law, subrogation) is attestation only; fold into the GT-07 eligibility attestation.
- Doc A 11.8 recovery-then-loss-share waterfall is an LGD recovery model, not a CRM input; only GT-03's loss_allocation flag is capital-relevant.
- Scheme vintage/version metadata (CBILS, BBLS, RLS, GGS) is provenance only; no capital effect while the guarantor is the sovereign.
- Facility-level guarantee allocation uses post-CCF EAD while cover is measured on the CCF=100% basis; no rule prescribes it, so document the choice.
- CRR Art. 235(3) says 'domestic currency of the borrower', PS1/26 says 'of that central government'; the engine tests the guarantor's; low impact for GB/GBP.
- Sold-protection vocabulary: add FINANCIAL_GUARANTEE, CREDIT_DERIVATIVE_SOLD, RISK_PARTICIPATION mapping to FR in VALID_OBS_PRODUCTS (a DQ warning already exists).
- TRS Art. 204(2) net-income condition and Art. 216(2) reference-obligation mismatch: add attestation flags only.
- Art. 215(2) mutual guarantee schemes / provisional payments remain in P7.5.
- An unresolvable guarantor reference silently yields no relief (conservative); add an FK warning under P5.52.
- Accounting derecognition vs prudential risk transfer for participations (Doc B 6.4) is outside CRM scope.

**Retail banking and real estate**

- Debt consolidation settlement-tracking fields are input preparation; no rule moves a number if the feed is correct.
- BNPL platform/merchant/promotional metadata is descriptive; recourse already maps to the guarantee input.
- Interest-only repayment-vehicle field has no SA capital effect.
- Lifetime-mortgage NNEG and roll-up projections have no Pillar 1 SA rule.
- Offset mortgages: keep interest-offset facts separate from netting attestations (netting dimension).
- A shared property_id table across loans and lenders would support RE-07 and Art. 124E property counts.
- RE decision-evidence record (Doc A 12.4) aids audit but moves no number.
- Effective-dated retail thresholds already served by resolve(regime, date) packs.
- Student-loan government-scheme flag is descriptive; the guarantee input carries the capital effect.
- Sales segment vs regulatory class already separate columns; documentation only.
- Pillar 2A adjustments correctly absent from engine; keep them out of Pillar 1.

**Trade finance, receivables, ABL and leasing**

- Borrowing-base availability, reserves and over-advance as reporting-only fields beside the contractual limit (T49).
- Invoice/asset identity and cross-programme duplicate-funding control (039, 058).
- Purchased-receivables role model (seller, debtor, servicer, insurer, reserve) and recourse scope by risk (default/dilution/fraud) (T50).
- Lease record (lessee, legal owner, RV guarantor, asset, MLP schedule, discount rate) to validate the discounted-MLP convention (055).
- LC role field (issuing/confirming/advising) and contingent-to-funded lifecycle link (047, 049).
- Refundable purchase-price discount as first-loss protection (Art 153(7)/154(6)) is optional relief, so its absence only overstates.
- Credit-insurance attestation fields (dilution/dispute exclusions) so cover links to the default leg only.
- CRR F-IRB revolving purchased-receivables commitments: 166(8)(c)/(d) are reachable only via risk_type LR/MR; FRC gives 100% (overstated).
- Observation: D3.57 (SCRA 6m trade window) appears fixed. B31 Grade A 5m trade loan got 20% in the probe, but via the TR-01 leak; re-verify after the fix.
- OUT-OF-SCOPE incidental: B31 F-IRB entity_type=institution without is_financial_sector_entity takes 40% (Art 161(1)(aa)), not 45%. The FSE flag is a raw pass-through (classify/attributes.py:144). Route to the institutions reviewer (cf. P1.400).

**Derivatives (SA-CCR), CCPs, SFTs, settlement and CVA**

- Simplified SA-CCR / OEM (P8.21/P8.22), IMM (P8.90), SA-CVA (P8.61): conservative fall-through, already planned.
- Optional reliefs not modelled (overstate only): Art 274(5) sold-option NS, Art 274(7) CDS premium cap, Art 306(1)(c)/(2) zero exposure, Art 304(2), Art 227 zero-haircut repos.
- PS1/26 Art 220(3) MNA formula (0.4*Enet + 0.6*Egross/sqrt(N)); engine gross haircut sum is more conservative once CC-14 gate exists.
- Basis and volatility transactions as separate hedging sets with epsilon (Art 277a(2)/280) need trade flags.
- Separate VM/IM records with custodian, segregation and reuse rights (Doc A 7.2) — columns exist; wire with CC-02.
- Netting legal-opinion scope and review dates as structured data (Doc A 7.2, Doc B G05).
- Product taxonomy plus explicit 'unresolved product' route with reason (Doc B 8.1); product_type is free text today.
- Agent-lender indemnity, merchant chargeback and payment-system pre-funding product keys (catalogue 089/101/100).
- Art 274(2A) per-trade legacy cohort and CVA Part 7.1(2) discount scalar transitional.
- Report file: /tmp/claude-0/-home-user-rwa-calculator/0e314a4f-daa3-5e8f-a2b1-d782e9208f7d/scratchpad/review/ccr_sft_settlement.md

**Investments, specialised lending and specialist products**

- Fund-finance due-diligence fields (investor commitments, excuse rights, side letters, NAV eligibility, cash sweeps) per Doc A 6.3.
- Controlled product_type vocabulary with an explicit 'unsupported / needs assessment' exception route (Doc A 8.2, Doc B T56).
- Islamic contract-stage modelling (asset stage before receivable, no duplicate debt-and-asset) for 106-110.
- Explicit crypto/stablecoin route pending PRA cryptoasset rules (Doc B 113).
- Covered bond Art. 129(1)/(7) eligibility attestation flag instead of relying on entity_type choice.
- RBL borrowing-base / redetermination / availability-reduction fields (Doc B 065).
- Banking-book vs trading-book flag on securities (market-risk boundary).
- HVCRE limbs (2)/(3) imply ADC: derive is_adc for SA-equivalent instead of requiring is_under_construction (document as input condition now).

**Party relationships, groups and data-quality controls**

- Typed party_relationship edges (control %, economic dependency, evidence, validity dates) instead of untyped parent/child mapping tables.
- Effective and recorded dates on mapping tables for as-of replay (T64).
- Limit-membership model for overlapping caps and borrowing base vs contractual limit (Doc A 10.3, 11.3).
- Separate facility_borrower 'may draw' from obligation_party 'must repay' (G02/G03 belong to facility review).
- Runtime conservation identity at pipeline exit (funded + contingent = pre-CRM original exposure), not test-only.
- Per-result explanation/lineage view (Doc A 13.3).
- Informational limit-breach flag for excess drawings (loan already measured in full).
- Decimal/fixed-point convention for cap and allocation arithmetic.
- Keep SS3/25 large-exposure grouping separate from retail/SME groupings; no LE calculation in scope.
- Emit HIE003 depth warnings for facility graphs (currently dropped at graph.py:222-229).
- Report: /tmp/claude-0/-home-user-rwa-calculator/0e314a4f-daa3-5e8f-a2b1-d782e9208f7d/scratchpad/review/relationships_controls.md; probes in .../scratchpad/review/probes/.

**Regime selection, permissions, output floor**

- Per-row approach-routing reason (ladder branch, Art. 147A limb that demoted A-IRB, CLS006 cause) instead of aggregate warnings only.
- Carry rulepack id/content hash, regime and reporting date on AggregatedResultBundle and CalculationResponse, not only the opt-in audit manifest.
- model_permissions: optional valid_from/valid_to and reporting-entity columns (Doc A 12.5 permission matrix); today snapshot plus excluded_book_codes.
- Dated amendment overlays for pack entries beyond Schedule (e.g. LIAF02/26-style corrections).
- Remove config-side duplicate schedules (OutputFloorConfig, EquityTransitionalConfig); analysis/transition.py:120 and api/service.py:512 still read them.
- Wire registry institution_type into Art. 92(2A) floor applicability for scoped runs (currently defaults to floor applies, conservative).
- Label pro-rata floor add-on in rwa_final as attribution (COREP already uses rwa_pre_floor; Pillar 3 pending P3.8).
- Optional B31 Pillar 2A side-output of SME/infrastructure eligibility kept outside Pillar 1.
- SDDT as a distinct regime only once PS4/26 rules are sourced; never inferred from customer size.

