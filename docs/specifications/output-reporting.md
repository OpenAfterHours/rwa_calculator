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
| FR-4.8 | UI writes the export formats to a user-chosen local folder (run-stamped subfolder; see [interfaces FR-6.6](interfaces.md)) | P2 | Done |

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
| GCRA | General credit risk adjustment included in T2, capped at **1.25% of the Art. 92(3A) risk-weighted exposure amounts** (the whole book's credit and CCR RWEA at its standardised value) | Art. 62(c), Art. 92(2A) |
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
    applied (the multiplier is applied in OF 02.00 row 0010 col 0030). Source: PS1/26 Annex II §1.3.2
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

The class a leg is reported under is the sealed `reporting_class_origin` (obligor basis) or
`reporting_class` (post-substitution basis). Both are the Art. 112 applied class, with one
exception: the IRB templates are laid out on the Art. 147(2) classes, and those differ from the
Art. 112 classes for an MDB. CRR Art. 147(4)(c) assigns "exposures to multilateral development
banks which are not assigned a 0 % risk weight under Article 117" to the IRB **institutions**
class. So a twin whose class is `mdb` and whose own approach twin is F-IRB or A-IRB reads
`institution` when the classifier's IRB class for it is `institution` (a non-named MDB under
CRR). That puts the leg on the C 08.01–08.05 institutions sheet, C 09.02 row 0020, C 02.00 rows
0270 / 0330 and the Pillar 3 CR6 / CR7 / CR7-A institutions rows, not on an `mdb` sheet that no
published sheet code addresses. A slice substituted to an IRB guarantor keeps the guarantor's
class on the post basis. An SA leg keeps `mdb`, the correct Art. 112(1)(d) class (C 07.00,
C 09.01 row 0040). A named Art. 117(2) MDB is not relabelled: its IRB class stays `mdb`. Under
Basel 3.1 the case cannot arise, because PS1/26 Art. 147(3)(f) and 147A(1)(a) make every MDB
Standardised (`engine/aggregator/aggregator.py::_art147_reporting_class`; P1.366).

### Templates
- **C 02.00 / OF 02.00** — Own Funds Requirements: master template aggregating RWEA across all risk types. 1 column (CRR) / 3 columns (Basel 3.1). Row 0040 is the credit-risk RWEA and equals SA (0050, the same figure as 0060) + IRB (0240) + CCP default fund (0460) + securitisation (0470) in both templates (EBA `v0205_m`; BoE `boe_b1093`); neither template has an "8% own funds requirement" row. Basel 3.1 col 0010 ("All approaches") is the **un-floored** RWEA — row 0010 col 0010 is U-TREA, one data point with OF 02.01 row 0080 col 0030. Col 0020 ("Standardised approaches only (Output Floor)") exists on row 0040 and the modelled rows only and holds the standardised-approach RWEA of the same exposures; row 0040 col 0020 is S-TREA = row 0050 col 0010 + row 0240 col 0020 (`boe_b0716`). Col 0030 ("Output Floor") exists on rows 0010, 0034, 0035 and 0036 only: row 0010 is the floor `x·S-TREA + OF-ADJ`, and TREA = max(row 0010 col 0010, col 0030). Rows restructured: FIRB (0250) / AIRB (0310) / Slotting (0411) separated, corporate and retail subclass breakdowns added, slotting by 5 SL types, market risk expanded for ASA/IMA; no rows for IRB sovereigns, A-IRB institutions or IRB equity (Art. 147A). Row codes, labels and cells are declared in `reporting/corep/c02_rows.py` and held to the PRA001 taxonomy by `tests/contracts/test_of02_published_cells.py`. An IRB class row that is one data point with an OF 08.01 class sheet's total (0271, 0295–0297, 0350, 0355, 0356, 0382–0385, 0390, 0400, 0410) is reported only when that sheet has exposures and is empty otherwise, as OF 08.01 omits the sheet; row 0290 (its sheet also totals slotting), the approach totals and every CRR row are still zero when empty (BoE XBRL Filing Manual v1.0.1 rule 2.19; `boe_b1055`). Source: PS1/26 Annex II §1.3; taxonomy table `OF02.00.01.01`.
- **OF 02.01** — Output Floor (**new**, no CRR equivalent): dedicated output floor comparison for IM firms. 4 columns: col 0010 "RWA for modelled approaches" (portfolios under permitted internal models), col 0020 "RWA for portfolios on standardised approaches", col 0030 "Total RWA (U-TREA)" = arithmetic sum of 0010 + 0020 (the un-floored TREA from Art. 92), col 0040 "Standardised total RWA (S-TREA)" (all portfolios on SA, **no** multiplier applied). **Cols 0010 and 0020 partition the book** — col 0030 is only "the complete current portfolio" because each exposure is counted in exactly one of them, so col 0020 is the *complement* of the modelled set (SA, SA-CCR and equity all land there), never an allow-list of approach labels. 8 rows by risk type (credit excl. CCR, CCR, CVA, securitisation, market, op risk, residual, total); rows 0010/0020 partition the credit-risk book and row 0080 is their sum. Produces the raw U-TREA / S-TREA inputs that feed OF 02.00 col 0030. Note: OF 02.01 col 0030 is **U-TREA** (un-floored) — the same data point as OF 02.00 row 0010 col **0010** — and is distinct from OF 02.00 col 0030 (the floor) — same column number, different meaning. Source: PS1/26 Annex II §1.3.2.
- **C 07.00 / OF 07.00** — CR SA: one submission per SA exposure class. 24 columns (CRR) / ~29 columns (Basel 3.1) covering original exposure, provisions, CRM substitution effects, on-balance sheet netting adjustment, Financial Collateral Comprehensive Method, CCF breakdown (5 bands: 10%, 20%, 40%, 50%, 100%), exposure value, and RWEA. 5 row sections: totals, exposure types (on-BS/off-BS/CCR), risk weights (15 bands CRR / 29 bands Basel 3.1), CIU approach, memorandum items. Row 0015 "of which: Defaulted exposures" is reported only on the sheets of the classes that keep a defaulted exposure — high risk and equity (CRR), plus CIUs (Basel 3.1) — and on the Total, which adds those sheets up; a defaulted exposure of any other class is reported on row 0010 of the "exposures in default" sheet and leaves row 0015 blank (COREP Annex II p.91; PS1/26 Annex II p.88; `v4721_m`, `boe_b0431`).
- **C 08.01 / OF 08.01** — CR IRB totals: one submission per IRB exposure class × own-estimates filter. 33 columns (CRR) / 40+ columns (Basel 3.1) covering PD, original exposure, CRM substitution effects, CRM in LGD estimates (detailed collateral breakdown), exposure value, LGD, maturity, RWEA, expected loss, provisions, obligor count. Basel 3.1 adds post-model adjustment and output floor columns. Column 0010 (PD) is in both layouts (PS1/26 Annex I; taxonomy table `OF08.01.01.01`, no cell on rows 0080 and 0170): the exposure-weighted average of the post-input-floor `pd_floored` over the row's legs that carry a PD, so a row of slotting exposure alone reports none (`boe_b0356`, `boe_b0410`; `corep/c08_sheets.py::pd_average`). Column 0250 (maturity) is empty on a retail sheet in both regimes and both C / OF 08.01 and 08.02 ("This column shall therefore not be filled in for the exposure class 'retail' or for exposures subject to the slotting approach", PS1/26 Annex II p.111; CRR Annex II p.104), so the A-IRB Total's maturity is the average over its non-retail legs (`c08_sheets.py::sheet_spec`). Columns 0230 (LGD), 0240 and 0250 (maturity) are, like column 0010, the exposure-weighted average over the row's legs that carry the parameter (`c08_sheets.py::parameter_average`), so a slotting leg is left out rather than averaged in as zero: PS1/26 Annex II p.111 excludes slotting from both columns 0230 and 0250 (CRR Annex II p.103 from column 0230; for column 0250 CRR p.104 names retail only and the CRR cell is left out because no Article 162 maturity is carried for slotting). A row of slotting exposure alone reports neither, and a row that holds F-IRB specialised lending beside slotting (Basel 3.1 sheet 0010; CRR `specialised_lending`; slotting is assigned to exposure class specialised lending only) reports the F-IRB legs' figure. The exclusion is per leg, not per sheet, because sheet 0010 also holds F-IRB specialised lending. Basel 3.1 OF 08.01 reports a cell only where its published sheet has one: the cells the PRA001 taxonomy lacks per sheet are declared in `corep/of08_published_cells.py`, held to the taxonomy by `tests/contracts/test_of08_published_cells.py`, and left empty on every sheet after the Totals are built (`c08_sheets.py::reported_sheets`) — sheet 0019's r0017 / r0020 column 0035 netting is in Total 0001 and not on sheet 0019 (Bank known-issues log item 25). Row 0010 is broken down twice over the same columns, in both regimes: by balance-sheet side (rows 0020-0060) and by IRB treatment (rows 0070 + 0080 + 0170 + 0180, plus 0160 under CRR). Rows 0017 / 0015 / 0016 ("of which") and 0175 (purchased receivables, also in row 0070) are in neither sum. The CRM substitution inflow (column 0080) lands on row 0010, on row 0020 or 0030 by the side of the covered leg, and on row 0070 or 0080 by the treatment it is reported under (`corep/c08_01_rows.py::INFLOW_KEYS`). Under Basel 3.1 the PRA001 taxonomy has no row 0080 cell in column 0080, so an inflow reported under slotting would reach no treatment row; no registered population has one. The Bank withdrew its two rules for these identities (`boe_b0744` / `boe_b0745`) in taxonomy v4.1.1, and EBA `v0337_m` / `v0338_m` cover the CRR side on some columns only, column 0080 in neither. `tests/acceptance/reporting/test_of08_01_row_decompositions.py` checks both identities in both regimes, on every C 08.01 sheet (Totals included) of every registered IRB run and of a synthetic book whose substitution inflow is off-balance-sheet. The registered runs' inflow is all on-balance-sheet, so the book is the only one of these populations with inflow on row 0030. Rows 0040-0060, 0160, 0170 and 0180 are empty in every one of these populations, so their place in the sums is not exercised. On Basel 3.1 the test reads each sheet's columns from the PRA001 pack. Columns that do not add across rows (0010, 0230, 0240, 0250, 0300) are left out, and so is any column the taxonomy publishes on row 0010 but not on the breakdown row the money must reach: the "of which" columns and 0310 on the balance-sheet axis, 0125 and 0310 on the treatment axis. On a sheet holding slotting exposure, row 0080 has no cell for the output-floor columns 0275 / 0276, so row 0010 exceeds the sum of the treatment rows there by the slotting legs' figure, which no treatment-row cell carries; the test leaves both columns out of the treatment split on those sheets. Column 0275 is a standardised-basis exposure value (Art. 111, for exposures risk-weighted under Articles 113-134; PS1/26 Annex II p.112) that the generator still builds from the IRB exposure value (open plan items P2.27 / P1.474), so a slotting leg's column 0275 is not required to equal its column 0110.
- **C 08.02 / OF 08.02** — CR IRB by obligor grade: same columns as C 08.01 with dynamic rows (one per firm-specific internal rating grade/pool, ordered by PD).
  A defaulted leg reports on the "Default (100%)" row, after every performing grade ("PD of obligors in default shall be 100%"; "The last reported grade or grades (or pool) shall be that of exposures in default"), also when the firm's grade column still gives it a performing grade (`corep/c08.py::_c08_02_keyed`).
- **PD of defaulted obligors (C / OF 08.01–08.05, 09.02, CR6, CR9)** — every IRB leg with `is_defaulted = True` carries `pd = pd_floored = 1.0` (CRR / PS1/26 Art. 160(3), 163(2); `engine/irb/adjustments.py::apply_defaulted_treatment`), so it sits in row 0170 "100 (Default)" of C / OF 08.03 and 08.05 on both regimes' row bases and enters every exposure-weighted PD average at 100%. The firm's own estimate stays on `internal_pd`. See [Defaulted Exposures](basel31/defaulted-exposures.md), including the recorded C / OF 08.05 back-testing decision.
- **C 08.03 / OF 08.03** — CR IRB PD ranges: one submission per IRB exposure class. 11 columns covering on/off-BS, avg CCF, exposure value, avg PD, obligors, avg LGD, avg maturity, RWEA, EL, provisions. Rows are 17 fixed PD range buckets (0.00–0.15 through 100% default). Basel 3.1: row allocation uses pre-input-floor PD ("PD RANGE (PRE-INPUT FLOOR)") while the PD column value reports post-input-floor PD ("EXPOSURE WEIGHTED AVERAGE PD (POST INPUT FLOOR)"). Supporting factors removed, slotting excluded.
- **C 08.04 / OF 08.04** — CR IRB RWEA flow statements: one submission per IRB exposure class. 1 column (RWEA), 9 rows (previous period, 7 movement categories, current period). Virtually identical between CRR and Basel 3.1 (supporting factors no longer mentioned).
- **C 08.05 / OF 08.05** — CR IRB PD back-testing: one submission per IRB exposure class. 5 columns (arithmetic average PD, prior-year obligor count, of which defaulted, observed default rate, historical annual default rate), 17 fixed PD range buckets (same as C 08.03). Basel 3.1: col 0010 explicitly post-input floor; row allocation uses pre-input-floor PD. Slotting and CCR exposures excluded. See [corep-reporting.md](../features/corep-reporting.md#c-0805-of-0805-cr-irb-pd-back-testing) for the full column structure.
- **C 08.06 / OF 08.06** — CR IRB specialised lending slotting: one submission per SL type. 10 columns (CRR) / 11 columns (Basel 3.1 adds col 0031 "(-) Change in exposure due to FCCM" — a deduction column between original exposure and exposure value). Rows by slotting category (1–5) × maturity band. The maturity band is the sealed `slotting_short_maturity_rw_applied` (P1.204): the remaining maturity, except that a Basel 3.1 short-dated Strong / Good exposure of a firm without the PS1/26 Art. 153(5)(d) election is weighted on Table A column B / D and reported on the ≥ 2.5-year row; Satisfactory / Weak / Default exposures (one Table A column each) and every CRR exposure follow their remaining maturity. Pillar 3 CR10 cuts its rows on the same band, and a projected legacy ledger derives it from the firm's maturity band. Basel 3.1 adds "substantially stronger" sub-categories (reported in both row 0015 and 0025 when both criteria met) and separates HVCRE from IPRE (5 SL types vs 4).
- **C 08.07 / OF 08.07** — CR IRB scope of use: one submission covering all exposure/roll-out classes. 5 columns (CRR) / 18 columns (Basel 3.1 — significantly expanded with RWEA breakdown by SA reason and materiality thresholds). Rows change from exposure classes to roll-out classes (Art 147B).
- **C 09.01 / OF 09.01** — CR GB 1 geographical breakdown SA: one submission per country. 13 columns (CRR) / 10 columns (Basel 3.1) covering original exposure, defaults, provisions, exposure value, RWEA. Rows by SA exposure class. Basel 3.1: supporting factor columns removed, real estate rows restructured (regulatory residential/commercial RE sub-rows).
- **C 09.02 / OF 09.02** — CR GB 2 geographical breakdown IRB: one submission per country. 17 columns (CRR) / 13 columns (Basel 3.1) covering exposure, defaults, provisions, PD, LGD, RWEA, EL. Basel 3.1: adds defaulted exposure value column, removes supporting factors and SF columns, adds corporate sub-rows, restructures retail RE rows, removes equity.

### Missing Templates (Not Yet Documented)

- **OF 08.05.1** — PD Backtesting External Rating Equivalent: Extension of OF 08.05 for Art. 180(1)(f) ECAI-based estimates. Col 0005 uses firm-defined PD ranges (variable-width, not fixed buckets). Col 0006 provides one column per ECAI considered showing external rating equivalents. Columns 0010-0050 same as OF 08.05.
- **OF 34.07** — IRB CCR Exposures by Exposure Class and PD Scale: 7 columns — col 0010 exposure value, col 0020 exposure-weighted average PD (post-floor), col 0030 number of obligors, col 0040 EWA LGD, col 0050 EWA maturity (years), col 0060 RWEA, col 0070 density of RWEA (col 0060 / col 0010). Required for any firm using F-IRB or A-IRB for CCR, regardless of CCR valuation method (SA-CCR, IMM, etc.). Excludes CCP-cleared exposures.

### Basel 3.1 Reporting Field Additions

**OF 07.00 (SA)** — new columns vs CRR C 07.00:
- Col 0035: (-) Adjustment for on-balance sheet netting (Art. 219) — the netted deposit's **adjusted** value (after the Art. 224 currency-mismatch haircut and the Art. 237-239 maturity scaling), capped at the exposure it reduces. The deposit is reported here and **excluded** from cols 0130 / 0140, so col 0150 is reduced by it once (`boe_b0471`). CRR C 07.00 has no col 0035 and keeps the deposit in col 0130.
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
- Col 0254: Unrecognised exposure adjustments (Art. 153(5A)(b), 154(4A)(c)) — not reported for F-IRB or slotting sheets (PS1/26 Annex II p.112); empty on those sheets and their Total 0002 in OF 08.01 and OF 08.02 (`c08_sheets.py::sheet_spec`). The engine adds the adjustment to Advanced IRB legs only (Art. 166D(6), P1.399), so column 0260 on those sheets still equals 0251 + 0252 + 0253
- Col 0260: Risk-weighted exposure amount **after** adjustments — equals col 0251 adjusted for cols 0252 to 0254 (i.e. `0251 + 0252 + 0253 + 0254`). This is the post-adjustment RWEA that flows into OF 02.00's IRB class rows (0271–0410, column 0010; each is one data point with this cell on the class's sheet) and through them into rows 0240, 0040 and 0010. Source: PS1/26 Annex II §3.3.1, p. 112.
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
- Row 0034: Output floor activated (Yes/No indicator, not RWEA) — column 0030 only
- Row 0035: Output floor multiplier (the rate 0.55 / 0.60 / 0.65 / 0.70 / 0.725 per `boe_b0359`, not a percentage and not RWEA) — column 0030 only
- Row 0036: Output floor adjustment OF-ADJ (monetary value) — column 0030 only
- Rows OF 02.00 does **not** have, which the CRR C 02.00 does: 0190 (short-term credit assessment), 0260 / 0320 (IRB central governments), 0330 (A-IRB institutions), 0370 / 0380 (retail real estate SME / non-SME, replaced by 0382–0385) and 0420 (Equity IRB)

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

    Row 0341 therefore carries **every** not-materially-dependent regulatory CRE
    leg, SME or not: 0340 = 0341 + 0342 (`boe_b0732`) and 0343 ≤ 0341
    (`boe_b0960`), and 0344 ≤ 0342 likewise. Until 2026-11 row 0341 excluded the
    SME legs, so an SME leg sat in 0343 and in neither summand of 0340 (plan
    P1.378). The generator lists the rows in the taxonomy's order, 0341, 0343,
    0342, 0344.

!!! info "The SME flag: rows 0020, 0343 and 0344"
    Row 0020 is "All exposures to SMEs as defined in the Glossary Part" (Annex II
    p.88; CRR Annex II C 07.00: "All exposures to SME"), and 0343 / 0344 are
    "Exposures to SMEs ... within Article 124H / 124I". The flag behind them, and
    behind the C 09.01 "of which: SME" rows defined by reference to row 0020, is
    the obligor's sealed `is_sme` (with the Basel 3.1 `exposure_subclass`),
    OR-ed with an exposure class whose name contains "sme"
    (`reporting/corep/sme_flag.py`, one function C 07.00 and C 09 both call). It
    used to read the class name alone. The loan-splitter renames an SME's secured
    leg `residential_mortgage` (both regimes) or `commercial_mortgage`, and an
    SME's specialised-lending exposure keeps the `specialised_lending` class, so
    those legs reached no SME row while `is_sme` said SME (plan P1.339). Not
    covered: an SME's ADC exposure and a retail-qualifying SME, for which the
    classifier's `is_sme` is False.

!!! info "0330, 0340, 0350 and 0360: the limb the weight was set under"
    The four parent rows are the three Art. 124 limbs, and no leg is in two of
    them. A leg's limb is the one the Basel 3.1 SA dispatcher's real-estate route
    places it in, read by evaluating the dispatcher's own predicates
    (`b31_real_estate_route`) on the leg (`reporting/corep/re_limbs.py`), first
    match in its order. It is the branch the leg's weight is computed on unless
    an earlier dispatcher branch pre-empts the real-estate ones (subordinated
    debt's flat 150%, for one):

    1. **0360**: ADC (`is_adc`), even where the leg also meets the other-real-estate
       test below (attested non-qualifying, or no LTV). Art. 124K wins over
       Art. 124J as well as over Art. 124F-124I.
    2. **0350–0354**: other real estate (Art. 124J). Either the property is
       attested not to meet Art. 124A (`is_qualifying_re` False), or it has a
       `property_type` but no LTV. A property with no value fails Art. 124A(1)(d),
       "the value of the property is determined in accordance with Article
       124D". 0351/0352 versus 0353/0354 follow the Art. 124J(2)/(3) test the
       weight applies: residential where `property_type` is residential, else
       commercial.
    3. **0330–0344**: regulatory real estate. The leg has an LTV, and its
       property side is the route's: commercial where the class or
       `property_type` says commercial, else residential. On a mortgage that
       carries its own LTV and no `property_type`, the class decides.

    PS1/26 Art. 124A(1) makes a regulatory exposure one that "is not an ADC
    exposure", and the Glossary defines an other real estate exposure as one
    "that is not a regulatory real estate exposure or an ADC exposure". On the
    `real_estate` sheet, 0330 + 0340 + 0350 + 0360 equals row 0010 for every leg
    the route places in a limb. A real-estate-class leg with no ADC flag, no LTV,
    no `property_type` and no attested non-qualification matches no branch: the
    engine weights it by counterparty, and it would count in row 0010 alone.
    The one such shape measured, a mortgage product with no property linked, is
    classified `retail_other` and never reaches the sheet.

    OF 09.01 rows 0091–0094 have the "Same definition as" these four rows, and
    row 0090 is their "Sum". They take the same terms over the same derivation,
    so each OF 09.01 row holds exactly the legs of its OF 07.00 twin
    (`boe_b0978`–`boe_b0989`). A frame missing any column the route reads
    (`exposure_class`, `property_type`, `ltv`, `is_qualifying_re`, `is_adc`)
    reports no limb row in either template. The aggregator exit seals all five.

Source: PS1/26 Annex II §3.2, pp. 90–91 (OF 07.00) and p. 140 (OF 09.01) of
`docs/assets/ps1-26-annex-ii-reporting-instructions.pdf`; PS1/26 Art. 124,
Art. 124A(1), Art. 124J and the Glossary.

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
Transitional Approach period via memorandum row 0371 (row 0373 is the IRB Transitional
Approach's), but always allocated to row 0261 in Section 3.

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
    - **Loan-split real estate (Art. 124F / 124H, not materially dependent)** is
      reported *"in two parts, against the risk weight applied to the portion up to
      55% of the value of the property, and against the portion above 55% of the
      value of the property (if applicable)"* (Annex II p.94). **Implemented as:** the
      Basel 3.1 SA dispatcher records the secured share and both part weights on
      `sa_loan_split_secured_share` / `sa_loan_split_secured_rw` /
      `sa_loan_split_residual_rw`
      (`engine/sa/b31_risk_weight_tables.py::with_b31_loan_split_parts`; named once as
      `contracts/edges.py::LOAN_SPLIT_CARRIERS`; CONDITIONAL columns on every
      calculator edge and on `AGGREGATOR_EXIT_EDGE`, never produced under CRR).
      `reporting/kernel/rw_parts.py::split_risk_weight_parts` turns each
      such ledger row into two report rows before OF 07.00 is cut: every column a cell
      sums is split by the share (exposure) or by each part's share of the weight
      (RWEA), so the parts add back to the row, and each part bands on its own weight.
      A row is split only while the weight it is reported against still equals the
      recorded blend — the pre-multiplier weight where Art. 123B applied, so the RWEA
      keeps the multiplier — and a defaulted or otherwise re-weighted leg stays
      whole: Art. 127 runs after the dispatcher and leaves its record on the row, so
      the reader, not the engine, is what keeps a defaulted mortgage out of the
      20% / 75% rows. A covered leg Art. 235 substitution was applied to is split on
      the OBLIGOR's own weight (`pre_crm_risk_weight`, still the blend): its original
      exposure goes to the two part rows of the real-estate sheet, its exposure value
      whole to the protection provider's row (see the next note). Both parts stay on the real-estate sheet
      (Art. 112(2) Table A2 ranks real estate above retail and corporates;
      Art. 123(2)). Worked example
      (`b31/rich`, `RP-LN-RRE`, 400,000 at 60% LTV to a natural person, 24.58% as a
      whole): row 0180 366,666.67 / RWEA 73,333.33, row 0220 33,333.33 / RWEA
      25,000.00, row 0280 empty, as `boe_b0445` requires on sheet 0010. No risk weight
      or RWEA changes. **Not yet:** the CRR template (the Art. 125 / 126 blend above
      the LTV limit, which lands in row 0280; the registered row past the limit is
      `RWL-LN-RE-105` in `crr/rw-ladder`), the residual leg of a loan the engine
      splits physically (still reported on the counterparty's sheet), Pillar 3 CR5
      (Annex XX carries the same sentence), and banding a non-split Art. 123B or
      junior-charge exposure on its un-multiplied weight — those two are still banded
      on the applied weight; no registered portfolio reaches either.
    - **A substituted covered part is reported in two risk-weight rows, one per
      basis.** Cols 0010-0040 are the original exposure "deducted from the
      obligor's exposure class" (Annex II p.84, cols 0090 / 0100) and the rows give
      "the allocation of risk weights within the respective exposure class" (p.94),
      so cols 0010-0150 of a covered part sit at the **obligor's own** risk weight on
      the obligor's sheet; from col 0150 on — cols 0160-0235, and the col 0100 inflow
      — they sit at the **protection provider's** weight on the provider's sheet (EBA
      Q&A 2014_1636 reads the identical C 07.00 text the same way). **Implemented
      as:** `reporting/corep/c07_rw_bands.py` derives two bands, `c07_rw_band` (the
      post weight) and `c07_rw_band_origin` (the obligor's `pre_crm_risk_weight`
      wherever `is_guarantee_beneficial` is true — the protection was applied — else
      the post weight; `reporting/kernel/bases.py::origin_risk_weight`); a
      risk-weight row's origin cells key the second, its post cells the first, and
      the row is non-empty when a leg is on the sheet under a basis at that basis's
      band. A same-class substitution therefore reports one leg in two rows of one
      sheet. Worked example (`crm-substitution`, S4: an unrated corporate loan of
      8,000,000, 2,800,000 covered by a CQS 2 institution): corporates row 0230
      (100%) c0010 = c0040 = 8,000,000 and c0150 = c0200 = c0220 = 5,200,000;
      corporates row 0182 (30% under Basel 3.1; row 0200, 50%, under CRR) empty, as
      the Bank's `boe_b0441` / `boe_b0441_1` require; institutions row 0182
      c0150 = c0200 = 4,300,000 (its own 1,500,000 and the 2,800,000 inflow),
      c0220 = 1,290,000. No risk weight or RWEA changes. **Not yet:** the Financial
      Collateral Simple Method and the Art. 232 other-funded methods still weight
      the covered part inside one blended row (P1.347), and a covered leg the due
      diligence override or the Art. 113(6) intra-group 0% re-weights after
      substitution is banded on its own weight as it stood before those steps.
    - Equity exposures under the Standardised Transitional Approach (Rules 4.1–4.10
      of the Credit Risk: General Provisions (CRR) Part) are allocated to rows 0250
      and 0261 per Art. 133, and additionally reported against memorandum rows
      0371–0374 for the transitional period (expiring 1 January 2030). The
      memorandum reporting in 0371–0374 does **not** affect the primary allocation
      to 0250 / 0261.
    - **Implemented as:** `reporting/corep/c07_rw_bands.py::rw_band_expr` bands a leg on
      `risk_weight_pre_equity_transitional` (the Article 133 weight the rules
      4.2 / 4.3 weight replaced) where it is set, and on `risk_weight` otherwise,
      so a 160% leg reports in row 0250 and a 220% leg in row 0261 with col 0220
      at the transitional RWEA; row 0280 stays empty on the class (p) sheet, as
      the Bank's `boe_b0458` requires. Rows 0371–0374 key the
      `equity_transitional_approach` / `equity_higher_risk` carriers on the class
      (p) sheet only (¶55A; the Bank publishes OF 07.00.01.04 on sheet 0016
      alone). The three carriers are sealed on `AGGREGATOR_EXIT_EDGE`; the
      equity calculator sets them only on legs whose weight rules 4.2 / 4.3
      assigned (firms without IRB permission, 2027–2029). Rows 0373 / 0374 stay
      empty until rules 4.4–4.6 (IRB permission) are implemented. Registered
      book: `tests/fixtures/reporting_equity_transitional_portfolio.py`
      (`b31/equity-transitional`).
    - **Bank-rule conflict (publisher issue PI-01).** A correct return of such
      equity fails `boe_b1016` / `boe_b1031` (ERROR, Total sheet: RWEA ≥ 2.5× /
      4× exposure value on rows 0250 / 0261) and `boe_b0491` / `boe_b0506`
      (WARNING, sheet 0016: RWEA = 2.5× / 4×), because every rules 4.2 / 4.3
      weight is below the row weight; and `boe_b0710_2` (ERROR) on rows 0371 /
      0372, because an on-balance-sheet holding has no conversion-factor
      breakdown. These are banked in the supervisory register as rule limits;
      the figures are not altered to satisfy them.
    - **Memorandum rows 0300 / 0320 — exposures in default, by the class before
      default.** Row 0300 is the "in default" class at 100% (Art. 127(1)(b) and (3)),
      row 0320 at 150% (Art. 127(1)(a)); *"the figures reported, however, are the same
      as used to calculate the risk-weighted exposure amounts in the exposure class
      'exposures in default'"* (PS1/26 Annex II ¶54). Under Basel 3.1 each leg is
      reported on the Total and on the sheet of the class it would otherwise have had,
      where table OF07.00.01.03 publishes the rows (sheets 0002–0004 and 0007–0009).
      An MDB- or international-organisation-origin default goes on the Total only
      because the taxonomy publishes no sheet for either class in that table (¶52
      leaves both out, although the row 0300 / 0320 instructions read "Article
      112(1)(a) to (i)"; the sheet set is held to the taxonomy both ways by
      `tests/contracts/test_of07_published_cells.py`). A real-estate-origin default
      also goes on the Total only: ¶52 does list real estate, but sheet 0010 is
      missing from the table, and the Bank of England known-issues log (November
      2026, #27) tells firms to report it on the Total sheet alone until that sheet
      is added. The "in default" sheet carries neither row
      (`reporting/corep/c07_sheet_scope.py`). Under CRR the rows are still keyed on
      the applied class, so they appear on the Total and the "in default" sheet
      (COREP Annex II ¶55) and not yet on the obligor's class sheet (P1.377). A
      covered defaulted part keeps its original exposure (c0010) in the obligor's memo
      row at the Art. 127 weight; its exposure value and RWEA (c0200 on) are the
      protection provider's, on the provider's sheet at the provider's weight, and are
      not in the memo row. Registered book:
      `tests/fixtures/reporting_default_populations_portfolio.py`
      (`crr/default-populations`, `b31/default-populations`; P5.80) — provisioned
      defaults either side of the 20% threshold on the central-government, regional,
      PSE, institution and retail sheets; a defaulted corporate 40% guaranteed by a
      CQS 2 institution (50% under CRR, 30% under Basel 3.1 — a non-zero weight, so
      the RWEA that crosses to the institution's sheet is a figure); a
      real-estate-origin default that takes 100% under Art. 127(3) despite a 5%
      provision, in both regimes (CRR: the whole loan is secured within Art. 125's
      80%); and under Basel 3.1 a defaulted high-risk leg beside a performing one (row
      0015 on sheet 0012) and an Art. 124F loan split guaranteed by the UK sovereign at
      0%. A correct return of it fails `boe_b0350`
      (OF 09.01 c0010 ≥ c0020, WARNING) on every class row whose obligors are all in
      default: publisher issue PI-28, banked as a rule limit. Its Basel 3.1 Pillar 3
      CR4 / CR5 row 11 ("Items associated with particularly high risk") is still null
      while row 17 (Total) holds both high-risk legs (700,000 defaulted + 450,000
      performing = 1,150,000 original exposure, 1,725,000 RWEA at 150%): the open
      P3.7(a) stranding, not a property of the book.
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
`docs/assets/` is git-ignored, so none of these files is in a fresh clone or a git worktree: `scripts/download_docs.py` fetches every one of them from the Bank of England. `tests/contracts/test_asset_manifest_coverage.py` fails a `docs/assets/<name>` citation in a tracked file that its manifest cannot fetch. For Basel 3.1 OF 02.00 and OF 07.00 the tracked PRA001 taxonomy pack (`packages/rwa-filer/src/rwa_filer/taxonomy/data/pra001-4.1.1/pack.json`, tables `OF02.00.01.01` and `OF07.00.01.0x`) also carries the published row and column codes, and needs no download.

- `docs/assets/CRR - corep-own-funds.xlsx` — CRR template layouts (sheets "2", "7", "8.1", "8.2", "8.3", "8.4", "8.6", "8.7", "9.1", "9.2")
- `docs/assets/crr-annex-ii-reporting-instructins.pdf` — CRR reporting instructions
- `docs/assets/0F07 - annex-i-of-07-00-credit-risk-sa-reporting-template.xlsx` — Basel 3.1 OF 07.00 layout
- `docs/assets/OF0801-annex-i-of-08-01-credit-risk-irb-reporting-template.xlsx` — Basel 3.1 OF 08.01 layout
- `docs/assets/OF0802-annex-i-of-08-02-credit-risk-irb-reporting-template.xlsx` — Basel 3.1 OF 08.02 layout
- `docs/assets/ps1-26-annex-ii-reporting-instructions.pdf` — Basel 3.1 reporting instructions

### Status
- Generator: Complete — all COREP credit-risk template families are declarative per-template modules (`reporting/corep/{c02,c07,c08,c09,c34,of02}.py`) through the one executor (`reporting/cellspec.py`), C 02.00 as the recorded pre-pass-kernel hybrid: C/OF 02.00, 07.00, 08.01–08.07, 09.01, 09.02, OF 02.01, and the four in-scope C 34 counterparty-credit-risk templates (C 34.01/02/04/08 in `reporting/corep/c34.py` — R27a the single-frame trio, R27b the multi-sheet per-netting-set C 34.02). No credit-risk COREP template remains on the legacy `generator.py` path.
- OF 02.01: Complete — `reporting/corep/of02.py::generate_of_02_01` populates the credit-risk row (0010, excl. CCR), the CCR row (0020) and the Total row (0080 = their sum); cols 0010/0020 partition the book (modelled vs its complement) and col 0030 = 0010 + 0020 = U-TREA. Rows 0030–0070 (CVA/securitisation/market/op risk/other) are null — out of scope.
- Template definitions: all templates use 4-digit COREP column references and multi-section row structures. The Basel 3.1 layouts are held to the PRA001 v4.1.1 taxonomy pack by one contract test, `tests/contracts/test_b31_layouts_held_to_the_pack.py`, whose population is every bundle member a table is bound to in `reporting/filing/bindings.py`: column and row codes in both directions, the sheet axis (the binding's shape, and a published place for every sheet a book generates), no generated figure — a zero included — where the published sheet has no cell, and, where a code could carry another template's meaning, a label that states the published one. The sheet and cell limbs run on one hand-built book that must report a non-zero figure for every bound member, so none passes them with nothing to check. What diverges today is listed in its `KNOWN_DIVERGENCES`, each entry naming the plan item that owns the fix; the comparison is exact, so a fix must shrink its entry. Measured divergences (2026-11-23):
    - **OF 02.00** — settlement/delivery and CVA risk are laid out empty: totals 0490 and 0640 are null and their breakdown rows 0500 / 0510 (settlement/delivery risk in the non-trading / trading book) and 0642 (BA-CVA) are not declared (a new item). The engine computes both. Its DvP failed trades (CRR Art. 378, `engine/ccr/failed_trades.py`, `regulatory_band` `dvp_*`) are not missing but misplaced: they reach the exposure frame as SA own-funds lines, so OF 02.00 reports them as SA credit risk — rows 0040 / 0050 / 0060 and the obligor's class row — and C 07.00 on the class sheet, in both regimes, while 0490 / 0500 / 0510 stay empty. The free deliveries the same module computes (Art. 379) rightly stay in credit risk: row 0040 is "... and free deliveries", and Annex II's CR SETT instructions (para 105) exclude them. A Table 2 Column 4 free delivery carries the same `risk_type` as a DvP leg, so the fix moves the DvP legs by band; adding `failed_trades_rwa` to 0490 as a roll-up would count the DvP RWEA twice and take the free deliveries out of credit risk. BA-CVA (PS1/26 CVA Risk Part Chapter 4, `AggregatedResultBundle.cva_rwa`) is in no OF 02.00 row, so the total risk exposure amount (0010) is understated by it. Rows for what the engine does not compute — market risk by approach, SA-CVA (0641, deferred under P8.61), AA-CVA (0643), the 0690 of-which rows and the investment-firm rows 0020 / 0030 — are left out of scope, each with its reason.
    - **OF 08.02** — generates OF 08.01's columns 0275 / 0276 and lacks 0105 / 0106; its 0101–0104 carry OF 08.01's slotting financial-collateral meaning where the published table has the 10% / 20% / 40% / 50% conversion-factor breakdown (P2.71).
    - **OF 08.06** — built on the CRR row grid (rows 0010–0120) where the published rows are 0005–0095, still generates column 0070, row 0025 means "Good — substantially stronger" where the published row is "Strong — less than 2.5 years", every published row the fix adds is anchored to its label (0005 is "Strong Preferential", not all of Strong; 0045 is "Good, less than 2.5 years remaining", not all of Good), and its sheets are keyed by our `sl_type` rather than the table's members (P2.72). Rows 0035 and 0055 are both published as "Other", so each is also held against the sibling block's word: 0035 (the rest of Strong) may not say "good", 0055 (the rest of Good) may not say "strong".
    - **C 08.04** — generated per exposure class against a table with no sheet axis (P2.73).
    - **OF 09.01 / OF 09.02** — OF 09.02 generates a central-government row 0010 the published IRB breakdown does not have, and both report a figure where the published table has no cell: OF 09.01 row 0100 column 0020 (a zero) and OF 09.02 row 0045 (slotting) columns 0080–0100 (P2.85 for the slotting row; a new item for the other two).
    - **C 34.01 / .02 / .04 / .08** — not the published templates under those codes: PRA001's C 34.01 is the size of the derivative business, C 34.02 CCR exposures by approach, C 34.04 the original exposure method and C 34.08 the composition of collateral, while ours are SA-CCR by approach, EAD per netting set, CVA capital and CCP exposures. C 34.01 / .04 / .08 figures are placed on cells that mean something else — our C 34.04 CVA RWEA sits on the published "Number of transactions" (P2.101, which records only partial rows and columns). The fix re-targets the figures: relabelling our rows and columns to the published labels would clear the meaning limb and leave every figure on the wrong cell, and adding the missing rows and columns would build on the wrong templates. C 34.02's sheet axis is fixed (0001 all CCR exposures, 0002 all but CCPs), not open; we key it by netting set and bind it without a sheet map.
    - **OF 08.05.1** (`OF08.05.01.01`) is bound to our OF 08.05 frame but is a separate, conditional template we do not generate; the test leaves it out of the population, and its three rules are evaluated on our OF 08.05 frame.
- Excel export: Complete — produces per-exposure-class sheets for all templates.
- Integration: Done (`ResultExporter.export_to_corep()`, `CalculationResponse.to_corep()`)
- Tests: Complete — 700+ COREP tests across multiple test files covering all template families.
- Known sub-gaps:
    - **C 07.00 / OF 07.00**: Section 2 rows 0090 (SFT netting sets) / 0100 (of which QCCP) / 0110 (derivative and long-settlement netting sets — the additive parent) / 0120 (of which QCCP) are **populated**, as are columns 0210 / 0211 ("Of which: arising from CCR" / the same excluding Art. 301(1) CCP-cleared contracts). C 07.00 covers counterparty credit risk: Annex II rows 0070/0080 direct CCR exposures to rows 0090–0130, and C 34 is not an alternative to it. Row 0130 (contractual cross-product netting sets, Art. 295(c)) is null — **not modelled**, there is no input carrier for a cross-product netting agreement.
    - **C 08.01 / OF 08.01**: Section 2 rows 0040–0060 (SFT, derivatives, cross-product netting) always null — **not** because CCR is out of scope, but because the engine risk-weights CCR under SA-CCR, so it reports in C 07.00 rows 0090–0130 rather than in an IRB template; these rows carry no binding, so an IRB-routed CCR exposure would not be broken out. B31 rows 0031, 0032, 0001, 0033, 0034, 0035 (off-BS breakdown by conversion factor: 10%, 20%, 40%, 50%, 100%, own estimate) are reported, each leg in one row (`corep/ccf_buckets.py`). Column 0130 ("Of which: arising from CCR") null (same reason). Column 0120 ("Of which: off balance sheet" under Exposure Value) null (Phase 2B). Column 0030 ("Of which: LFSE") null (Phase 2F).
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
- **UKB CR5** — SA risk weight allocation by exposure class (point (e) of Art. 444). Fixed format. The published layout (PS1/26 Annex XIX, sheet 'UKB CR5', rows 11–12) puts 27 named risk weights in columns a–y and aa–ab: 0%, 2%, 4%, 10%, 15%, 20%, 25%, 30%, 35%, 40%, 45%, 50%, 60%, 65%, 70%, 75%, 80%, 85%, 100%, 105%, 110%, 130%, 135%, 150% and 250% (at y), then 400% (aa) and 1250% (ab). Column ac is "Others", ad "Total" and ae "Of which unrated", followed by the ba–bd exposure breakdown. **The template does not use the letter z, and it has no 300% column**: a leg at a weight no column names (a blended CIU look-through weight, for example) is reported in ac. `reporting/pillar3/templates.py` writes each column letter out beside its weight (`_B31_CR5_BANDS`) rather than deriving it from position, so the gap at z stays where the template puts it. Rows are the SA exposure classes. Regulatory real estate not materially dependent on cash-flows is split into two rows: portion up to 55% of property value, portion above 55%. Exposures subject to the Art. 123B currency-mismatch multiplier are reported against the base (pre-multiplier) risk weight, but the RWEA column reflects the multiplier.
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
- Basel 3.1 template workbooks — the published layouts. The band labels and column letters of a fixed-format template are only in its workbook; the instruction PDFs give column *ranges*. Each is fetched by `scripts/download_docs.py`:
    - `docs/assets/ps1-26-annex-xix-credit-risk-sa-disclosure-templates.xlsx` — UKB CRD, CR4, CR5. The template annex is **XIX**, as the Disclosure (CRR) Part Art. 11(b)–(c) names it (`docs/assets/ps126app1.pdf` page 468, link 6.50 on page 471). Annex XX is the instructions, although its own text says CR5 is "as presented in Annex XX".
    - `docs/assets/ps1-26-annex-xxi-credit-risk-irb-disclosure-templates.xlsx` — UKB CRE, CR6, CR6-A, CR7, CR7-A; UK CR8, CR9, CR9.1
    - `docs/assets/ps1-26-annex-xxiii-credit-risk-irb-disclosure-templates.xlsx` — UKB CR10
    - `docs/assets/ps1-26-annex-xxv-ccr-disclosure-templates.xlsx` — Table UK CCRA; UKB CCR1, CCR3; UK CCR4, CCR5, CCR6, CCR7, CCR8 (instructions: Annex XXVI)
    - `docs/assets/ps1-26-annex-i-output-floor-and-capital-summaries-disclosure-templates.xlsx` — UKB OV1, KM1, CMS1, CMS2; UK INS1, INS2, OVC
- **CMS1 / CMS2**: the templates are listed in **Annex I** and the row/column instructions live in **Annex II** of the Disclosure (CRR) Part. Article 2a (*Disclosure of Output Floor*) of the Disclosure (CRR) Part — `docs/assets/ps126app1.pdf` page 467 — establishes that institutions shall make the Article 456(1) output-floor disclosures using Templates UKB CMS1 and UKB CMS2 of Annex I "and the relevant instructions set out in Annex II". The PS1/26 PDF references the Annex I templates and Annex II instructions only via inline hyperlinks (`docs/assets/ps126app1.pdf` page 470, §6.2A "Annex I Template UKB CMS1 can be found here" and §6.2B "Annex I Template UKB CMS2 can be found here"). `scripts/download_docs.py` fetches both: the templates as `docs/assets/ps1-26-annex-i-output-floor-and-capital-summaries-disclosure-templates.xlsx` and the instructions as `docs/assets/ps1-26-annex-ii-output-floor-and-capital-summaries-disclosure-instructions.pdf`. Note: the local file `docs/assets/ps1-26-annex-ii-reporting-instructions.pdf` is the **COREP supervisory** reporting Annex II — **not** the Pillar III Disclosure Annex II that contains CMS1/CMS2 instructions.

### Status
- Documentation: Done — see [Pillar III Disclosures](../features/pillar3-disclosures.md)
- Code implementation: Done — 13 declarative templates (OV1, CR4-CR10, CR9/CR9.1, CMS1/CMS2), one module each under `reporting/pillar3/`, through the one executor (`reporting/cellspec.py`)

## Export

### Status
- Parquet export: Done
- CSV export: Done
- Excel (XLSX) export via xlsxwriter: Done
