# Basel 3.1 Framework Differences

Key differences from CRR including output floor, PD/LGD floors, and removal of supporting factors.

**Regulatory Reference:** PRA PS1/26

---

## Overview

Basel 3.1 (effective 1 January 2027 in the UK) introduces significant changes to the credit risk framework. The calculator supports both regimes via a configuration toggle.

## Key Differences

| Parameter | CRR (Current) | Basel 3.1 | Reference |
|-----------|---------------|-----------|-----------|
| RWA Scaling Factor | 1.06 | Removed | — |
| SME Supporting Factor | 0.7619 / 0.85 | Removed | CRR Art. 501 |
| Infrastructure Factor | 0.75 | Removed | CRR Art. 501a |
| Output Floor | None | 72.5% of SA | PRA PS1/26 |
| PD Floor | 0.03% (all classes) | Differentiated | CRE30.55 |
| A-IRB LGD Floors | None | Yes (by collateral type) | CRE30.41 |
| Slotting Risk Weights | Maturity-differentiated | HVCRE-differentiated (no pre-op distinction) | PRA PS1/26 |

## Differentiated PD Floors (Basel 3.1)

PRA PS1/26 Art. 160(1) (corporate, sovereign, institution) and Art. 163(1) (retail):

| Exposure Class | PD Floor | Reference |
|---------------|----------|-----------|
| Corporate | 0.05% | Art. 160(1) |
| Corporate SME | 0.05% | Art. 160(1) |
| Sovereign | 0.05% | Art. 160(1) |
| Institution | 0.05% | Art. 160(1) |
| Retail Mortgage | 0.10% | Art. 163(1)(b) |
| Retail Other | 0.05% | Art. 163(1)(c) |
| QRRE (Transactors) | 0.05% | Art. 163(1)(c) |
| QRRE (Revolvers) | 0.10% | Art. 163(1)(a) |

!!! note "Sovereign and Institution PD Floors"
    Under Basel 3.1, sovereign exposures are restricted to SA only (Art. 147A) and institution
    exposures to F-IRB only. PD floors remain relevant for any grandfathered or transitional
    IRB treatment.

## A-IRB LGD Floors (Basel 3.1)

**Corporate / Institution (Art. 161(5)):**

| Collateral Type | LGD Floor |
|----------------|-----------|
| Unsecured | 25% |
| Financial collateral | 0% |
| Receivables | 10%* |
| Commercial real estate | 10%* |
| Residential real estate | 10%* |
| Other physical | 15%* |

!!! note "No senior/subordinated distinction"
    Art. 161(5)(a) sets a flat 25% floor for **all** corporate unsecured exposures. Unlike F-IRB supervisory LGD (which distinguishes non-FSE senior 40% / FSE senior 45% / subordinated 75%), A-IRB LGD floors have no subordinated uplift.

**Retail (Art. 164(4)):**

| Exposure Type | LGD Floor |
|---------------|-----------|
| Secured by residential RE | 5% |
| QRRE unsecured | 50% |
| Other unsecured retail | 30% |

*Values reflect PRA PS1/26 implementation. BCBS standard values differ (Receivables: 15%, CRE: 10%, RRE: 10%, Other Physical: 20%).

## F-IRB Supervisory LGD (Art. 161)

### Art. 161 LGD Values

| Exposure Type | CRR | Basel 3.1 | Reference |
|---------------|-----|-----------|-----------|
| Financial Sector Entity (Senior) | 45% | 45% | Art. 161(1)(a) |
| Other Corporate/Institution (Senior) | 45% | 40% | Art. 161(1)(aa) |
| Corporate/Institution (Subordinated) | 75% | 75% | Art. 161(1)(b) |
| Covered Bonds | 11.25% | 11.25% | Art. 161(1)(d) → Art. 161(1B) |
| Senior purchased corporate receivables | 45% | 40% | Art. 161(1)(e) |
| Subordinated purchased corporate receivables | 100% | 100% | Art. 161(1)(f) |
| Dilution risk | 75% | 100% | Art. 161(1)(g) |

### Art. 230 LGDS Values (Secured Portions)

| Collateral Type | CRR LGDS (Senior) | CRR LGDS (Sub.) | Basel 3.1 LGDS | Reference |
|----------------|-------------------|-----------------|----------------|-----------|
| Financial Collateral | 0% | 0% | 0% | Art. 230 Table 5 / Art. 230(2) |
| Receivables | 35% | 65% | 20% | Art. 230 Table 5 / CRE32.9 |
| CRE/RRE | 35% | 65% | 20% | Art. 230 Table 5 / CRE32.10-11 |
| Other Physical | 40% | 70% | 25% | Art. 230 Table 5 / CRE32.12 |

!!! note "FSE Distinction — New in Basel 3.1"
    Basel 3.1 Art. 161(1)(aa) reduces the senior unsecured LGD from 45% to 40% for non-FSE
    corporates only. Financial sector entities (Art. 4(1)(27)) retain 45% under Art. 161(1)(a),
    reflecting higher observed loss severity for financial institution defaults. Institutions are
    implicitly FSEs. See [Key Differences](key-differences.md#f-irb-supervisory-lgd) for change
    summary.

!!! info "Purchased Receivables and Dilution Risk (Art. 161(1)(e)–(g))"
    Art. 161(1)(e)/(f) apply where the institution cannot estimate PD for the purchased
    receivables pool (per Art. 160(2)). Senior purchased receivables align with the standard
    senior rate; subordinated purchased receivables are penalised at 100%. Basel 3.1 increases
    the dilution risk LGD from 75% to 100% (Art. 161(1)(g)). See
    [CRR F-IRB spec](../specifications/crr/firb-calculation.md#art-1611-lgd-values) for full
    Art. 161(1)(a)–(g) breakdown.

!!! info "B31 Art. 230 — Subordinated LGDS Distinction Removed"
    CRR Art. 230 Table 5 has separate "senior" and "subordinated" LGDS columns (e.g.,
    receivables 35% senior / 65% subordinated). PRA PS1/26 Art. 230(2) replaces this with a
    single LGDS per collateral type with no subordinated distinction. Under Basel 3.1, the
    subordination effect is captured solely through the LGDU term (75%, Art. 161(1)(b)).

## Output Floor

The output floor ensures IRB RWA cannot fall below a percentage of what the SA would produce:

```
RWA_final = max(RWA_IRB, floor_percentage x RWA_SA)
```

### Transitional Schedule (PRA PS1/26 Art. 92 para 5)

The PRA compressed the BCBS 6-year phase-in to a 4-year schedule:

| Year | Floor Percentage |
|------|-----------------|
| 2027 | 60.0% |
| 2028 | 65.0% |
| 2029 | 70.0% |
| 2030+ | 72.5% |

Note: Art. 92 para 5 says institutions "may apply" these transitional rates — they are
permissive. Firms can voluntarily use 72.5% from day one.

### Output Floor Adjustment (OF-ADJ)

The full output floor formula from PRA PS1/26 Art. 92(2A) is:

```
TREA = max{U-TREA; x × S-TREA + OF-ADJ}
```

Where:

- **U-TREA** = un-floored total risk exposure amount (Art. 92(3))
- **S-TREA** = standardised total risk exposure amount (Art. 92(3A)) — calculated without IRB, SFT VaR, SEC-IRBA, IAA, IMM, or IMA
- **x** = floor percentage (see transitional schedule above)
- **OF-ADJ** = `12.5 × (IRB_T2 – IRB_CET1 – GCRA + SA_T2)`

The OF-ADJ reconciles the different treatment of provisions under IRB and SA:

| Component | Description | Regulatory Ref |
|-----------|-------------|----------------|
| IRB_T2 | IRB excess provisions T2 credit (provisions > EL), capped at 0.6% of IRB RWAs | Art. 62(d) |
| IRB_CET1 | IRB EL shortfall CET1 deductions (EL > provisions) + Art. 40 additional deductions | Art. 36(1)(d), Art. 40 |
| GCRA | General credit risk adjustments in T2, gross of tax effects, capped at **1.25% of S-TREA** | Art. 62(c), Art. 92(2A) |
| SA_T2 | SA general credit risk adjustments T2 credit | Art. 62(c) |

Under IRB, EL shortfall adds to capital requirements (CET1 deduction) while excess provisions
provide T2 relief. Under SA, general credit risk adjustments provide T2 relief directly. The
12.5 multiplier converts own-funds amounts to risk-weighted equivalents. Without this adjustment,
the floor comparison would not be on a like-for-like basis.

For COREP template mapping of OF-ADJ components, see the
[output reporting spec](../specifications/output-reporting.md#output-floor-adjustment-of-adj).

### Entity-Type Carve-Outs (Art. 92(2A)(b)–(d))

The output floor does **not** apply universally. Art. 92(2A) specifies which entity/basis
combinations must use the floored TREA formula; all others use U-TREA directly:

**Floor applies (Art. 92(2A)(a)):**

- Standalone UK institution — individual basis
- Ring-fenced body in sub-consolidation group — sub-consolidated basis
- CRR consolidation entity (not international subsidiary) — consolidated basis

**Exempt — use U-TREA only (Art. 92(2A)(b)–(d)):**

- **(b)** Non-ring-fenced institution — sub-consolidated basis
- **(c)** Ring-fenced body in sub-consolidation group; non-standalone UK institution — individual basis
- **(d)** CRR consolidation entity that is an international subsidiary — consolidated basis

!!! info "Implementation"
    Set `institution_type` and `reporting_basis` on `OutputFloorConfig` to activate the carve-out
    logic. When both are `None`, the floor defaults to applicable. See the
    [output floor spec](../specifications/basel31/output-floor.md#entity-type-carve-outs) for the
    full applicability table.

## Supervisory Haircut Comparison

### CRR Haircuts (3 maturity bands)

| Collateral Type | 0-1y | 1-5y | 5y+ |
|-----------------|------|------|-----|
| Govt bonds CQS 1 | 0.5% | 2% | 4% |
| Govt bonds CQS 2-3 | 1% | 3% | 6% |
| Corp bonds CQS 1 | 1% | 4% | 8% |
| Corp bonds CQS 2-3 | 2% | 6% | 12% |
| Main index equities | 15% | — | — |
| Other equities | 25% | — | — |
| Gold | 15% | — | — |
| Cash | 0% | — | — |

### Basel 3.1 Haircuts (5 maturity bands)

PRA PS1/26 Art. 224 Table 3 (10-day holding period):

| Collateral Type | 0-1y | 1-3y | 3-5y | 5-10y | 10y+ |
|-----------------|------|------|------|-------|------|
| Govt bonds CQS 1 | 0.5% | 2% | 2% | 4% | 4% |
| Govt bonds CQS 2-3 | 1% | 3% | 4% | 6% | **12%** |
| Corp bonds CQS 1 | 1% | 4% | 6% | **10%** | **12%** |
| Corp bonds CQS 2-3 | 2% | 6% | 8% | **15%** | **15%** |
| Main index equities | **20%** | — | — | — | — |
| Other equities | **30%** | — | — | — | — |
| Gold | **20%** | — | — | — | — |
| Cash | 0% | — | — | — | — |

Currency mismatch haircut remains 8% under both frameworks (CRR Art. 224 / CRE22.54).

## SA Residential Real Estate Risk Weights (Basel 3.1)

Basel 3.1 replaces CRR Art. 125 (flat 35% up to 80% LTV) with two distinct residential RE treatments:

**General (not income-dependent) — Art. 124F: Loan-Splitting**

- Secured portion (up to **55% of property value**) → **20%** RW
- Residual portion → **counterparty RW** (75% for individuals per Art. 124L)

**Income-producing (cash-flow dependent) — Art. 124G, Table 6B: Whole-Loan**

| LTV | ≤50% | 50–60% | 60–70% | 70–80% | 80–90% | 90–100% | >100% |
|-----|------|--------|--------|--------|--------|---------|-------|
| RW  | 30%  | 35%    | 40%    | 50%    | 60%    | 75%     | 105%  |

!!! info "Junior Charge Multiplier (Art. 124G(2))"
    Where prior-ranking charges exist that the institution does not hold, the Table 6B risk
    weight is multiplied by **1.25×** when LTV > 50%. At LTV ≤ 50% the 30% weight applies
    without uplift. The multiplied weight is capped at 105%.
    **Example:** junior charge at 75% LTV → 50% × 1.25 = **62.5%** whole-loan.
    CRR has no equivalent junior-charge mechanism for residential RE (Art. 125 applies flat
    35% regardless of lien position).
    See [key-differences](key-differences.md#residential-real-estate) for the full CRR vs
    Basel 3.1 comparison.

## SA Commercial Real Estate Risk Weights (Basel 3.1)

Basel 3.1 replaces CRR Art. 126 (flat 50%/100% split for all CRE) with entity-type-differentiated
treatment under Art. 124H:

| Counterparty Type | Treatment | Risk Weight | Reference |
|-------------------|-----------|-------------|-----------|
| Natural person / SME | Loan-splitting | 60% secured (≤55% LTV) + counterparty RW residual | Art. 124H(1)–(2) |
| Other (large corporate, institution) | Whole-loan | max(60%, min(counterparty RW, income-producing RW)) | Art. 124H(3) |
| Income-dependent (any counterparty) | Whole-loan LTV table | 100% (≤80%) / 110% (>80%) | Art. 124I |

!!! info "Art. 124H(3) — Large Corporate CRE"
    The Art. 124H(3) path applies to the **entirety** of the exposure — no portion-based splitting.
    The `income_producing_rw` in the formula is the Art. 124I rate for the same LTV band.
    The calculator routes automatically when `cp_is_natural_person = False` and `is_sme = False`.
    See [key-differences](key-differences.md#commercial-real-estate) for the full CRR vs Basel 3.1
    comparison.

Exposures failing Art. 124A qualifying criteria fall to Art. 124J: 150% (income-dependent),
counterparty RW (residential non-income-dependent), or max(60%, counterparty RW) (commercial
non-income-dependent).

## Slotting Risk Weights (Basel 3.1)

PRA PS1/26 Art. 153(5) Table A defines two slotting weight tables — non-HVCRE and HVCRE:

### Non-HVCRE (OF, CF, PF, IPRE)

| Category | Risk Weight |
|----------|-------------|
| Strong | 70% |
| Good | 90% |
| Satisfactory | 115% |
| Weak | 250% |
| Default | 0% (EL) |

!!! warning "PRA Deviation from BCBS — No Pre-Operational PF Slotting Table"
    BCBS CRE33.6 Table 6 defines separate elevated slotting weights for pre-operational
    project finance (Strong 80%, Good 100%, Satisfactory 120%, Weak 350%). **PRA PS1/26
    does not adopt this distinction** — all project finance uses the standard non-HVCRE
    table regardless of operational status. The pre-operational / operational distinction
    only applies under the SA approach (Art. 122B(2)(c): 130% pre-op, 100% operational,
    80% high-quality operational).

### HVCRE

| Category | Risk Weight |
|----------|-------------|
| Strong | 95% |
| Good | 120% |
| Satisfactory | 140% |
| Weak | 250% |
| Default | 0% (EL) |

### Slotting Subgrades (Table A Columns A/B/C/D)

PRA PS1/26 Art. 153(5) Table A splits **Strong** into columns A and B, and **Good** into
columns C and D:

| Exposure Type | Strong A | Strong B | Good C | Good D | Satisfactory | Weak | Default |
|---------------|----------|----------|--------|--------|--------------|------|---------|
| OF, CF, PF, IPRE | 50% | 70% | 70% | 90% | 115% | 250% | 0% |
| HVCRE | 70% | 95% | 95% | 120% | 140% | 250% | 0% |

**Column B/D** is the default assignment (Art. 153(5)(c)). Column A/C may be used when:

- **< 2.5yr** remaining maturity (Art. 153(5)(d)) — optional for all SL types
- **IPRE** Strong meets enhanced criteria: very low LTV, investment-grade tenant income, no ADC (Art. 153(5)(e))
- **PF** Strong meets enhanced underwriting criteria (Art. 153(5)(f))

The values are identical to CRR — PRA restructured the format from maturity-split tables
to A/B/C/D columns but preserved all risk weight values. See [Key Differences](key-differences.md#slotting-subgrades-table-a-column-structure-art-1535) for the full comparison and [Slotting Approach spec](../specifications/basel31/slotting-approach.md#subgrade-treatment-table-a-columns-abcd) for implementation details.

## Financial Institution Correlation Multiplier (CRE31.5)

The 1.25x correlation multiplier applies to exposures to **financial institutions** only (not non-financial corporates):
- Regulated financial institutions with total assets above the applicable threshold:
  - **CRR**: EUR 70bn (Art. 153(2))
  - **BCBS/Basel 3.1**: USD 100bn (CRE31.5)
- Unregulated financial institutions regardless of size

This multiplier is already implemented via the `requires_fi_scalar` flag in the classifier and `_polars_correlation_expr()` in the IRB formulas. It applies under both CRR and Basel 3.1 frameworks.

Note: There is no separate "large corporate" correlation multiplier for non-financial corporates in either the BCBS standard or PRA PS1/26.

## Credit Conversion Factors (Art. 111 Table A1)

PRA PS1/26 replaces CRR Annex I with a 7-row Table A1. Key changes: CRR maturity-based commitment split (50%/>1yr, 20%/≤1yr) replaced by flat 40% "other commitments" bucket; UCC from 0% to 10%; F-IRB CCFs aligned to SA (Art. 166C). UK residential mortgage commitments carved out at **50%** (Row 4(b)) — a PRA-specific addition preventing the maturity-removal from reducing capital for irrevocable mortgage offers (BCBS would assign 40%). See [CCF specification](../specifications/crr/credit-conversion-factors.md#basel-31-sa-changes-pra-ps126-art-111-table-a1) for full Table A1.

### A-IRB CCF Floor (CRE32.27)

A-IRB own-estimate CCFs must be at least **50% of the SA CCF** for the same item type.

## Post-Model Adjustments (Art. 146(3), 153(5A), 154(4A), 158(6A))

Basel 3.1 introduces mandatory post-model adjustments (PMAs) — conservative overlays on
A-IRB model outputs with no CRR equivalent. PMAs address material model non-compliance
without requiring full model re-estimation.

### Components

| Component | Formula | Article |
|-----------|---------|---------|
| Mortgage RW floor | `RW = max(RW_modelled, mortgage_rw_floor)` | Art. 154(4A)(b) |
| General RWA scalar | `RWEA_adj = RWEA × (1 + pma_rwa_scalar)` | Art. 153(5A) / 154(4A)(a) |
| EL scalar | `EL_adj = EL × (1 + pma_el_scalar)` | Art. 158(6A) |

The mortgage RW floor default is **10%** for UK residential mortgage exposures (PRA supervisory
parameter). The general scalars are set per model via `PostModelAdjustmentConfig`.

### Sequencing (Mandatory)

Art. 154(4A) prescribes a strict ordering:

1. **Step 1 — Mortgage floor** (Art. 154(4A)(b)): Floor the modelled risk weight
2. **Step 2 — PMA scalar** (Art. 154(4A)(a)): Scale the floor-adjusted RWEA

The PMA scalar amplifies the post-floor RWEA, not the raw model output. Reversing the
order would produce incorrect results because the scalar would inflate a sub-floor RW
before the floor is applied.

### EL Monotonicity (Art. 158(6A))

```
EL_adjusted >= EL_unadjusted
```

PMAs cannot decrease expected loss. The `pma_el_scalar` must be ≥ 0, ensuring conservative
RWA overlays do not inadvertently reduce EL shortfall calculations (Art. 159).

### Output Floor Interaction

PMAs are included in the un-floored TREA (U-TREA) used for the output floor comparison.
They cannot be avoided by flooring to SA — the floor applies to the post-PMA total.

See the [A-IRB specification](../specifications/basel31/airb-calculation.md#post-model-adjustments-art-1463-1544a-1586a) for the complete implementation detail and COREP column mapping.

## IRB Effective Maturity (Art. 162)

PRA PS1/26 substantially rewrites Art. 162. The most significant structural change is the
**deletion of F-IRB fixed supervisory maturities** — all IRB firms must now calculate M.

| Aspect | CRR | Basel 3.1 | Change |
|--------|-----|-----------|--------|
| F-IRB fixed maturities (§1) | 0.5yr repo / 2.5yr other | **Deleted** | All IRB firms calculate M |
| Scope | A-IRB only (Art. 143) | F-IRB and A-IRB (Art. 147A) | Expanded |
| Cash-flow schedule (§2A(a)) | `M = max(1, min(Σ(t×CF_t)/Σ(CF_t), 5))` | Same | Unchanged |
| Revolving exposures (§2A(k)) | Repayment date of current drawing | **Max contractual termination date** | Increases M |
| Mixed MNA (§2A(da)) | Not addressed | **10-day floor** | New |
| Purchased receivables min M (§2A(e)) | 90 days | **1 year** | Raised |
| Collateral daily condition (§2A(c)/(d)) | Re-margining **and** revaluation | Re-margining **or** revaluation | Wider scope |
| SME simplification (§4) | Available (EUR 500m threshold) | **Deleted** | Removed |
| One-day floor (§3) | Daily remargined + revalued repos/derivatives | Same (with OR condition) | Unchanged |
| Floor | 1 year (general) | 1 year (general) | Unchanged |
| Cap | 5 years | 5 years | Unchanged |

The revolving maturity change (Art. 162(2A)(k)) typically increases M for revolving
facilities, leading to higher maturity adjustments and therefore higher capital. The deletion
of the F-IRB 0.5-year repo maturity means repo exposures will use the full cash-flow or
contractual calculation, generally increasing M from 0.5 to ≥ 1 year.

!!! info "One-Day Floor Exceptions (Art. 162(3))"
    Both CRR and Basel 3.1 allow a **one-day** maturity floor (overriding the general 1-year
    floor) for daily-margined repos, derivatives, and margin lending, plus qualifying
    short-term exposures (FX settlement, trade finance ≤ 1yr, securities settlement). Basel 3.1
    widens the trigger condition from re-margining **and** revaluation to re-margining **or**
    revaluation. See the [CRR F-IRB spec](../specifications/crr/firb-calculation.md#art-1623--one-day-maturity-floor-exceptions)
    for the full qualifying exposure list.

See the [CRR F-IRB specification](../specifications/crr/firb-calculation.md#effective-maturity-crr-art-162)
and [Basel 3.1 F-IRB specification](../specifications/basel31/firb-calculation.md#effective-maturity-art-162)
for full regulatory text and implementation details.

## Configuration

Switch between frameworks using the configuration factory:

```python
from rwa_calc.contracts.config import CalculationConfig

# CRR (current)
config = CalculationConfig.crr(reporting_date=date(2026, 12, 31))

# Basel 3.1
config = CalculationConfig.basel_3_1(reporting_date=date(2027, 1, 1))
```
