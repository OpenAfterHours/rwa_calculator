---
name: crr
description: >
  Look up UK CRR (Capital Requirements Regulation) credit risk rules. Use when you need
  SA risk weights, IRB parameters, CCFs, credit risk mitigation haircuts, slotting tables,
  supporting factors, provision treatment, or exposure classification under the current
  CRR framework (EU 575/2013 as onshored, effective until 31 Dec 2026).
---

# CRR — Capital Requirements Regulation Reference

The UK CRR (EU Regulation 575/2013, as onshored) defines the current credit risk framework
for UK banks, effective until 31 December 2026 when Basel 3.1 takes over.

## Where the numbers live

**This skill does not state regulatory values.** Every value table in the reference files
below is generated from the rulepack (`src/rwa_calc/rulebook/packs/{common,crr}.py`) by
`uv run python scripts/generate_regulatory_tables.py`, and
`scripts/check_skill_values.py` fails the build if a value is reintroduced as prose.

When you need a number:

1. **Read the generated table** in the relevant reference file — each `### entry_name`
   heading is the literal pack key, with its citation.
2. **Or grep the pack**: `rg 'corporate_risk_weights' src/rwa_calc/rulebook/packs/`.
3. **Or read the whole rendered pack**: `docs/data-model/regulatory-tables.md`.

Use `docs/assets/crr.pdf` to *audit* a pack value you have reason to doubt — not for
routine lookup. If the PDF and the pack disagree, the fix goes in the **pack**.

## Quick Navigation

Use this guide to find the right reference file for your question:

| Question | Reference File |
|----------|---------------|
| What risk weight applies to exposure class X? | [references/sa-risk-weights.md](references/sa-risk-weights.md) |
| What are the FIRB/AIRB parameters (LGD, PD, correlation)? | [references/irb-parameters.md](references/irb-parameters.md) |
| What CCF applies to off-balance sheet item X? | [references/credit-conversion-factors.md](references/credit-conversion-factors.md) |
| What haircut applies to collateral type X? | [references/credit-risk-mitigation.md](references/credit-risk-mitigation.md) |
| What are the slotting risk weights / equity treatments? | [references/slotting-and-equity.md](references/slotting-and-equity.md) |
| How are provisions treated (SA vs IRB)? | [references/provisions-and-el.md](references/provisions-and-el.md) |
| What are the SME/infrastructure supporting factors? | [references/supporting-factors.md](references/supporting-factors.md) |
| How are exposures classified by entity type? | [references/exposure-classification.md](references/exposure-classification.md) |
| What must my COREP template tie out to? (EBA validation rules) | [references/reporting-validation-rules.md](references/reporting-validation-rules.md) |

## External Regulatory Sources

- **PRA Rulebook (CRR firms):** https://www.prarulebook.co.uk/pra-rules/crr-firms
- **UK CRR (legislation.gov.uk):** https://www.legislation.gov.uk/eur/2013/575/contents
- **Source PDF:** `docs/assets/crr.pdf` — use to verify specific articles against the authoritative text
- **EBA reporting frameworks (validation rules):** https://www.eba.europa.eu/risk-and-data-analysis/reporting/reporting-frameworks
- **EBA validation rules workbook (up to 3.5, 2026-06-10):** https://www.eba.europa.eu/sites/default/files/2026-06/12d2a6ae-9f58-47ab-a684-cdc9924ed4aa/%28up%20to%203.5%29%20EBA_validation_rules_2026-06-10.xlsx — raw at `docs/assets/eba-validation-rules.xlsx` (gitignored; `uv run python scripts/download_docs.py`), extract at `src/rwa_calc/reporting/validations/rules/crr-eba-v3.0-credit-risk.json`

## Project Specification Files

These are the authoritative implementation specs with full detail, test scenarios, and
acceptance test results:

| Spec File | Topic |
|-----------|-------|
| `docs/specifications/crr/sa-risk-weights.md` | SA risk weights for all exposure classes (CRR + Basel 3.1) |
| `docs/specifications/crr/firb-calculation.md` | Foundation IRB: supervisory LGD, PD floors, correlation, maturity |
| `docs/specifications/crr/airb-calculation.md` | Advanced IRB: own LGD/CCF, LGD floors (Basel 3.1), PMAs |
| `docs/specifications/crr/credit-conversion-factors.md` | CCFs for SA, FIRB, and AIRB |
| `docs/specifications/crr/credit-risk-mitigation.md` | Collateral haircuts, overcollateralisation, guarantees |
| `docs/specifications/crr/slotting-approach.md` | Specialised lending slotting and equity treatments |
| `docs/specifications/crr/provisions.md` | Provision resolution, EL comparison, EL shortfall/excess |
| `docs/specifications/crr/supporting-factors.md` | SME and infrastructure supporting factors |
| `docs/specifications/common/hierarchy-classification.md` | Counterparty hierarchy, rating inheritance, classification |

## Key CRR Articles

| Article(s) | Topic |
|------------|-------|
| Art. 111 | CCFs for off-balance sheet items |
| Art. 112-134 | SA exposure classes and risk weights |
| Art. 114 | Sovereign risk weights |
| Art. 120-121 | Institution risk weights — ⚠️ the CRR CQS 2 weight differs from the Basel 3.1 ECRA weight; never carry one into the other |
| Art. 122 | Corporate risk weights |
| Art. 123 | Retail risk weights |
| Art. 125 | Residential mortgage — LTV split, not a flat weight |
| Art. 126 | Commercial real estate — LTV plus rental-coverage test |
| Art. 127 | Defaulted exposures — threshold on provisions |
| Art. 133 | Equity risk weights |
| Art. 134 | Other items |
| Art. 138 | Multiple ECAI assessment resolution |
| Art. 143-154 | IRB approach (PD, LGD, correlation, K formula) |
| Art. 153(2) | FI correlation scalar |
| Art. 153(5) | Slotting approach for specialised lending |
| Art. 155 | Equity IRB simple method |
| Art. 158-159 | Expected loss and EL shortfall/excess |
| Art. 160(1), 163(1) | PD floors — note the **absent CGCB limb** |
| Art. 161-162 | Supervisory LGD values and effective maturity |
| Art. 166 | FIRB CCFs |
| Art. 192-241 | Credit risk mitigation (collateral, guarantees) |
| Art. 199 | Collateral eligibility — **IRB only** |
| Art. 201 | Eligible guarantors — exhaustive list, **no retail limb** |
| Art. 224 | Supervisory haircuts |
| Art. 230 | Overcollateralisation ratios |
| Art. 233 | FX mismatch haircut |
| Art. 238 | Maturity mismatch adjustment |
| Art. 501 | SME supporting factor |
| Art. 501a | Infrastructure supporting factor |

## CRR SA Exposure Classes (Art. 112)

1. Central governments and central banks (Art. 114)
2. Regional governments and local authorities (Art. 115)
3. Public sector entities (Art. 116)
4. Multilateral development banks (Art. 117)
5. Institutions (Art. 120-121)
6. Corporates (Art. 122)
7. Retail (Art. 123)
8. Secured by immovable property (Art. 124-126)
9. Defaulted exposures (Art. 127)
10. Equity (Art. 133)
11. Other items (Art. 134)

## Approach Decision Tree

```
Exposure
├── Is it equity? → Equity SA (Art. 133) or IRB Simple (Art. 155)
├── Is it specialised lending without PD model? → Slotting (Art. 153(5))
├── Does the firm have IRB permission for this class?
│   ├── Yes + internal PD available → IRB
│   │   ├── AIRB permission + own LGD? → A-IRB (Art. 153-154)
│   │   └── Otherwise → F-IRB (Art. 153, supervisory LGD Art. 161)
│   └── No (or no internal rating) → SA (Art. 112-134)
└── SA risk weight by exposure class and CQS
```
