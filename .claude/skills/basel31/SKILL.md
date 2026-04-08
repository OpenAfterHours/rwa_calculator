---
name: basel31
description: >
  Look up Basel 3.1 / PRA PS1/26 credit risk rules. Use when you need new SA risk weights
  (including RE loan-splitting, ECRA/SCRA, corporate sub-categories), IRB parameter floors,
  output floor mechanics, CCF changes, CRM method changes, slotting updates, or any
  difference between CRR and Basel 3.1. Effective 1 Jan 2027.
---

# Basel 3.1 — PRA PS1/26 Regulatory Reference

Basel 3.1 as implemented by PRA PS1/26 for UK firms, effective 1 January 2027. The
framework shifts emphasis from risk sensitivity to comparability and floors.

## Top 10 Changes from CRR

1. **Output floor** — IRB RWA floored at 72.5% of SA-equivalent (phased in 2027-2032)
2. **Supporting factors removed** — no SME (0.7619/0.85) or infrastructure (0.75) relief
3. **1.06 scaling factor removed** — ~5.7% IRB RWA reduction before output floor
4. **Differentiated PD floors** — class-specific (0.05%-0.10%) vs CRR uniform 0.03%
5. **A-IRB LGD floors introduced** — 0%-50% by collateral type (CRR had none)
6. **F-IRB supervisory LGD reduced** — senior corporate 45% -> 40%, secured reductions
7. **A-IRB restricted** — no AIRB for large corporates, FIs, banks (F-IRB only)
8. **Equity IRB removed** — SA only at 250%/400%
9. **RE becomes standalone class** — loan-splitting (20% secured / counterparty RW residual)
10. **New retail categories** — transactor 45%, payroll/pension 35%

## Quick Navigation

| Question | Reference File |
|----------|---------------|
| What changed overall? (master delta table) | [references/what-changed.md](references/what-changed.md) |
| What are the Basel 3.1 SA risk weights? | [references/sa-risk-weights.md](references/sa-risk-weights.md) |
| What are the new IRB floors and restrictions? | [references/irb-changes.md](references/irb-changes.md) |
| How does the output floor work? | [references/output-floor.md](references/output-floor.md) |
| What are the new CCF values? | [references/credit-conversion-factors.md](references/credit-conversion-factors.md) |
| What changed in CRM (haircuts, methods)? | [references/crm-changes.md](references/crm-changes.md) |
| What changed in slotting risk weights? | [references/slotting-changes.md](references/slotting-changes.md) |
| What changed in reporting templates? | [references/reporting-changes.md](references/reporting-changes.md) |

## External Regulatory Sources

- **PRA PS1/26:** https://www.bankofengland.co.uk/prudential-regulation/publication/2026/january/implementation-of-the-basel-3-1-final-rules-policy-statement
- **PRA PS1/26 Appendix 1 (full rules):** https://www.bankofengland.co.uk/-/media/boe/files/prudential-regulation/policy-statement/2026/january/ps126app1.pdf
- **BCBS CRE Standards:** https://www.bis.org/basel_framework/standard/CRE.htm
- **Source PDFs:** `docs/assets/ps126app1.pdf` (full rules), `docs/assets/comparison-of-the-final-rules.pdf` (delta summary) — use to verify specific articles against the authoritative text

## Project Specification & Comparison Files

| File | Topic |
|------|-------|
| `docs/framework-comparison/key-differences.md` | Comprehensive CRR vs Basel 3.1 comparison |
| `docs/framework-comparison/technical-reference.md` | Developer-facing parameter tables, haircuts, config |
| `docs/framework-comparison/impact-analysis.md` | Capital impact by portfolio type |
| `docs/framework-comparison/reporting-differences.md` | COREP template changes (C -> OF) |
| `docs/framework-comparison/disclosure-differences.md` | Pillar 3 template changes (UK -> UKB) |
| `docs/specifications/crr/sa-risk-weights.md` | SA risk weights (covers both CRR + Basel 3.1) |
| `docs/specifications/crr/airb-calculation.md` | A-IRB with Basel 3.1 LGD floors and PMAs |

## Key Regulatory Sections

| PRA PS1/26 Article | BCBS Section | Topic |
|--------------------|--------------|-------|
| Art. 92(5) | — | Output floor formula |
| Art. 111, Table A1 | CRE20.92 | SA CCFs (10%, 40% new) |
| Art. 112, Table A2 | CRE20.4 | Exposure class priority waterfall |
| Art. 114-121 | CRE20.7-21 | Sovereign, institution ECRA/SCRA |
| Art. 122, 122A-122B | CRE20.42-49 | Corporate + SA specialised lending |
| Art. 124A-124L | CRE20.71-85 | Real estate loan-splitting, LTV tables |
| Art. 127 | CRE20.87-90 | Defaulted exposures |
| Art. 133 | CRE20.52-57 | Equity (250%/400%) |
| Art. 146(3) | — | Post-model adjustments (PMAs) |
| Art. 153, 154 | CRE31-32 | IRB K formula, correlation, LGD floors |
| Art. 161, 162 | CRE32.12-24 | F-IRB supervisory LGD |
| Art. 163(1) | CRE30.55 | Differentiated PD floors |
| Art. 166C-166D | CRE32.25-27 | F-IRB/A-IRB CCFs |
| Art. 191A | CRE22 | CRM method decision tree |

## Basel 3.1 Exposure Class Waterfall (Art. 112, Table A2)

Priority ordering — highest-priority class applies when exposure meets multiple criteria:

1. Securitisation positions
2. CIU units/shares
3. Subordinated debt, equity and own funds instruments
4. Items associated with particularly high risk
5. Exposures in default
6. Eligible covered bonds
7. **Real estate exposures** (new standalone class)
8. International organisations
9. Multilateral development banks
10. Institutions
11. Central governments / central banks
12. Regional governments / local authorities
13. Public sector entities
14. Retail exposures
15. Specialised lending (new)
16. Corporates
17. Other items

## Transitional Schedule

### Output Floor Phase-In (Art. 92(5))

| Year | Floor % |
|------|---------|
| 2027 | 50.0% |
| 2028 | 55.0% |
| 2029 | 60.0% |
| 2030 | 65.0% |
| 2031 | 70.0% |
| 2032+ | 72.5% |

### Equity SA Phase-In (Art. 4.2/4.3)

| Year | Standard | Higher-Risk |
|------|----------|-------------|
| 2027 | 160% | 220% |
| 2028 | 190% | 280% |
| 2029 | 220% | 340% |
| 2030+ | 250% | 400% |

IRB transitional (Art. 4.4-4.6): firms with IRB permission use the **higher of** old
IRB methodology and transitional SA schedule. Opt-out available (irrevocable).
