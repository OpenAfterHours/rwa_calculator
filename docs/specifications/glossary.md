# Glossary

| Term | Definition |
|------|------------|
| **RWA** | Risk-Weighted Assets — credit exposures multiplied by risk weights to determine capital requirements |
| **CRR** | Capital Requirements Regulation (EU 575/2013 as onshored into UK law) — current Basel 3.0 implementation |
| **Basel 3.1** | BCBS finalisation of Basel III reforms, implemented in UK via PRA PS1/26, effective 1 Jan 2027 |
| **SA** | Standardised Approach — risk weights assigned by exposure class and external rating |
| **F-IRB** | Foundation Internal Ratings-Based — firm provides PD, regulator sets LGD/CCF |
| **A-IRB** | Advanced Internal Ratings-Based — firm provides PD, LGD, EAD, CCF |
| **Slotting** | Specialised lending approach — risk weights by supervisory category (Strong/Good/Satisfactory/Weak/Default). See [SlottingCategory and subgrades](#slottingcategory-and-subgrades-abcd) below. |
| **SlottingCategory** | The five-bucket supervisory grade enum (`STRONG`, `GOOD`, `SATISFACTORY`, `WEAK`, `DEFAULT`) defined in `domain/enums.py`. Under PRA PS1/26 Art. 153(5) Table A, the **Strong** and **Good** buckets are further refined into **subgrade columns A/B and C/D**; Satisfactory, Weak, and Default have a single column. See [SlottingCategory and subgrades](#slottingcategory-and-subgrades-abcd) below. |
| **CRM** | Credit Risk Mitigation — collateral, guarantees, and provisions that reduce capital requirements |
| **EAD** | Exposure at Default — estimated exposure amount at the time of default |
| **PD** | Probability of Default — estimated likelihood of obligor default within one year |
| **LGD** | Loss Given Default — estimated loss as percentage of EAD if default occurs |
| **CCF** | Credit Conversion Factor — converts off-balance sheet amounts to on-balance sheet equivalents |
| **CQS** | Credit Quality Step — standardised rating scale (1=AAA/AA, 2=A, 3=BBB, etc.) |
| **Output Floor** | Basel 3.1 minimum: IRB RWA must be at least X% of SA-equivalent RWA |
| **PRA** | Prudential Regulation Authority — UK banking regulator |
| **BCBS** | Basel Committee on Banking Supervision — global standard setter |
| **SME** | Small and Medium Enterprise — turnover < EUR 50m, eligible for supporting factor |

## Regulatory Definitions (PRA PS1/26)

Long-form regulatory definitions introduced by PRA PS1/26 Appendix 1 (effective 1 January
2027). Quoted verbatim from the PS1/26 Glossary unless marked otherwise.

### Vehicle financing arrangement

**PRA PS1/26 Glossary (Appendix 1, p. 27) — verbatim:**

> "**vehicle financing arrangement** means a loan, lease or other finance arrangement in
> respect of vehicle classes AM, A1, A2, A and B and B1 as specified in Parts 1 and 3 of
> Schedule 2 of The Motor Vehicles (Driving Licenses) Regulations 1999, provided that such
> arrangement does not qualify as an object finance exposure for the purposes of Articles
> 122A and 122B."

**Plain English:** Retail-style financing (loan, lease, or hire-purchase) for a passenger
car, motorcycle, moped, or small van — i.e. a personal-use vehicle covered by an ordinary
UK driving licence — provided the deal is not a corporate-style object-finance transaction
caught by the SA specialised lending articles (Art. 122A) or the IRB specialised lending
article (Art. 122B).

**Where used in PS1/26:**

- [Art. 123(1)(b)(i)(2)](basel31/sa-risk-weights.md#retail-risk-weights-art-123) — listed as
  an example of a "term loan or lease" that may qualify an SME exposure as a **retail
  exposure** under the Basel 3.1 SA exposure-class waterfall.
- [Art. 123A(1)(b)(i)](basel31/sa-risk-weights.md#retail-risk-weights-art-123) — listed as
  an example of a "term loan or lease" that may qualify a natural-person exposure as a
  **regulatory retail exposure** (eligible for the 75% / 45% risk weight rather than the
  100% other-retail weight).

The definition is purely **inclusive** — it confirms that personal-vehicle finance is a
permissible retail product type. It does not by itself trigger any specific risk weight;
the eligibility tests in Art. 123(1) (granularity, GBP 880,000 threshold) and Art. 123A
(regulatory-retail conditions) still apply.

!!! info "Why the carve-out for object finance"
    The closing proviso ("does not qualify as an object finance exposure for the purposes
    of Articles 122A and 122B") prevents wholesale fleet-financing or commercial-vehicle
    leasing from being routed through the retail risk-weight tables when the cash flows are
    economically those of specialised lending. Where a vehicle deal meets the object-finance
    criteria — typically large commercial vehicles (HGVs, buses, aircraft — vehicle classes
    outside AM/A/B) financed primarily from the asset's revenue stream — it is captured by
    SA specialised lending (Art. 122A, slotted weights) or IRB specialised lending
    (Art. 122B, slotting approach) instead.

!!! note "CRR comparison"
    CRR Art. 4(1) does **not** define "vehicle financing arrangement" — the concept is new
    in PS1/26. Under CRR, vehicle financing was implicitly covered by the generic "retail
    exposure" definition in Art. 123 without an explicit asset-class carve-out. The new
    definition aligns the UK retail boundary with BCBS CRE20.65, which lists "auto loans
    and leases" among the qualifying retail product types and excludes specialised vehicle
    lending.

### SlottingCategory and subgrades A/B/C/D

`SlottingCategory` (`src/rwa_calc/domain/enums.py`) is the **coarse five-bucket** grade
enum used throughout the calculator for specialised lending exposures (PF, OF, CF, IPRE,
HVCRE):

| Member | Loader value | Plain meaning |
|--------|--------------|---------------|
| `STRONG` | `"strong"` | Highest supervisory category — strong financials, sponsors, contracts |
| `GOOD` | `"good"` | Adequate margin against stress |
| `SATISFACTORY` | `"satisfactory"` | Acceptable but vulnerable to downside |
| `WEAK` | `"weak"` | Significant deterioration risk |
| `DEFAULT` | `"default"` | Defaulted — 0% RW, capital captured via EL shortfall |

**Where the A/B/C/D subgrades come from.** PRA PS1/26 Art. 153(5) Table A (risk weights)
and Art. 158(6) Table B (expected loss) split the **Strong** and **Good** buckets into
two columns each:

- **Strong** → column **A** (concession) or column **B** (default)
- **Good** → column **C** (concession) or column **D** (default)
- **Satisfactory**, **Weak**, **Default** → single column (no subgrades)

The subgrade is **not a separate input field** — there is no `slotting_subgrade` column
on the loader. Instead the calculator derives the column from the exposure's residual
maturity and (for B31) HVCRE flag:

- `is_short_maturity = remaining_maturity_years < 2.5` triggers column A / C under
  Art. 153(5)(d). This concession is implemented for **CRR** only; the B31 calculator
  currently routes all slotting exposures to column B / D regardless of maturity (tracked
  as `IMPLEMENTATION_PLAN.md` items P1.97 non-HVCRE, P1.117 HVCRE).
- The IPRE / PF enhanced-underwriting concessions in Art. 153(5)(e)–(f) are **not**
  implemented — there is no input field to mark an exposure as meeting those tests.

**Where to find the actual numbers.** Risk-weight values for each (category × subgrade ×
HVCRE) combination live in the canonical slotting specs — do not reproduce them here:

- [Basel 3.1 Table A — Subgrade Treatment](basel31/slotting-approach.md#subgrade-treatment-table-a-columns-abcd)
  for risk weights (PRA PS1/26 Art. 153(5)).
- [Basel 3.1 Table B — Slotting Expected Loss Rates](crr/slotting-approach.md#slotting-expected-loss-rates--table-b-pra-ps126-art-1586)
  for the EL ladder (PRA PS1/26 Art. 158(6)). Note: HVCRE EL collapses to a flat 0.4%
  across all four columns A/B/C/D for both Strong and Good — a documented PRA quirk.
- [CRR Table 1](crr/slotting-approach.md#table-1-art-1535) for the CRR pre-Basel-3.1
  risk-weight equivalent (single table; no subgrade columns — maturity differentiation
  is expressed as a separate `< 2.5yr` / `≥ 2.5yr` split rather than A/B/C/D columns).

A practitioner-level walkthrough (input fields, worked example) is in the
[Specialised Lending user guide](../user-guide/methodology/specialised-lending.md#from-category-to-risk-weight-the-subgrade-step).
