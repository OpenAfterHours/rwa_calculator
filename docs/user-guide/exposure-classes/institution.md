# Institution Exposures

**Institution exposures** are claims on banks, investment firms, and other regulated financial institutions.

## Definition

Institution exposures include:

| Entity Type | Description |
|-------------|-------------|
| Credit institutions | Banks, building societies |
| Investment firms | Broker-dealers, asset managers |
| Central counterparties (CCPs) | Clearing houses |
| Financial holding companies | Bank holding companies |
| Insurance companies | Subject to certain conditions |

## Risk Weights (SA)

Institution risk weights range from 20% (CQS 1) to 150% (CQS 6). Under CRR Art. 120 Table 3, CQS 2 receives **50%**. Basel 3.1 ECRA (PRA PS1/26 Art. 120 Table 3) reduces CQS 2 to **30%**.

Under CRR, unrated institutions receive **100%** (Art. 120(2)). Under Basel 3.1, unrated institutions use the **Standardised Credit Risk Assessment Approach (SCRA)** based on capital adequacy (Grade A: 40%, Grade A enhanced: 30%, Grade B: 75%, Grade C: 150%). Grade A enhanced requires CET1 ≥ 14% and leverage ratio ≥ 5%.

!!! info "SCRA Disclosure Barring Ladder (Art. 121(1)(a), (1)(b))"
    SCRA classification depends on what the counterparty institution publicly discloses
    about its prudential requirements. Missing disclosures bar grades asymmetrically:

    - Buffers undisclosed (requirements disclosed) → barred from Grade A, Grade B (75%) at best.
    - Minimum requirements undisclosed → forced to Grade C (150%).

    `scra_grade` is a firm-supplied input; disclosure evaluation sits upstream of the
    calculator. See
    [B31 SA spec — Disclosure Barring Rules](../../specifications/basel31/sa-risk-weights.md#scra-disclosure-barring-rules-art-1211a-1b)
    for the full barring table, Art. 121(1A)/(1B) disclosure-scope definitions, and
    the near-final → final drafting reversal.

!!! warning "SCRA Sovereign Floor (Art. 121(6))"
    Where an unrated institution exposure is denominated in a foreign currency (other
    than the local currency of the institution's jurisdiction of incorporation), its
    risk weight cannot fall below the home sovereign's RW: `RW = max(SCRA_grade_RW,
    sovereign_RW)`. Self-liquidating trade-related contingent items arising from the
    movement of goods with original maturity < 1 year are carved out and retain the
    underlying SCRA grade weight. See
    [B31 SA Risk Weights — Art. 121(6)](../../specifications/basel31/sa-risk-weights.md#scra-sovereign-floor-for-foreign-currency-exposures-art-1216).

!!! info "ECRA Due Diligence CQS Step-Up (Art. 120(4)) — Basel 3.1 only"
    Where a rated institution exposure is risk-weighted from Table 3 (or Table 4 / Table 4A
    for short-term exposures), Basel 3.1 Art. 120(4) requires firms to conduct due diligence
    on the ECAI rating. If DD reveals higher risk than the assigned CQS implies, the firm
    must assign **at least one CQS step higher**. Currently routed through the Art. 110A
    `due_diligence_override_rw` input (no dedicated Art. 120(4) branch in the calculator).
    Parallels Art. 122(4) for rated corporates and Art. 129(4A) for covered bonds; no CRR
    equivalent. See
    [B31 SA Risk Weights — Art. 120(4)](../../specifications/basel31/sa-risk-weights.md#rated-institution-due-diligence-cqs-step-up-art-1204)
    for the full trigger/effect table.

> **Details:** See [Key Differences — Institution Exposures](../../framework-comparison/key-differences.md#institution-exposures) for the complete ECRA/SCRA comparison tables.

## IRB Treatment

F-IRB uses supervisory LGD (45% senior, 75% subordinated) with PD floors of 0.03% (CRR) / 0.05% (Basel 3.1). Institution correlation uses the corporate formula.

!!! warning "Basel 3.1"
    A-IRB is **no longer permitted** for institution exposures under Basel 3.1. Only SA or F-IRB may be used.

> **Details:** See [IRB Approach](../methodology/irb-approach.md) for the full formula and parameter details.

## Short-Term Exposures

### Table 4 — General Short-Term Preferential (Art. 120(2))

Rated institution exposures with original maturity ≤ 3 months receive preferential
treatment under Table 4.

| CQS | Standard RW (>3m) | Table 4 RW (≤3m) |
|-----|-------------------|-------------------|
| CQS 1 | 20% | 20% |
| CQS 2 | 30% | 20% |
| CQS 3 | 50% | 20% |
| CQS 4-5 | 100% | 50% |
| CQS 6 | 150% | 150% |

!!! info "Art. 120(2A) Trade Finance ≤ 6m Extension — Basel 3.1 only"
    Trade-finance exposures arising from the **movement of goods** qualify for Table 4
    weights when original maturity ≤ **6 months** (not the general 3-month window).
    Both limbs must hold: `is_short_term_trade_lc = True` **and** `original_maturity_years ≤ 0.5`.
    A 5-month documentary credit to a CQS 3 rated bank therefore receives Table 4's 20%
    rather than Table 3's 50%.

    This is the **rated** counterpart of the SCRA Art. 121(4) carve-out below; both were
    introduced in Basel 3.1 to align with BCBS CRE20.20. **No CRR analogue** — CRR
    Art. 120(2) has no trade-goods extension, so a 5-month trade-finance exposure to a
    rated CRR bank reverts to Table 3's long-term weight. See
    [B31 SA Risk Weights — Art. 120(2A)](../../specifications/basel31/sa-risk-weights.md#ecra-short-term-trade-finance-exception-art-1202a-table-4)
    for worked examples, interaction with Art. 120(2B) Table 4A, and the side-by-side
    comparison with Art. 121(4).

### Table 4A — Short-Term ECAI Assessment (Art. 120(2B))

Where an institution has a specific **short-term credit assessment** from a nominated
ECAI (as opposed to a long-term rating applied to a short-term exposure), Table 4A
applies:

| Short-Term CQS | Risk Weight |
|----------------|-------------|
| CQS 1 | 20% |
| CQS 2 | 50% |
| CQS 3 | 100% |
| Others | 150% |

!!! warning "Not Yet Implemented — Schema Gap"
    The `has_short_term_ecai` schema field does not exist. The calculator cannot
    distinguish Table 4A exposures (specific short-term ECAI) from Table 4 exposures
    (long-term ECAI applied to short-term tenor). All short-term institution exposures
    currently receive Table 4 weights, which **understates risk** for CQS 2 (20% applied
    vs correct 50%) and CQS 3 (20% vs 100%). See D3.8 in the docs implementation plan
    and [B31 SA Risk Weights spec](../../specifications/basel31/sa-risk-weights.md#ecra-short-term-ecai-art-1202b-table-4a).

### Art. 120(3) — Interaction Rules

The interaction between Table 4 and Table 4A is governed by Art. 120(3):

- **(a)** No short-term assessment → Table 4 applies
- **(b)** Short-term assessment yields more favourable or equal RW → Table 4A for that exposure only; other short-term exposures still use Table 4
- **(c)** Short-term assessment yields less favourable RW → Table 4 preferential treatment withdrawn; all unrated short-term claims against that obligor receive the Table 4A weight

### Implicit Government Support Higher-of Rule (Art. 138(1)(g), Art. 139(6))

Basel 3.1 introduces two new provisions governing how ECAI ratings that incorporate
**implicit government support** may be used to risk-weight institution exposures.
Both apply only where the obligor is an institution and only on the ECRA (rated) path:

- **Art. 138(1)(g)** prohibits using a credit assessment that incorporates assumptions
    of implicit government support, *unless* the rated institution is owned by or set
    up and sponsored by central, regional, or local government (the government-owned /
    government-sponsored exemption).
- **Art. 139(6)** is a residual "higher-of" floor: where no "clean" issue-specific
    rating exists but an implicit-support issue-specific rating does, the firm must
    assign the **higher of** (i) the baseline RW derived from Art. 138 with implicit-
    support assessments suppressed, and (ii) the RW from the issue-specific rating
    disregarding Art. 138(1)(g).

!!! warning "Not Yet Implemented — Use Art. 110A Override as Workaround"
    The calculator does not distinguish issue-specific from general-issuer ratings
    and has no flag for implicit-support assumption — so the Art. 139(6) higher-of
    comparison cannot be computed automatically. Firms with material rated-institution
    exposures whose ratings embed implicit support should either:

    - **Pre-adjust** `external_cqs` offline to reflect the Art. 139(6) higher-of
        result before loading, or
    - Set `due_diligence_override_rw` to the required floor via the framework-wide
        Art. 110A pathway ([see Art. 110A discussion](../../user-guide/regulatory/basel31.md#10-due-diligence-requirements)).

    Firms must also independently determine whether the rated institution falls
    within the Art. 138(1)(g) exemption (government-owned / government-sponsored) —
    this is a firm governance question, not a calculator input. See
    [B31 SA Risk Weights — Art. 138(1)(g), Art. 139(6)](../../specifications/basel31/sa-risk-weights.md#ecai-assessment-implicit-government-support-art-1381g-art-1396)
    for the full trigger, worked example, exemption scope, and distinction from the
    Art. 121(6) SCRA sovereign floor.

    No CRR equivalent — CRR Art. 138 has only sub-points (a)–(f), and CRR Art. 139
    has only paragraphs (1)–(4). CRR firms apply implicit-support ratings directly.

## Interbank Exposures

### Due From Banks

| Exposure Type | Treatment |
|---------------|-----------|
| Nostro balances | Standard institution RW |
| Interbank loans | Standard institution RW |
| Money market placements | May qualify for short-term |
| Repo/reverse repo | CRM treatment may apply |

### Trade Finance

| Item | CCF | Risk Weight |
|------|-----|-------------|
| Documentary credits | 20% | Institution RW |
| Standby LCs | 50-100% | Institution RW |
| Guarantees | 100% | Institution RW |

## Covered Bonds

Covered bonds issued by institutions receive preferential treatment under Art. 129. Rated bonds range from 10% (CQS 1) to 100% (CQS 6) per Table 6A/Table 7. Unrated bonds derive their RW from the issuing institution's senior unsecured RW via Art. 129(5), producing values from 10% to 100%. PRA PS1/26 retains the same rated table — the BCBS CRE20 reductions (CQS 2→15%, CQS 4–6→50%) were not adopted.

> **Details:** See [Key Differences — Covered Bonds](../../framework-comparison/key-differences.md#covered-bonds-art-129) for the full CQS table and CRR vs Basel 3.1 comparison.

!!! info "Art. 129(4A) Due Diligence CQS Step-Up — Basel 3.1 only"
    Where a rated covered bond is risk-weighted from Table 7, Basel 3.1 Art. 129(4A) requires
    firms to conduct due diligence on the ECAI assessment. If DD reveals higher risk than the
    assigned CQS implies, the firm must assign **at least one CQS step higher** than the
    ECAI-implied weight (e.g. CQS 1 → CQS 2 = 10% → 20%, CQS 3 → CQS 4 = 20% → 50%,
    CQS 5 → CQS 6 = 50% → 100%). Note that CQS 2 → CQS 3 and CQS 4 → CQS 5 transitions
    produce no numerical change (Table 7 assigns identical weights to those adjacent steps);
    the reassignment is still mandatory for any downstream CQS-keyed process. Currently
    routed through the Art. 110A `due_diligence_override_rw` input (no dedicated Art. 129(4A)
    branch in the calculator). Parallels Art. 120(4) for rated institutions and Art. 122(4)
    for rated corporates; no CRR equivalent. See
    [B31 SA Risk Weights — Art. 129(4A)](../../specifications/basel31/sa-risk-weights.md#covered-bond-due-diligence-cqs-step-up-art-1294a)
    for the full trigger/effect table.

## Central Counterparties (CCPs)

### Qualifying CCPs (QCCPs)

| Exposure Type | Risk Weight |
|---------------|-------------|
| Trade exposures | 2% |
| Default fund contributions | Risk-sensitive calculation |

### Non-QCCPs

| Exposure Type | Treatment |
|---------------|-----------|
| Trade exposures | Bilateral institution RW |
| Default fund contributions | 1250% (or deduction) |

## CRM for Institutions

### Bank Guarantees

Exposures guaranteed by better-rated institutions:

```python
if guarantee.type == "INSTITUTION" and guarantee.cqs < counterparty.cqs:
    # Substitution approach
    guaranteed_rw = institution_risk_weight(guarantee.cqs)
```

### Bank Collateral

Bonds issued by institutions as collateral:

| Collateral Rating | Haircut (1-5yr) |
|-------------------|-----------------|
| CQS 1-2 | 4% |
| CQS 3 | 6% |
| CQS 4+ | Not eligible |

## Calculation Examples

**Example 1: Rated Bank**
- £25m placement with Deutsche Bank
- Rating: A+ (CQS 2)
- Maturity: 6 months

```python
# CQS 2 institution under CRR (Art. 120 Table 3)
Risk_Weight = 50%
EAD = £25,000,000
RWA = £25,000,000 × 50% = £12,500,000
# Under Basel 3.1 ECRA: 30% → RWA = £7,500,000
```

**Example 2: Unrated Bank (Basel 3.1)**
- £10m loan to regional bank
- No external rating
- SCRA assessment: CET1 = 16%, Leverage = 6%

```python
# SCRA Grade A
Risk_Weight = 40%
RWA = £10,000,000 × 40% = £4,000,000
```

**Example 3: Short-Term**
- £50m overnight placement
- Counterparty: CQS 3 bank
- Original maturity: 1 day

```python
# Short-term preferential treatment
Risk_Weight = 20%  # vs. standard 50%
RWA = £50,000,000 × 20% = £10,000,000
```

## Subordinated Debt

Exposures to subordinated debt of institutions:

| Instrument Type | CRR | Basel 3.1 |
|-----------------|-----|-----------|
| Tier 2 instruments | Institution RW + premium | 150% |
| AT1 instruments | Institution RW + premium | 150% |
| Equity-like | 150% | 250% |

## Regulatory References

| Topic | CRR Article | BCBS CRE |
|-------|-------------|----------|
| Institution definition | Art. 119 | CRE20.15-20 |
| Risk weights | Art. 119-121 | CRE20.21-25 |
| Short-term treatment | Art. 119(2) | CRE20.26 |
| Covered bonds | Art. 129 | CRE20.27-30 |
| CCPs | Art. 300-311 | CRE54 |

## Next Steps

- [Corporate Exposures](corporate.md)
- [Standardised Approach](../methodology/standardised-approach.md)
- [Credit Risk Mitigation](../methodology/crm.md)
