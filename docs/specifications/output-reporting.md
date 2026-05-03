# Output & Reporting

## Functional Requirements

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-4.1 | Aggregated RWA by approach (SA, F-IRB, A-IRB, Slotting, Equity) | P0 | Done |
| FR-4.2 | Aggregated RWA by exposure class (9 classes) | P0 | Done |
| FR-4.3 | Basel 3.1 output floor calculation with transitional phase-in schedule | P1 | Done |
| FR-4.4 | Pre/post-CRM RWA breakdown with guarantee benefit attribution | P1 | Done |
| FR-4.5 | Exposure-level detail output with all intermediate calculations | P1 | Done |
| FR-4.6 | COREP template generation (CRR reporting) | P3 | Done |
| FR-4.7 | Excel / Parquet export of results | P2 | Done |

## Output Floor (Basel 3.1)

### Description
IRB RWA must be at least X% of what SA-equivalent RWA would produce. Transitional phase-in:

| Year | Floor Percentage | Reference |
|------|-----------------|-----------|
| 2027 | 60% | PRA PS1/26 Art. 92(5) |
| 2028 | 65% | PRA PS1/26 Art. 92(5) |
| 2029 | 70% | PRA PS1/26 Art. 92(5) |
| 2030+ | 72.5% | PRA PS1/26 Art. 92(5) |

### Output Floor Adjustment (OF-ADJ)

PRA PS1/26 Art. 92 defines the output floor formula:

```
TREA = max(U-TREA, x × S-TREA + OF-ADJ)
```

Where:
- **U-TREA** = un-floored total risk exposure amount (para 3)
- **S-TREA** = standardised total risk exposure amount (para 3A) — calculated WITHOUT IRB, SFT VaR, SEC-IRBA, IAA, IMM, or IMA
- **x** = floor multiplier from transitional schedule (60%-72.5%)
- **OF-ADJ** = `12.5 × (IRB_T2 - IRB_CET1 - GCRA + SA_T2)` — adjusts for approach-specific deductions

| Component | Description | Regulatory Ref |
|-----------|-------------|----------------|
| IRB_T2 | IRB excess provisions T2 **credit** (provisions > EL), capped at 0.6% of IRB credit RWAs | Art. 62(d) |
| IRB_CET1 | IRB EL shortfall CET1 deductions (EL > provisions) + Art. 40 additional deductions | Art. 36(1)(d), Art. 40 |
| GCRA | General credit risk adjustment included in T2, capped at **1.25% of S-TREA** | Art. 62(c), Art. 92(2A) |
| SA_T2 | SA general credit risk adjustments T2 credit | Art. 62(c) |

!!! info "GCRA qualifying criteria"
    The `GCRA` and `SA_T2` inputs carry **only** amounts that qualify as general credit
    risk adjustments under Commission Delegated Regulation (EU) No 183/2014 and
    Art. 110. See
    [Output Floor spec — GCRA Qualifying Criteria](basel31/output-floor.md#general-credit-risk-adjustments-gcra-qualifying-criteria)
    for the GCRA vs SCRA boundary, IFRS 9 Stage mapping, mixed-approach allocation
    (Art. 110(3)), and double-count avoidance. CMS1/CMS2 column d and OF 02.01 row 0040
    derive from the post-cap values returned by `compute_of_adj()`.

!!! note "Entity-Type Carve-Outs"
    The output floor does NOT apply universally. Art. 92 para 2A(b)-(d) exempts: non-ring-fenced institutions on sub-consolidated basis, ring-fenced bodies at individual level, and international subsidiaries. Exempt entities use U-TREA (no floor).

!!! info "S-TREA Scope"
    **S-TREA** (standardised total risk exposure amount, Art. 92(3A)) is built by re-running the
    Art. 92(3) components under standardised approaches only — i.e. no IRB, no SFT VaR, no
    SEC-IRBA, no IAA, no IMM and no IMA. Specifically it comprises:

    - Credit and dilution risk under the Standardised Approach (plus SA-CCR for counterparty risk)
    - Securitisation under SEC-SA / SEC-ERBA (not SEC-IRBA or IAA)
    - Settlement / delivery risk
    - Market risk under ASA (not IMA)
    - Operational risk (SMA)
    - CVA risk

    CVA and operational risk **are** included in S-TREA (they have no IRB counterpart so the
    modelled and standardised figures are identical). The output floor multiplier `x` is
    applied to S-TREA; see OF 02.01 col 0040 which reports S-TREA with the multiplier **not**
    applied (the multiplier is applied in OF 02.00 col 0030). Source: PS1/26 Annex II §1.3.2
    column 0040 instructions.

!!! note "Transitional Rates Are Permissive"
    Art. 92 para 5 says institutions "may apply" the 60/65/70% transitional rates — firms can voluntarily use 72.5% from day one.

### Status
- Engine implemented — Done
- Phase-in schedule validation tests — Done (6 acceptance tests in `test_scenario_b31_f_output_floor.py`)

## COREP Templates

### Description
Regulatory reporting templates for CRR / Basel 3.1 firms following the EBA/PRA COREP structure.
CRR templates use the **C** prefix (Regulation (EU) 2021/451); Basel 3.1 templates use the **OF**
prefix for the output-floor-aware re-issues and retain **C** for templates that are unchanged by
PS1/26 (PRA PS1/26 Annex I). Both `C` and `OF` prefixes are supervisory (COREP) submissions.

!!! note "Prefix Cheat-Sheet"
    - `C xx.xx` — COREP supervisory return, unchanged (or pre-PS1/26) template.
    - `OF xx.xx` — COREP supervisory return, PS1/26 re-issue (output-floor-aware or B3.1-restructured).
    - `UK xx` — CRR-era Pillar III public disclosure (UK onshored EBA Pillar III templates).
    - `UKB xx` — PS1/26 Pillar III public disclosure (Basel 3.1). `UKB` is the disclosure
      prefix, **not** a COREP prefix — do not confuse `UKB CR4` (Pillar III, Annex XIX/XX)
      with the COREP `C/OF` series.

Each template is submitted **once per exposure class** — the exposure class acts as a filter, not
a row dimension. Within each submission, rows are organised into sections (totals, exposure type
breakdown, risk weight breakdown, memorandum items).

### Templates
- **C 02.00 / OF 02.00** — Own Funds Requirements: master template aggregating RWEA across all risk types. 1 column (CRR) / 3 columns (Basel 3.1). Basel 3.1 adds col 0020 ("Standardised approaches only (output floor)" — SA-only RWEA per exposure class, pre-multiplier) and col 0030 ("Output floor" — the post-floor RWEA: SA totals after applying the output floor multiplier and OF-ADJ, i.e. the *floor-adjusted* number used in the TREA = max(U-TREA, x·S-TREA + OF-ADJ) comparison). Rows restructured: FIRB/AIRB/Slotting separated, corporate and retail subclass breakdowns added, slotting by 5 SL types, market risk expanded for ASA/IMA. Source: PS1/26 Annex II §1.3.
- **OF 02.01** — Output Floor (**new**, no CRR equivalent): dedicated output floor comparison for IM firms. 4 columns: col 0010 "RWA for modelled approaches" (portfolios under permitted internal models), col 0020 "RWA for portfolios on standardised approaches", col 0030 "Total RWA (U-TREA)" = arithmetic sum of 0010 + 0020 (the un-floored TREA from Art. 92), col 0040 "Standardised total RWA (S-TREA)" (all portfolios on SA, **no** multiplier applied). 8 rows by risk type (credit, CCR, CVA, securitisation, market, op risk, residual, total). Produces the raw U-TREA / S-TREA inputs that feed OF 02.00 col 0030. Note: OF 02.01 col 0030 is **U-TREA** (un-floored) and is distinct from OF 02.00 col 0030 (floor-adjusted) — same column number, different meaning. Source: PS1/26 Annex II §1.3.2.
- **C 07.00 / OF 07.00** — CR SA: one submission per SA exposure class. 24 columns (CRR) / ~29 columns (Basel 3.1) covering original exposure, provisions, CRM substitution effects, on-balance sheet netting adjustment, Financial Collateral Comprehensive Method, CCF breakdown (5 bands: 10%, 20%, 40%, 50%, 100%), exposure value, and RWEA. 5 row sections: totals, exposure types (on-BS/off-BS/CCR), risk weights (15 bands CRR / 29 bands Basel 3.1), CIU approach, memorandum items.
- **C 08.01 / OF 08.01** — CR IRB totals: one submission per IRB exposure class × own-estimates filter. 33 columns (CRR) / 40+ columns (Basel 3.1) covering PD, original exposure, CRM substitution effects, CRM in LGD estimates (detailed collateral breakdown), exposure value, LGD, maturity, RWEA, expected loss, provisions, obligor count. Basel 3.1 adds post-model adjustment and output floor columns.
- **C 08.02 / OF 08.02** — CR IRB by obligor grade: same columns as C 08.01 with dynamic rows (one per firm-specific internal rating grade/pool, ordered by PD).
- **C 08.03 / OF 08.03** — CR IRB PD ranges: one submission per IRB exposure class. 11 columns covering on/off-BS, avg CCF, exposure value, avg PD, obligors, avg LGD, avg maturity, RWEA, EL, provisions. Rows are 17 fixed PD range buckets (0.00–0.15 through 100% default). Basel 3.1: row allocation uses pre-input-floor PD ("PD RANGE (PRE-INPUT FLOOR)") while the PD column value reports post-input-floor PD ("EXPOSURE WEIGHTED AVERAGE PD (POST INPUT FLOOR)"). Supporting factors removed, slotting excluded.
- **C 08.04 / OF 08.04** — CR IRB RWEA flow statements: one submission per IRB exposure class. 1 column (RWEA), 9 rows (previous period, 7 movement categories, current period). Virtually identical between CRR and Basel 3.1 (supporting factors no longer mentioned).
- **C 08.05 / OF 08.05** — CR IRB PD back-testing: one submission per IRB exposure class. 5 columns (arithmetic average PD, prior-year obligor count, of which defaulted, observed default rate, historical annual default rate), 17 fixed PD range buckets (same as C 08.03). Basel 3.1: col 0010 explicitly post-input floor; row allocation uses pre-input-floor PD. Slotting and CCR exposures excluded. See [corep-reporting.md](../features/corep-reporting.md#c-0805-of-0805-cr-irb-pd-back-testing) for the full column structure.
- **C 08.06 / OF 08.06** — CR IRB specialised lending slotting: one submission per SL type. 10 columns (CRR) / 11 columns (Basel 3.1 adds col 0031 "(-) Change in exposure due to FCCM" — a deduction column between original exposure and exposure value). Rows by slotting category (1–5) × maturity band. Basel 3.1 adds "substantially stronger" sub-categories (reported in both row 0015 and 0025 when both criteria met) and separates HVCRE from IPRE (5 SL types vs 4).
- **C 08.07 / OF 08.07** — CR IRB scope of use: one submission covering all exposure/roll-out classes. 5 columns (CRR) / 18 columns (Basel 3.1 — significantly expanded with RWEA breakdown by SA reason and materiality thresholds). Rows change from exposure classes to roll-out classes (Art 147B).
- **C 09.01 / OF 09.01** — CR GB 1 geographical breakdown SA: one submission per country. 13 columns (CRR) / 10 columns (Basel 3.1) covering original exposure, defaults, provisions, exposure value, RWEA. Rows by SA exposure class. Basel 3.1: supporting factor columns removed, real estate rows restructured (regulatory residential/commercial RE sub-rows).
- **C 09.02 / OF 09.02** — CR GB 2 geographical breakdown IRB: one submission per country. 17 columns (CRR) / 13 columns (Basel 3.1) covering exposure, defaults, provisions, PD, LGD, RWEA, EL. Basel 3.1: adds defaulted exposure value column, removes supporting factors and SF columns, adds corporate sub-rows, restructures retail RE rows, removes equity.

### Missing Templates (Not Yet Documented)

- **OF 08.05.1** — PD Backtesting External Rating Equivalent: Extension of OF 08.05 for Art. 180(1)(f) ECAI-based estimates. Col 0005 uses firm-defined PD ranges (variable-width, not fixed buckets). Col 0006 provides one column per ECAI considered showing external rating equivalents. Columns 0010-0050 same as OF 08.05.
- **OF 34.07** — IRB CCR Exposures by Exposure Class and PD Scale: 7 columns — col 0010 exposure value, col 0020 exposure-weighted average PD (post-floor), col 0030 number of obligors, col 0040 EWA LGD, col 0050 EWA maturity (years), col 0060 RWEA, col 0070 density of RWEA (col 0060 / col 0010). Required for any firm using F-IRB or A-IRB for CCR, regardless of CCR valuation method (SA-CCR, IMM, etc.). Excludes CCP-cleared exposures.

### Basel 3.1 Reporting Field Additions

**OF 07.00 (SA)** — new columns vs CRR C 07.00:
- Col 0035: (-) Adjustment for on-balance sheet netting (Art. 219)
- Col 0160-0190: Off-balance sheet breakdown now uses 5 CCF bands (10%, 20%, 40%, 50%, 100%) instead of 4
- Col 0235: Of which: where a credit assessment by a nominated ECAI is not available (new)
- Rows 0021-0026: Specialised lending sub-types (object, commodities, project finance phases)
- Rows 0330-0360: Real estate sub-breakdowns (regulatory RESI/CRE, dependent/not, ADC). PS1/26 row order is **non-sequential** for CRE: 0341 then 0343 (SME nested under 0341) then 0342 then 0344 (SME nested under 0342). See [OF 07.00 Section 1 — Real Estate Row Hierarchy](#of-0700-section-1--real-estate-row-hierarchy) for the full nesting.
- Row 0380: Currency mismatch multiplier (retail and real estate)

**OF 08.01 (IRB)** — new columns vs CRR C 08.01:
- Col 0101-0104: FCCM adjustments (slotting only)
- Col 0125: Of which: defaulted exposure value
- Col 0251: RWEA pre-adjustments
- Col 0252: Adjustment for post-model adjustments
- Col 0253: Adjustment for mortgage RW floor
- Col 0254: Unrecognised exposure adjustments (Art. 153(5A)(b), 154(4A)(c)) — not reported for F-IRB or slotting sheets
- Col 0260: Risk-weighted exposure amount **after** adjustments — equals col 0251 adjusted for cols 0252 to 0254 (i.e. `0251 + 0252 + 0253 + 0254`). This is the post-adjustment RWEA that flows into OF 02.00 row 0010 as the IRB credit-risk RWEA contribution. Source: PS1/26 Annex II §3.3.1, p. 112.
- Col 0265: Of which: exposure value for non-defaulted
- Col 0275-0276: Non-modelled approaches exposure value and RWEA (for output floor)
- Col 0281: Expected loss adjustment for post-model adjustments
- Col 0282: Expected loss amount after post-model adjustments (total EL post all adjustments, not just PD/LGD floors)

### Missing Row IDs

**OF 02.00** — missing row IDs:
- Rows 0271, 0290, 0295-0297: F-IRB breakdown (institutions, SL excl slotting, financial/large corporates, SME, non-SME)
- Rows 0355-0356: A-IRB corporate breakdown (SME, non-SME)
- Rows 0382-0385: A-IRB retail residential/commercial splits (SME/non-SME)
- Rows 0411-0416: Slotting by 5 SL types (PF, OF, CF, IPRE, HVCRE)
- Row 0034: Output floor activated (Yes/No indicator, not RWEA)
- Row 0035: Output floor multiplier (percentage 60%-72.5%, not RWEA)
- Row 0036: Output floor adjustment OF-ADJ (monetary value)

**OF 07.00 (SA)** — missing row IDs:
- Rows 0021-0026: Specialised lending sub-types (0021=OF, 0022=CF, 0023=PF, 0024=PF pre-operational, 0025=PF operational, 0026=PF high-quality operational — hierarchical under PF)
- Rows 0330-0360: Real estate sub-breakdowns (regulatory RESI, regulatory CRE, other RE, ADC). The 03xx grid is **non-sequential** in the PS1/26 row order — see [OF 07.00 Section 1 — Real Estate Row Hierarchy](#of-0700-section-1--real-estate-row-hierarchy) below.
- Rows 0351-0354: Other real estate sub-breakdown (residential/commercial, dependent/non-dependent under Art. 124J)
- Rows 0371-0374: Equity transitional sub-rows (0371=SA higher-risk, 0372=SA other, 0373=IRB higher-risk, 0374=IRB other — expire 1 January 2030)
- Row 0380: Retail and real estate exposures subject to the currency mismatch multiplier (Art. 112(1)(h)/(i))

#### OF 07.00 Section 1 — Real Estate Row Hierarchy

The Section 1 real-estate "of which" grid (rows 0330–0360) is **not** a flat
sequential range. PS1/26 Annex II §3.2 (pp. 90–91) defines the rows in the
order **0341 → 0343 → 0342 → 0344**, and the SME sub-rows (0343, 0344) are
each nested under a different parent. Generators must respect this nesting
when allocating SME CRE exposures.

| Row | Title | Article | Parent | Notes |
|-----|-------|---------|--------|-------|
| 0330 | Regulatory residential real estate | Art. 124F + 124G | — | Sum of 0331 + 0332 |
| 0331 | RESI — not materially dependent on property cash flows | Art. 124F | 0330 | Loan-splitting "secured leg" applies |
| 0332 | RESI — materially dependent on property cash flows | Art. 124G | 0330 | Income-producing residential (LTV grid) |
| 0340 | Regulatory commercial real estate | Art. 124H + 124I | — | Sum of 0341 + 0342 |
| 0341 | CRE — not materially dependent on property cash flows | Art. 124H | 0340 | |
| 0343 | of which: CRE not materially dependent — to SMEs | Art. 124H + Glossary "SME" | **0341** | **Nested under 0341, not 0342** |
| 0342 | CRE — materially dependent on property cash flows | Art. 124I | 0340 | |
| 0344 | of which: CRE materially dependent — to SMEs | Art. 124I + Glossary "SME" | **0342** | **Nested under 0342, not 0341** |
| 0350 | Other real estate | Art. 124J | — | Sum of 0351–0354 |
| 0351 | Other RESI — not materially dependent | Art. 124J(2) | 0350 | |
| 0352 | Other RESI — materially dependent | Art. 124J(1) | 0350 | |
| 0353 | Other CRE — not materially dependent | Art. 124J(3) | 0350 | |
| 0354 | Other CRE — materially dependent | Art. 124J(1) | 0350 | |
| 0360 | Land acquisition, development and construction (ADC) | Art. 124K | — | |

!!! warning "0343 is under 0341, 0344 is under 0342"
    The SME sub-rows are **separated by parent**, not paired together. A CRE
    SME exposure that is not materially dependent on property cash flows
    (Art. 124H) is reported in row **0343** (nested under 0341); a CRE SME
    exposure that **is** materially dependent (Art. 124I) is reported in
    row **0344** (nested under 0342). The PS1/26 Annex II row-order listing
    deliberately interleaves them as 0341 → 0343 → 0342 → 0344 to make this
    explicit. Do not assume row-ID ordering implies parent-child grouping.

Source: PS1/26 Annex II §3.2, pp. 90–91 of
`docs/assets/ps1-26-annex-ii-reporting-instructions.pdf`.

For the **risk-weight band rows** (Section 3 of OF 07.00), see the dedicated table
[OF 07.00 Section 3 — Risk Weight Band Row IDs](#of-0700-section-3--risk-weight-band-row-ids)
below.

### OF 07.00 Section 3 — Risk Weight Band Row IDs

Section 3 of OF 07.00 (the "Breakdown of total exposures by risk weights" section)
expands from **15** risk-weight rows under CRR C 07.00 to **29** rows under Basel 3.1
OF 07.00. The fourteen new granular bands (15%, 25%, 30%, 40%, 45%, 60%, 65%, 80%,
85%, 105%, 110%, 130%, 135%, 400%) reflect the more granular risk-weight grid
introduced by PRA PS1/26 — primarily from real-estate loan-splitting / income-producing
LTV bands (Art. 124F–124I), corporate sub-categories (Art. 122), institution ECRA/SCRA
(Art. 120–121), and the new equity higher-risk weight (Art. 133(4)).

The previous CRR row 0260 (370%) is **removed** and replaced by row **0261 (400%)**
for higher-risk equity exposures under Art. 133(4) — reported during the Standardised
Transitional Approach period via memorandum row 0374, but always allocated to row 0261
in Section 3.

| Row ID | Risk Weight | Basel 3.1 / CRR Article(s) | Typical Source |
|--------|-------------|----------------------------|----------------|
| 0140 | 0% | SA Art. 114(2) (sovereign CQS 1), Art. 116(4) (PSE), Art. 134(3) (cash) | Sovereign AAA-AA-, eligible PSE, cash items |
| 0150 | 2% | Art. 306(1) Counterparty Credit Risk (CRR) Part | Trade exposures to QCCPs |
| 0160 | 4% | Art. 305(3) Counterparty Credit Risk (CRR) Part | Default-fund contributions to QCCPs (cap) |
| 0170 | 10% | SA Art. 129 (covered bonds CQS 1) | Covered bonds — CQS 1 |
| **0171** | **15%** | SA Art. 129 (covered bonds CQS 2-3) — Basel 3.1 expansion | Covered bonds — CQS 2 (and certain CQS 3) |
| 0180 | 20% | SA Art. 114 / 120 (sovereign / institution CQS 2; SCRA Grade A short-term) | Sovereign CQS 2, institution ECRA CQS 1, RE secured-portion (Art. 124F) |
| **0181** | **25%** | SA Art. 124G(2) junior-charge multiplier on 20% base | Real estate income-producing RESI low-LTV variants |
| **0182** | **30%** | SA Art. 120 (institution ECRA CQS 2 >3m), Art. 121 (SCRA Grade A enhanced), Art. 124G (income-producing RESI <=50% LTV) | Institutions, income-producing RESI |
| 0190 | 35% | SA Art. 124G (income-producing RESI 50-60% LTV) | Income-producing residential RE |
| **0191** | **40%** | SA Art. 121 (SCRA Grade A >3m), Art. 124G (income-producing RESI 60-70% LTV), Art. 161 covered-bond LGD-driven RW | Institutions SCRA Grade A, income-producing RESI mid-LTV |
| **0192** | **45%** | SA Art. 123A (transactor retail) — Basel 3.1 new | Transactor retail exposures (paid in full each cycle) |
| 0200 | 50% | SA Art. 120 (institution ECRA CQS 3), Art. 124G (income-producing RESI 70-80% LTV) | Institutions ECRA CQS 3, income-producing RESI |
| **0201** | **60%** | SA Art. 124H (commercial RE secured-portion natural person/SME), Art. 124G (income-producing RESI 80-90% LTV) | CRE loan-splitting secured leg |
| **0202** | **65%** | SA Art. 122(2) (corporate CQS 3 — was 100% under CRR), Art. 122(3) (investment-grade unrated corporate) | Corporates CQS 3, investment-grade unrated corporates |
| 0210 | 70% | Art. 232(3)(c) Credit Risk Mitigation (CRR) Part | CRM-driven outcomes (e.g., minimum collateral floor) |
| 0220 | 75% | SA Art. 123 (other retail), Art. 124F (counterparty RW for RESI residual) | Standard retail, RE residual leg |
| **0221** | **80%** | SA Art. 122A(3) (project finance high-quality operational phase) — Basel 3.1 SA SL new | High-quality operational PF |
| **0222** | **85%** | SA Art. 122(4) (SME corporate — replaces CRR 100% + SF mechanism) | SME corporate (turnover <= EUR 50m) |
| 0230 | 100% | SA Art. 122(2) (corporate CQS 4-5 / unrated), Art. 124I (commercial RE income-producing <=80% LTV), Art. 134(2) (other items) | Default unrated corporates, CRE income-producing, other items |
| **0231** | **105%** | SA Art. 124G (income-producing RESI >100% LTV) | High-LTV income-producing residential |
| **0232** | **110%** | SA Art. 124I (commercial RE income-producing >80% LTV) | High-LTV income-producing commercial |
| **0233** | **130%** | SA Art. 122A(1) (project finance pre-operational phase) — Basel 3.1 SA SL new | Pre-operational project finance |
| **0234** | **135%** | Junior-charge multiplier × 110% (CRE income-producing high-LTV with subordinated charge) | Junior-charge CRE outcome |
| 0240 | 150% | SA Art. 122(2) (corporate CQS 6), Art. 127 (defaulted, low provisions), Art. 128 (high-risk), Art. 133 (subordinated debt) | Defaulted high-LGD, high-risk items, subordinated debt |
| 0250 | 250% | SA Art. 133(3) (standard equity) and Art. 48(4) CRR | Standard SA equity exposures |
| **0261** | **400%** | SA Art. 133(4) (higher-risk equity) and Art. 48(4) CRR — **replaces CRR row 0260 (370%)** | Higher-risk equity (unlisted, <5yr, PE, speculative) |
| 0270 | 1250% | SA Art. 132(2) and Art. 379 CRR | Risk-weight deductions (full capital) |
| 0280 | Other | SA Art. 113(1)–(5) | Other risk weights — not available for Government, Corporates, Institutions, Retail. Used for nth-to-default credit derivatives under "Other items" |

!!! warning "0260 (370%) Removed Under Basel 3.1"
    The CRR-era C 07.00 row **0260 = 370%** (higher-risk equity under CRR Art. 133(4))
    is **removed** under Basel 3.1 OF 07.00. Higher-risk equity exposures are now
    reported in row **0261 = 400%**, reflecting the increased Basel 3.1 SA risk weight
    in PRA PS1/26 Art. 133(4). Any code or template mapping that previously emitted
    row 0260 must be updated to emit 0261 with the revised 400% weight.

!!! info "Allocation Notes"
    - Mixed real estate exposures (Art. 124(4)) are reported against the risk weights
      for their constituent parts.
    - Real estate exposures with junior charges (Art. 124G(2), 124H(3), 124I(3)) are
      **allocated** to the row that would apply if the junior-charge multiplier were
      disapplied; the **RWEA column** still reflects the multiplier (so a 110% base
      with a 1.25× junior-charge multiplier reports under row 0232 = 110%, but with
      RWEA = exposure × 137.5%, surfacing in row 0234 = 135% only when the base RW
      itself is the multiplier outcome).
    - Equity exposures under the Standardised Transitional Approach (Rules 4.1–4.10
      of the Credit Risk: General Provisions (CRR) Part) are allocated to rows 0250
      and 0261 per Art. 133, and additionally reported against memorandum rows
      0371–0374 for the transitional period (expiring 1 January 2030). The
      memorandum reporting in 0371–0374 does **not** affect the primary allocation
      to 0250 / 0261.
    - Source: PS1/26 Annex II §3.2.5, pp. 95–96 of
      `docs/assets/ps1-26-annex-ii-reporting-instructions.pdf`.

**OF 08.07 (IRB Scope of Use)** — missing row IDs:
- Rows 0180-0260: Roll-out class breakdowns for corporate sub-classes, retail sub-classes, and SL types

**OF 09.01 (SA Geographic Breakdown)** — missing row IDs:
- Rows 0071-0073: Specialised lending sub-rows (0071=object finance, 0072=commodities finance, 0073=project finance — same definitions as OF 07.00 rows 0021-0023; sub-rows under Corporates 0070)
- Row 0075: Of which: SME — sub-row under Corporates (0070); same definition as OF 07.00 row 0020 (Art. 112(1)(g))
- Row 0085: Of which: SME — sub-row under Retail (0080); same definition as OF 07.00 row 0020 (Art. 112(1)(h))
- Rows 0091-0094: Real estate sub-breakdowns (0091=regulatory residential RE, 0092=regulatory commercial RE, 0093=other RE, 0094=ADC — same definitions as OF 07.00 rows 0330/0340/0350/0360; sum of 0091-0094 equals row 0090)
- Row 0095: Of which: SME — sub-row under Real estate exposures (0090); same definition as OF 07.00 row 0020 (Art. 112(1)(i))
- Row 0141: CIU look-through approach — sub-row under Collective investment undertakings (0140); same definition as OF 07.00 row 0281
- Row 0142: CIU mandate-based approach — sub-row under Collective investment undertakings (0140); same definition as OF 07.00 row 0282
- Row 0143: CIU fall-back approach — sub-row under Collective investment undertakings (0140); same definition as OF 07.00 row 0283 (sum of 0141-0143 equals row 0140, Art. 112(1)(o))
- Row 0160: Other items — Art. 112(1)(q) of the Credit Risk: Standardised Approach (CRR) Part
- Row 0170: Total exposures — geographic-breakdown grand total across all SA exposure classes

Source: PS1/26 Annex II §3.4.1 (OF 09.01 row instructions, pp. 139-141 of `docs/assets/ps1-26-annex-ii-reporting-instructions.pdf`).

**OF 09.02 (IRB Geographic Breakdown)** — missing row IDs:
- Row 0042: Specialised lending (excluding slotting approach)
- Row 0045: Specialised lending under the slotting approach
- Row 0048: Financial corporates and large corporates (Art. 147(4C))
- Row 0049: Purchased receivables (corporate) — **not** SME as previously documented
- Row 0050: Other general corporates – SME
- Row 0055: Other general corporates – non-SME
- Rows 0071-0074: Retail RE sub-rows (SME/non-SME splits for residential and commercial)
- Row 0100: Qualifying revolving retail exposures
- Row 0105: Purchased receivables (retail)
- Row 0120: Retail – Other SME
- Row 0130: Other non-SME
- Row 0150: Total exposures
- Col 0105 = total exposure value; col 0107 = of which: defaulted (sub-item)
- Note: Equity rows removed under Basel 3.1

### Reference Documents
- `docs/assets/CRR - corep-own-funds.xlsx` — CRR template layouts (sheets "7", "8.1", "8.2", "8.3", "8.4", "8.6", "8.7", "9.1", "9.2")
- `docs/assets/crr-annex-ii-reporting-instructins.pdf` — CRR reporting instructions
- `docs/assets/0F07 - annex-i-of-07-00-credit-risk-sa-reporting-template.xlsx` — Basel 3.1 OF 07.00 layout
- `docs/assets/OF0801-annex-i-of-08-01-credit-risk-irb-reporting-template.xlsx` — Basel 3.1 OF 08.01 layout
- `docs/assets/OF0802-annex-i-of-08-02-credit-risk-irb-reporting-template.xlsx` — Basel 3.1 OF 08.02 layout
- `docs/assets/ps1-26-annex-ii-reporting-instructions.pdf` — Basel 3.1 reporting instructions

### Status
- Generator: Complete — all 10 COREP template families implemented: C/OF 02.00, 07.00, 08.01, 08.02, 08.03, 08.04, 08.05, 08.06, 08.07, 09.01, 09.02, and OF 02.01.
- OF 02.01: Complete — `COREPGenerator._generate_of_02_01()` populates credit risk row (0010) and Total row (0080); other rows null (CCR/market/op risk out of scope).
- Template definitions: Complete — all templates use correct 4-digit COREP column references and multi-section row structures matching EBA/PRA layouts.
- Excel export: Complete — produces per-exposure-class sheets for all templates.
- Integration: Done (`ResultExporter.export_to_corep()`, `CalculationResponse.to_corep()`)
- Tests: Complete — 700+ COREP tests across multiple test files covering all template families.
- Known sub-gaps:
    - **C 07.00 / OF 07.00**: Section 2 rows 0090–0130 (SFT netting sets, derivatives, cross-product netting) always null — CCR out of scope. Columns 0210/0211 ("Of which: arising from CCR" / "CCR excl. CCP") always null.
    - **C 08.01 / OF 08.01**: Section 2 rows 0040–0060 (SFT, derivatives, cross-product netting) always null — CCR out of scope. B31 rows 0031–0035 (off-BS CCF bucket breakdown) null. Column 0130 ("Of which: arising from CCR") null. Column 0120 ("Of which: off balance sheet" under Exposure Value) null (Phase 2B). Column 0030 ("Of which: LFSE") null (Phase 2F).
    - **B31 CIU sub-rows**: OF 07.00 rows 0284/0285 not populated.
    - **OF 34.07**: IRB CCR template not yet implemented (see Missing Templates above).
- Detailed feature docs: Done — see [COREP Reporting](../features/corep-reporting.md) (all 10 template families documented)

## Pillar III Disclosure Templates

### Description
Public disclosure templates under CRR Part 8 / Disclosure (CRR) Part for market transparency.
CRR-era templates use the **UK** prefix (e.g. `UK CR8`); PS1/26 re-issues use the **UKB**
prefix (e.g. `UKB CR4`, `UKB CR9`, `UKB CMS1`). These are the Pillar III **disclosure** series —
distinct from the COREP supervisory `C/OF` series in the previous section. These complement
COREP supervisory returns with publicly available credit risk data.

### Templates
- **UKB OV1** — Overview of risk-weighted exposure amounts (Art. 438(d))
- **UKB CR4** — SA exposure and CRM effects (Art. 444(e), 453(g-i)). Fixed format, one submission per SA exposure class.
- **UKB CR5** — SA risk weight allocation by exposure class (point (e) of Art. 444). Fixed format: columns a–ac are the risk-weight bands (0%, 2%, 4%, 10%, 20%, 35%, 40%, 45%, 50%, 60%, 65%, 70%, 75%, 80%, 85%, 90%, 100%, 105%, 130%, 150%, 250%, 300%, 370%, 400%, 1250%, "other", deducted, total, "of which unrated") — precise band list follows Annex XIX. Rows are the SA exposure classes. Regulatory real estate not materially dependent on cash-flows is split into two rows: portion up to 55% of property value, portion above 55%. Exposures subject to the Art. 123B currency-mismatch multiplier are reported against the base (pre-multiplier) risk weight, but the RWEA column reflects the multiplier.
- **UKB CR6** — IRB exposures by exposure class and PD range (Art. 452(g))
- **UKB CR6-A** — Scope of IRB and SA use (Art. 452(b))
- **UKB CR7** — Credit derivatives effect on RWEA (Art. 453(j))
- **UKB CR7-A** — Extent of CRM techniques for IRB (Art. 453(g))
- **UK CR8** — RWEA flow statements for IRB (Art. 438(h)). Uses **signed** RWEA movements: increases are positive, decreases (asset size, quality, model updates, methodology, acquisitions/disposals, FX, other) are reported as negative values. See Annex XXII §11.
- **UKB CR9** — IRB PD back-testing per exposure class (Art. 452(h)) — Basel 3.1 only
- **UKB CR9.1** — IRB PD back-testing for ECAI mapping (Art. 452(h), Art. 180(1)(f)) — Basel 3.1 only. Adds one column per ECAI considered; PD ranges are firm-defined internal grade ranges (not the fixed external PD buckets used in CR9). Generation requires ECAI mapping data (template defined, runtime generation pending).
- **UKB CR10** — Slotting approach exposures (Art. 438(e)). Sub-templates CR10.1 (project finance), CR10.2 (IPRE), CR10.3 (object finance), CR10.4 (commodities finance), CR10.5 (HVCRE — new under PS1/26). Fixed templates per Annex XXIII/XXIV.
- **UKB CMS1** — Output floor comparison by risk type (Art. 456(1)(a), Art. 2a of the Disclosure (CRR) Part) — Basel 3.1 only
- **UKB CMS2** — Output floor comparison by asset class (Art. 456(1)(b), Art. 2a of the Disclosure (CRR) Part) — Basel 3.1 only

!!! note "Sign Conventions in Pillar III"
    A subset of Pillar III templates use **signed** values where decreases are reported as
    negative numbers:

    - **UK CR8 / UKB CR8** — RWEA flow statement: decreases in RWEA (rows: asset size (+/-), asset quality (+/-), model updates (+/-), methodology and policy (+/-), acquisitions and disposals (+/-), foreign exchange movements (+/-), other (+/-)) are reported as negative. Source: PS1/26 Annex XXII §11.
    - **UKB CR9 / UKB CR9.1** — back-testing: observed default rates are non-negative but external-rating-equivalent columns may reproduce signed PD mapping inputs.
    - **UKB CR10** — slotting: signed deductions for collateral-driven exposure reductions (e.g. FCCM adjustment).

    All other Pillar III credit risk templates (CR4, CR5, CR6, CR7, CMS1/CMS2, OV1) report
    absolute non-negative figures unless an explicit "(-)" column header indicates a
    deduction.

### Reference Documents
- CRR: `docs/assets/crr-annex-xx-instructions-regarding-disclosure.PDF`, `crr-pillar3-irb-credit-risk-instructions.pdf`, `crr-pillar3-risk-weighted-exposure-instructions-leverage-ratio.pdf`, `crr-pillar3-specialised-lending-instructions.pdf`
- Basel 3.1: `docs/assets/ps1-26-annex-xx-credit-risk-sa-disclosure-instructions.pdf` (CR4, CR5), `ps1-26-annex-xxii-credit-risk-irb-disclosure-instructions.pdf` (CR6, CR6-A, CR7, CR7-A, CR8, CR9, CR9.1), `ps1-26-annex-xxiv-credit-risk-irb-disclosure-instructions.pdf` (CR10)
- **CMS1 / CMS2**: the templates are listed in **Annex I** and the row/column instructions live in **Annex II** of the Disclosure (CRR) Part. Article 2a (*Disclosure of Output Floor*) of the Disclosure (CRR) Part — `docs/assets/ps126app1.pdf` page 467 — establishes that institutions shall make the Article 456(1) output-floor disclosures using Templates UKB CMS1 and UKB CMS2 of Annex I "and the relevant instructions set out in Annex II". The PS1/26 PDF references the Annex I templates and Annex II instructions only via inline hyperlinks (`docs/assets/ps126app1.pdf` page 470, §6.2A "Annex I Template UKB CMS1 can be found here" and §6.2B "Annex I Template UKB CMS2 can be found here"); neither the templates nor the disclosure instructions are reproduced locally as standalone PDFs in `docs/assets/`. Retrieve them from the PS1/26 publication landing page: <https://www.bankofengland.co.uk/prudential-regulation/publication/2026/january/implementation-of-the-basel-3-1-final-rules-policy-statement>. Note: the local file `docs/assets/ps1-26-annex-ii-reporting-instructions.pdf` is the **COREP supervisory** reporting Annex II — **not** the Pillar III Disclosure Annex II that contains CMS1/CMS2 instructions.

### Status
- Documentation: Done — see [Pillar III Disclosures](../features/pillar3-disclosures.md)
- Code implementation: Done — 13 templates (OV1, CR4-CR10, CR9/CR9.1, CMS1/CMS2) in `reporting/pillar3/`

## Export

### Status
- Parquet export: Done
- CSV export: Done
- Excel (XLSX) export via xlsxwriter: Done
