# Supporting Factors Specification

SME supporting factor and infrastructure supporting factor under CRR.

**Regulatory Reference:** CRR Articles 501, 501a

**Test Group:** CRR-F

---

!!! warning "CRR Only"
    Supporting factors are **not available under Basel 3.1**. They are disabled automatically when using the Basel 3.1 configuration.
    CRR Art. 501 and 501a are revoked from 1 January 2027 by S.I. 2026/45 (FSMA 2023 Commencement No. 12)
    reg. 3(b) and Schedule Part 1. The revocation is a Treasury instrument, which is why PS1/26 does not
    mention either article. The Basel 3.1 oracle cases ORC-060 (SA) and ORC-097 (F-IRB) assert the
    un-factored RWEA.

## SME Supporting Factor (CRR Art. 501)

A tiered discount applied to RWA for qualifying SME exposures.

### Eligibility

- Turnover < EUR 50m (converted from GBP at the configured FX rate)
- E* aggregated across the SME's group of connected clients
  (`lending_group_reference`), with fallback to `counterparty_reference` when
  no lending group is mapped, per CRR Art. 501. **The aggregation runs on
  the unified frame before the SA / IRB / slotting branch split**, so
  siblings under any approach contribute to E* — a lending group containing
  both SA-treated and slotting- or IRB-treated members is summed correctly
  for the tier threshold.
- Claims secured on residential property collateral (e.g. BTL) are netted
  from E* per the Art. 501 carve-out: each row's contribution to E* is
  reduced by `residential_collateral_value` (capped at drawn so the
  contribution never goes negative), mirroring the retail-threshold
  treatment in CRR Art. 123(c). BTL rows additionally receive `factor=1.0`
  via a separate eligibility gate.

!!! info "Regulatory Scope vs Implementation"
    CRR Art. 501 applies the factor to **all** exposures to SMEs, including corporate, retail,
    and real-estate-secured classes. The implementation applies the factor only to exposures
    classified as `CORPORATE_SME` via the `is_sme` flag. Retail-origin entities that fail the
    retail qualification test are reclassified to `CORPORATE_SME` by the classifier and receive
    the factor (see CRR-F4). Retail-qualifying SMEs that remain in `RETAIL_OTHER`,
    `RETAIL_MORTGAGE`, or `RETAIL_QRRE` do not currently receive the Art. 501 discount — their
    75% risk weight already provides favourable treatment compared to corporate exposures.

### Tiered Application

| Tier | Exposure Threshold | Factor |
|------|-------------------|--------|
| Tier 1 | Up to EUR 2.5m (GBP ~2.2m) | 0.7619 |
| Tier 2 | Above EUR 2.5m | 0.85 |

### Blended Formula

For exposures that span both tiers:

```
SF = [min(D, threshold) x 0.7619 + max(D - threshold, 0) x 0.85] / D
```

Where `D` (= E* in Art. 501) is the on-balance-sheet amount (`max(0, drawn_amount) + interest`) aggregated across the SME's group of connected clients (`lending_group_reference`, falling back to `counterparty_reference` when the lending group is null), with each row's contribution reduced by the residential-property collateral value (`residential_collateral_value`, capped at drawn) per the Art. 501 carve-out — mirroring the retail-threshold treatment in CRR Art. 123(c). `threshold` is EUR 2.5m (or GBP equivalent).

## Infrastructure Supporting Factor (CRR Art. 501a)

A flat **0.75** factor applied to qualifying infrastructure lending exposures.

### Eligibility

Art. 501a(1) grants the factor only where the exposure meets **all** of criteria (a) to (o). The
calculator checks three things against Art. 501a and nothing else:

- **Candidate.** `product_type` contains `INFRASTRUCTURE` (case-insensitive). That match sets the
  derived `is_infrastructure` flag. There is **no** `is_infrastructure` input column, and the
  match is a name, not an attestation that the exposure meets Art. 501a.
- **Limb (a).** The exposure is in the corporate, corporate-SME or specialised-lending class and
  is not in default.
- **Limb (h), as a denial only.** The obligation must be "senior to all other claims other than
  statutory claims and claims from derivatives counterparties". Where the `seniority` input is
  anything other than `senior` (case-insensitive), the factor is withheld: `subordinated` in any
  case, out-of-domain values such as `junior` (validation warns on them, DQ006, but passes them
  through) and an empty string. A null (missing) `seniority` is treated as senior, matching the
  loader default for an absent column; an empty string is not null. A `senior` value does not
  prove limb (h); it only does not contradict it.

Settlement-risk and CCP default-fund rows (`risk_type` of a failed trade or a default-fund
contribution) never receive the factor: their amount is an own funds requirement, not an exposure
to an infrastructure entity.

The factor is applied regardless of exposure size.

!!! warning "Limbs (b)-(g), (i)-(o) and paragraph 2 are not checked"
    The special-purpose-entity test (b), the two-thirds repayment source (c), stressed conditions
    (d), predictable cash flows (e) with paragraph 2's definition, refinancing risk (f), the lender
    protections (g), the construction-phase equity-investor tests (i), and (j)-(o) are judgements
    the firm makes about the obligor and the facility. No input carries them, so the calculator
    cannot test them. Use an infrastructure `product_type` only for exposures the firm has assessed
    as meeting all of Art. 501a.

An SME exposure that fails Art. 501a can still receive the Art. 501 SME factor, which has no
seniority condition.

!!! note "Reporting of a denied SME infrastructure row (open item P2.56)"
    COREP C 07.00 row 0035 and col 0217 read the raw `is_infrastructure` flag. An
    infrastructure-named SME row that is denied Art. 501a, for example because it is subordinated,
    currently has its Art. 501 SME relief reported in col 0217 and row 0035 instead of col 0216.
    Totals and the `0215 + 0216 + 0217 = 0220` footing are unaffected.

## Combined Application

When both factors apply to an exposure, the calculator uses the **minimum** (most beneficial) factor.

## Key Scenarios

| Scenario ID | Description | Expected Factor |
|-------------|-------------|-----------------|
| CRR-F1 | Small SME — Tier 1 only (exposure ≤ EUR 2.5m) | 0.7619 |
| CRR-F2 | Medium SME — blended tiers (exposure spans threshold) | Blended (weighted average of 0.7619 and 0.85) |
| CRR-F3 | Large SME — Tier 2 dominant (exposure well above EUR 2.5m) | → 0.85 |
| CRR-F4 | Retail-origin SME — reclassified to `CORPORATE_SME`, Tier 1 factor applied | 0.7619 |
| CRR-F5 | Infrastructure — flat factor (not tiered) | 0.75 (Art. 501a) |
| CRR-F6 | Large corporate — no SME factor (turnover > EUR 50m threshold) | 1.0 (no discount) |
| CRR-F7 | Boundary — exposure exactly at EUR 2.5m (GBP ~£2.18m) threshold | Tier 1 factor (0.7619) applies up to threshold |
| CRR-F8 | Lending group of two SMEs at GBP 1.5m drawn each — E* = 3m → blended factor (not pure Tier 1) | Blended (E* aggregated across `lending_group_reference`) |

!!! note "Combined Factors"
    When both SME and infrastructure factors apply, the calculator uses the minimum (most beneficial) factor. This is validated within CRR-F5 where infrastructure exposures may also qualify as SME.

## Acceptance Tests

| Group | Scenarios | Tests | Pass Rate |
|-------|-----------|-------|-----------|
| CRR-F: Supporting Factors | F1–F8 | 17 | 94% (16/17 passing, 1 skipped — F8 pipeline fixture is a follow-up) |
