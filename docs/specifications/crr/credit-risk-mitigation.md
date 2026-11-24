# Credit Risk Mitigation Specification

Collateral haircuts, overcollateralisation, FX mismatch, maturity mismatch, and guarantee substitution.

**Regulatory Reference:** CRR Articles 192-241

**Test Group:** CRR-D

---

## Requirements Status

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-2.1 | Collateral recognition for 9 types | P0 | Done |
| FR-2.2 | Supervisory haircuts with maturity/currency mismatch | P0 | Done |
| FR-2.3 | Overcollateralisation ratios | P0 | Done |
| FR-2.4 | Multi-level collateral allocation | P0 | Done |
| FR-2.5 | Guarantee substitution | P0 | Done |
| FR-2.6 | Cross-approach CCF substitution | P0 | Done |
| FR-2.7 | CCF=100% override for CRM exposure value (Art. 223(4)) | P0 | Done |
| FR-2.8 | Immovable-property collateral valued net of prior claims (Art. 229(1)) | P0 | Done |
| FR-2.9 | Art. 207 attestation gates financial collateral under every method, F-IRB included | P0 | Done |

---

## Exposure value for CRM purposes (Art. 223(4))

**CRR Art. 223(4)** and **PRA PS1/26 Art. 223(4)** both require that, when computing the exposure value `E` used for credit risk mitigation, off-balance-sheet items shall be valued at **100% of nominal**, overriding the regulatory CCF. The actual CCF only re-couples afterwards.

> "(b) for institutions calculating risk-weighted exposure amounts under the IRB Approach, they shall calculate the exposure value of the items listed in Article 166(8) to (10) by **using a conversion factor of 100% rather than the conversion factors or percentages indicated in those paragraphs**."

The pipeline implements this with two parallel EAD bases on the exposures frame:

| Column | Definition | Used by |
|---|---|---|
| `ead_gross` | `on_bs_for_ead + nominal_after_provision × ccf` (post-CCF, the actual EAD that feeds RWA) | Audit, reporting, FIRB / Slotting RWA via `ead_final` |
| `ead_for_crm` | `on_bs_for_ead + nominal_after_provision` (CCF=100% basis) | Collateral pro-rata weights, FIRB LGD\* formula, Art. 230 thresholds, SA E\* netting |
| `effective_ccf` | `ead_pre_crm / ead_for_crm` | SA `ead_after_collateral` re-couples the actual CCF after collateral netting per Art. 228(1) |

For pure on-balance-sheet rows the two EAD bases are equal by construction.

> **On-balance-sheet netting (Art. 219) note.** The Art. 223(4) override applies to *collateral* valuation. **OBS netting under Art. 219 is its own drawn-only mechanism**: the synthetic cash collateral generated from a negative-drawn loan is allocated pro-rata across positive-drawn loan siblings by `on_bs_for_ead` (the drawn portion), not by `ead_for_crm`. Off-balance-sheet rows (contingents, synthetic `facility_undrawn` rows) are excluded from the OBS-netting beneficiary set.

### Worked example (FIRB cash collateral)

100m off-BS FIRB exposure, 75% CCF (Art. 166(8)(d) medium-risk commitment), 50m cash collateral; senior unsecured (LGDU=45%), cash LGDS=0%:

```
ead_for_crm    = 100m         (CCF=100% override)
ead_gross      =  75m         (post-CCF, used for RWA)
collateral     =  50m         (cash, 0% haircut)
LGD*           = (0% × 50 + 45% × (100−50)) / 100 = 22.5%
RWA            = ead_gross × K(PD, LGD*=22.5%, M) × 1.06
```

Pre-fix code netted collateral against the post-CCF `ead_gross` and produced LGD\* = 15%, under-stating FIRB LGD by 7.5pp on this exposure.

### Worked example (SA off-BS cash collateral)

100m off-BS, 50% CCF (medium-risk), 30m cash:

```
ead_for_crm           = 100m
E*                    = max(0, 100 − 30) = 70m       (Art. 223(5))
ead_after_collateral  = E* × CCF = 70 × 0.5 = 35m    (Art. 228(1))
```

Pre-fix code returned `ead_after_collateral = max(0, 50 − 30) = 20m`, under-stating EAD by 15m and therefore SA RWA.

---

## Collateral Haircuts (CRR Art. 224 / PRA PS1/26 Art. 224)

CRR uses 3 maturity bands for bond haircuts; Basel 3.1 expands to 5 bands with increased haircuts at longer tenors. All values below are at the 10-day liquidation period.

### Financial Collateral

| Collateral Type | CRR Haircut | Basel 3.1 Haircut |
|----------------|-------------|-------------------|
| Cash / Deposit | 0% | 0% |
| Gold | 15% | 20% |

### Government Bonds (by CQS and Residual Maturity — Art. 224 Table 1)

**CRR (3 maturity bands):**

| CQS | 0–1yr | 1–5yr | 5yr+ |
|-----|-------|-------|------|
| 1 | 0.5% | 2% | 4% |
| 2-3 | 1% | 3% | 6% |
| 4 | 15% | 15% | 15% |

**Basel 3.1 (5 maturity bands — PRA PS1/26 Art. 224 Table 1, 10-day liquidation period):**

| CQS | 0–1yr | 1–3yr | 3–5yr | 5–10yr | >10yr |
|-----|-------|-------|-------|--------|-------|
| 1 | 0.5% | 2% | 2% | 4% | 4% |
| 2-3 | 1% | 3% | 3% | 6% | 6% |
| 4 | 15% | 15% | 15% | 15% | 15% |

Key B31 change: the 5-band split re-groups the CRR 1–5yr and 5yr+ bands but **does not raise sovereign haircuts** for well-rated issuers. CQS 2–3 sovereigns remain at 6% even at the longest tenor; the CRR-era "5yr+ = 6%" simply splits into 5–10yr = 6% and >10yr = 6%. The cross-reference to the authoritative B31 spec is [Government Bond Haircuts (5-Band)](../basel31/credit-risk-mitigation.md#government-bond-haircuts-5-band).

**CQS eligibility (Art. 197):**

- CQS 1-4 government/central bank bonds are eligible as financial collateral (Art. 197(1)(b))
- CQS 5-6 government bonds are **ineligible** (Art. 197)
- CQS 1-3 institution/corporate bonds are eligible (Art. 197(1)(c)/(d)); CQS 4-6 are **ineligible**

### Corporate/Institution Bonds (by CQS and Residual Maturity — Art. 224 Table 1)

**CRR (3 maturity bands):**

| CQS | 0–1yr | 1–5yr | 5yr+ |
|-----|-------|-------|------|
| 1 | 1% | 4% | 8% |
| 2-3 | 2% | 6% | 12% |

**Basel 3.1 (5 maturity bands — PRA PS1/26 Art. 224 Table 1, 10-day liquidation period):**

| CQS | 0–1yr | 1–3yr | 3–5yr | 5–10yr | >10yr |
|-----|-------|-------|-------|--------|-------|
| 1 | 1% | 3% | 4% | 6% | 12% |
| 2-3 | 2% | 4% | 6% | 12% | 20% |

Key B31 changes: the 5-band split **raises the longest-tenor haircuts** materially while easing short-to-mid tenors. CQS 1 >10yr moves from the CRR 5yr+ flat 8% to **12%**; CQS 2–3 >10yr moves from 12% to **20%** (a +8pp uplift). By contrast, CQS 1 / 1–3yr eases from 4% to 3% and CQS 2–3 / 1–3yr eases from 6% to 4%. The cross-reference to the authoritative B31 spec is [Corporate and Institution Bond Haircuts (5-Band)](../basel31/credit-risk-mitigation.md#corporate-and-institution-bond-haircuts-5-band).

!!! note "Change log — B31 comparison table corrections (2026-04-21)"
    Prior versions of this CRR spec showed pre-correction B31 haircuts (CQS 2–3 / 10yr+ govt at 12%; corporate/institution CQS 2–3 / 5–10yr and 10yr+ both at 15%; CQS 1 / 1–3yr at 4%). These were drafted before the 17 Apr 2026 re-audit of PS1/26 Art. 224 Table 1. Values above now match the authoritative Basel 3.1 CRM spec and `ps126app1.pdf` page 203.

### Equity (Art. 224 Table 3)

| Type | CRR Haircut | Basel 3.1 Haircut |
|------|-------------|-------------------|
| Main index | 15% | 20% |
| Other listed | 25% | 30% |

### Credit-Linked Notes (CRR/PS1-26 Art. 218)

Art. 218 — *"investments in credit-linked notes issued by the lending institution
may be treated as cash collateral … provided that the credit default swap embedded
in the credit-linked note qualifies as eligible unfunded credit protection"* — grants
a credit-linked note the cash treatment (0% haircut, full EAD/LGD\* offset) **only
where the note is issued by the lending institution itself**. The note's cash proceeds
fund the protection, so it behaves as own-bank cash. PRA PS1/26 retains this verbatim
(both regimes — no regime split).

A CLN issued by a **third party** is *not* within Art. 218: its value is materially
correlated with the reference entity (typically the obligor — the Art. 194(4)
wrong-way-risk case), so it is not clean cash collateral.

**Input convention.** Supply the note as a `credit_linked_note` `COLLATERAL_SCHEMA`
row and attest own-issuance with `is_own_issued_cln`:

| `is_own_issued_cln` | Treatment |
|--------------------|-----------|
| `True` | Own-issued → **cash collateral** (0% haircut, full offset) |
| `False` / null | Not attested own-issued → **ineligible funded protection** |

`is_own_issued_cln` has **no Boolean default** — null means "own-issuance unattested"
and resolves to `False` (conservative): absence of attestation must not fabricate cash
treatment. The eligibility gate lives in `HaircutCalculator.apply_haircuts`
(`engine/crm/haircuts.py::credit_linked_note_ineligible_expr`) and works exactly like
the non-main-index-equity gate — it zeroes `value_after_haircut` and clears
`is_eligible_financial_collateral` for a non-own-issued row (which removes the row from
both the SA E\* reduction and the F-IRB LGD\* input, since `effectively_secured` derives
from the zeroed value), and raises one `CRM019` warning per gated row. The 0% cash
haircut the row would otherwise take is a valuation parameter, left intact.

**Direction of error.** Own-issued CLN: **exact** (unchanged cash treatment). Third-
party / unattested CLN: **conservative** (over-states RWA relative to the prior
anti-conservative full-cash treatment — a third-party CLN is not recognised at all,
rather than routed to a debt-security-of-its-issuer treatment, because a CLN carries no
clean issuer-bond eligibility path and its reference-entity correlation would need an
independent Art. 194(4) check).

### Non-Financial Collateral

Non-financial collateral does not use the supervisory volatility haircut framework (Art. 224). Instead, it is recognised through the **Foundation Collateral Method** (Art. 230-231) using LGDS values within the LGD* formula. See [F-IRB LGDS Values](#f-irb-lgds-values-art-230--art-161) below for the per-framework values.

### FX Mismatch Haircut (CRR Art. 224 Table 4 / Art. 233(3))

When *financial* collateral or *unfunded* credit protection is denominated in a currency different from the exposure: **8%** base haircut (10-day liquidation), scaled by Art. 226(2) for other liquidation periods and by Art. 226(1) for non-daily revaluation.

The H_fx scope is asymmetric and follows the regulatory text exactly:

- **Financial collateral (Art. 224 comprehensive method)** — H_fx applies via Art. 224 Table 4 to cash, gold, bonds, equity, and other instruments listed in Tables 1–4. Implemented in `engine/crm/haircuts.py:apply_haircuts`.
- **Unfunded credit protection (Art. 233(3))** — H_fx applies to guarantees and credit derivatives where G* = G(1 − H_fx). Implemented separately in `engine/crm/guarantees.py`. Article 232 explicitly cross-references Art. 233(3) for life insurance / credit-linked notes.
- **Funded non-financial collateral (Arts. 229–230)** — H_fx does **not** apply. Article 233 is unambiguously located in Sub-Section 2 *Unfunded credit protection*, and Art. 229 ("Valuation") plus Art. 230 ("Calculating risk-weighted exposure amounts…") for immovable property, receivables, and other physical collateral make no reference to H_fx. The LGD* formula compares the raw collateral value `C` (rebased to the reporting currency upstream by `FXConverter`) against the C\* / C\*\* thresholds in Table 5. The engine implements this exclusion by gating the H_fx Polars expression on `~collateral_type.is_in(NON_FINANCIAL_COLLATERAL_TYPES)` — see `data/schemas.py:NON_FINANCIAL_COLLATERAL_TYPES`.

PS1/26 inherits CRR's position on all three scopes; the engine behaviour is framework-agnostic.

### Zero-Haircut Conditions (CRR Art. 227)

Under certain conditions, supervisory haircuts may be set to **0%** for repo-style transactions:

- Both the exposure and collateral are **cash or CQS 1 government bonds**
- The transaction is subject to **daily margin maintenance** with a one-day margin period of risk
- The close-out period from the last MTM to the liquidation of the collateral
  following a re-margining failure is **no more than 4 business days** (Art. 227(2)(d) —
  see [the verbatim text and FCSM cross-application](#art-2272d-4-business-day-close-out-window))
- In the event of a counterparty failure to deliver margin, the transaction can be **terminated and collateral liquidated promptly**
- Settlement is via a **delivery-versus-payment** or equivalent mechanism
- The documentation is **standard market documentation** for the repo/SFT transaction type

Where these conditions are met, H_c = 0%, H_e = 0%, and H_fx = 0% (if applicable).

!!! note "Implementation Status"
    Art. 227 zero-haircut conditions are implemented. Institutions certify all 8 conditions
    (a)-(h) via the `qualifies_for_zero_haircut` Boolean field on collateral input data.
    The calculator validates collateral type eligibility: only cash/deposit and CQS ≤ 1
    sovereign bonds qualify. When conditions are met, H_c = 0%, H_fx = 0%.
    Ineligible types (corporate bonds, equity, gold) fall through to standard haircuts
    even when the flag is set.

### Volatility Scaling (CRR Art. 226)

Art. 226 defines **two separate scaling formulas**:

**Art. 226(2) — Scaling between liquidation periods:**
```
H_m = H_n × sqrt(T_m / T_n)
```
Where `H_n` is the haircut at liquidation period `T_n` and `H_m` is the haircut at the target period `T_m`.

**Art. 226(1) — Non-daily revaluation adjustment:**
```
H = H_m × sqrt((NR + T_m - 1) / T_m)
```
Where `NR` is the actual number of business days between revaluations and `T_m` is the liquidation period in days.

### Liquidation Period Dependency (CRR Art. 224, Tables 1-4)

| Transaction Type | Minimum Holding Period (T_m) |
|-----------------|------------------------------|
| Repo-style transactions | 5 business days |
| Other capital market transactions | 10 business days |
| Secured lending | 20 business days |

Art. 224 Tables 1-4 provide haircuts at all three liquidation periods. When scaling is needed (e.g., applying a 10-day table haircut to a repo), use Art. 226(2). When revaluation is not daily, additionally apply Art. 226(1).

### F-IRB LGDS Values (Art. 230 / Art. 161)

Under the Foundation Collateral Method, the collateral-adjusted LGD (LGD*) uses supervisory LGDS values that differ by framework:

| Collateral Type | CRR LGDS (Senior) | CRR LGDS (Sub.) | Basel 3.1 LGDS | Reference |
|----------------|-------------------|-----------------|----------------|-----------|
| Financial collateral | 0% | 0% | 0% | Art. 230 Table 5 / Art. 230(2) |
| Receivables | 35% | 65% | 20% | Art. 230 Table 5 / CRE32.9 |
| Residential / commercial RE | 35% | 65% | 20% | Art. 230 Table 5 / CRE32.10-11 |
| Other physical collateral | 40% | 70% | 25% | Art. 230 Table 5 / CRE32.12 |
| Covered bonds | 11.25% | — | 11.25% | Art. 161(1)(d) / Art. 161(1B) |
| Life insurance (Art. 232) | 40% | — | 40% | Art. 232(2)(b) |

!!! info "CRR Art. 230 Table 5 — Subordinated LGDS"
    CRR Art. 230 Table 5 provides separate LGDS columns for "senior exposures" and
    "subordinated exposures". For subordinated claims secured by receivables or real estate,
    LGDS is 65% (vs 35% senior). For other physical collateral, subordinated LGDS is 70%
    (vs 40% senior). Financial collateral remains 0% for both.

!!! info "B31 Art. 230(2) — Subordinated LGDS Distinction Removed"
    PRA PS1/26 Art. 230(2) replaces the CRR Table 5 with a simplified table containing a
    single LGDS per collateral type (0%/20%/20%/25%) with no subordinated distinction. Under
    Basel 3.1, the subordination effect is captured solely through the LGDU term (75%,
    Art. 161(1)(b)).

Unsecured LGD (LGDU) for the unsecured portion of the LGD* formula:

| Seniority | CRR LGDU | Basel 3.1 LGDU | Reference |
|-----------|----------|----------------|-----------|
| Senior unsecured (non-FSE) | 45% | 40% | Art. 161(1)(a) / Art. 161(1)(aa) |
| Senior unsecured (FSE) | 45% | 45% | Art. 161(1)(a) |
| Subordinated | 75% | 75% | Art. 161(1)(b) |

!!! warning "Not Yet Implemented — Subordinated LGDS"
    The code uses a single set of LGDS values per collateral type (35%/35%/40% CRR; 20%/20%/25%
    B31) regardless of seniority. The CRR Art. 230 Table 5 subordinated LGDS values (65%/65%/70%)
    are not applied. This means subordinated claims secured by non-financial collateral receive
    an understated LGDS. The subordination effect comes only through LGDU = 75%, not the elevated
    LGDS. See D4.13.

### LGD* Formula — Foundation Collateral Method (Art. 230)

The formula blends LGDU (unsecured) and LGDS (secured) across the secured and unsecured portions:

```
LGD* = LGDU × (EU / E(1+HE)) + LGDS × (ES / E(1+HE))
```

Where:
- `E(1+HE)` = exposure value grossed up by the exposure volatility haircut
- `ES` = haircut-adjusted collateral value, capped at `E(1+HE)`: `ES = min(C(1-HC-HFX), E(1+HE))`
- `EU` = unsecured portion: `EU = E(1+HE) - ES`
- `LGDU` = unsecured LGD (CRR: 45% uniform; B31: 40% non-FSE / 45% FSE per Art. 161(1))
- `LGDS` = secured LGD per framework (see F-IRB LGDS table above)
- `HC` = collateral haircut, `HE` = exposure haircut, `HFX` = FX mismatch haircut

Scope of the H_FX term in the formula above:

- **Financial collateral** — `HFX` = 8% × √(T_m/10) × Art. 226(1) multiplier when collateral currency ≠ exposure currency, per Art. 224 Table 4.
- **Funded non-financial collateral (receivables, real estate, other physical)** — `HFX = 0` regardless of currency mismatch. CRR Arts. 229–230 contain no FX volatility adjustment for Art. 230 collateral, and Art. 233 (the source of the 8%) sits in the unfunded-protection sub-section. The collateral value `C` is the market / mortgage-lending value per Art. 229, rebased to the reporting currency upstream by `FXConverter` at the spot rate. **PS1/26 does not inherit this scope:** its Art. 230(1)(b) applies Hfx to every Foundation Collateral Method type (pack Feature `fcm_hfx_applies_to_non_financial`; see the Basel 3.1 CRM specification).

Note: The simplified formula `LGD* = LGD × (E*/E)` where `E* = max(0, E(1+HE) - C(1-HC-HFX))` only works when LGDS = LGDU. For non-financial collateral (LGDS ≠ LGDU), the blended formula above is required.

### Mixed Collateral Pools (Art. 231)

When an exposure is secured by multiple collateral types, allocation is **sequential (waterfall)**, not pro-rata:

```
For each collateral type i (in chosen order):
  ES_i = min(C_i, E(1+HE) - sum(ES_k for k < i))
  EU = E(1+HE) - sum(ES_i)

Blended LGD* = sum(LGDS_i × ES_i / E(1+HE)) + LGDU × EU / E(1+HE)
```

The institution may choose the ordering (most favourable = lowest LGDS first). Typical waterfall: financial collateral first (LGDS=0%), then receivables (20%), then real estate (20%), then other physical (25%), with the remainder at LGDU.

Note: Pro-rata allocation gives different LGD* than sequential fill when total collateral < total exposure. Art. 231 requires sequential fill.

## Non-Financial Collateral Recognition (CRR Art. 230)

Non-financial collateral is recognised through the Foundation Collateral Method using the LGD* formula with LGDS values.

### Eligibility for Other Physical Collateral (CRR Art. 199(6))

Before any Art. 230 LGD\* mechanics can be applied, **other physical collateral**
(i.e., physical collateral that is *not* immovable property under Art. 199(2)–(4) or
receivables under Art. 199(5)) must clear the Art. 199(6) eligibility gate. CRR
Art. 199(6) requires the competent authority to permit the institution to use the
collateral, and is conditional on **all four** of the following:

| Para | Condition |
|------|-----------|
| (a) | **Liquid market.** There are liquid markets, evidenced by frequent transactions taking into account the asset type, for the disposal of the collateral in an expeditious and economically efficient manner. The institution must reassess this periodically and where information indicates material market changes. |
| (b) | **Public market prices.** There are well-established, publicly available market prices for the collateral, drawn from reliable sources (e.g., public indices), reflecting prices of transactions under normal conditions, and obtainable regularly without undue burden. |
| (c) | **Realisation analysis.** The institution analyses the market prices, the time and costs required to realise the collateral, and the realised proceeds from the collateral. |
| (d) | **70% / 10% realisation test.** *"the institution demonstrates that the realised proceeds from the collateral are not below 70% of the collateral value in more than 10% of all liquidations for a given type of collateral"* (CRR Art. 199(6)(d) verbatim, `docs/assets/crr.pdf` p. 197). Where there is material price volatility, the institution must additionally demonstrate to the competent authority that its valuation is sufficiently conservative. |

The (d) test is a **collateral-type-level** historical realisation track record — it is
assessed across the institution's full population of past liquidations of that
collateral type, not loan-by-loan. Failing the test (or any of (a)–(c)) renders
the collateral type ineligible: it cannot enter the Art. 230 LGD\* waterfall at
all, and there is no fallback to a haircut-based recognition.

Art. 199(6) eligibility is the **gate**; [Art. 230](#non-financial-collateral-recognition-crr-art-230)
governs the **mechanics** (the C\*/C\*\* minimum coverage thresholds and the
LGDS values applied to the secured portion via the LGD\* formula). The two
articles operate in sequence: 199(6) decides whether the collateral type may be
used at all, and 230 then converts the eligible collateral into an LGD effect
subject to the 30% C\* minimum and 140% C\*\* full-recognition thresholds for
"other collateral" in [Art. 230 Table 5](#f-irb-lgds-values-art-230--art-161).

Art. 199(6) also feeds the documentation duty: institutions shall document
fulfilment of (a)–(d) and the operational requirements under
[Art. 210](#crm-eligibility-principles-art-193-194). Art. 199(8) further
requires the PRA to publish a list of types of physical collateral for which
institutions can assume that conditions (a) and (b) of paragraph 6 are met
(condition (d) is institution-specific and cannot be satisfied by such a list).

!!! info "Verbatim text vs plan reference"
    The 70%/10% realisation test is sometimes informally cited as "Art. 199(3)"
    (e.g., in legacy gap-analysis tracking) because the same test sits at point
    16 of Annex VIII Part 1 of the original 2006 Capital Requirements Directive
    framework, and the renumbering between Annex VIII (CRD III) and CRR
    Art. 199 was not always updated downstream. In the consolidated UK-onshored
    CRR (`docs/assets/crr.pdf` p. 197), the rule sits at **Art. 199(6)(d)**.
    Art. 199(3) in the consolidated CRR is the unrelated UK-residential-property
    loss-rate derogation paragraph (≤ 0.3% / ≤ 0.5% loss limits for the
    derogation from the Art. 199(2)(b) repayment-source test). PS1/26 carries
    Art. 199 forward unchanged for IRB physical-collateral eligibility — the
    70%/10% test applies under both CRR and Basel 3.1.

!!! warning "Not Yet Implemented"
    The calculator does not currently enforce the Art. 199(6) eligibility gate
    on inputs. Other-physical collateral rows enter the Foundation Collateral
    Method (Art. 230) directly, subject only to the 30% C\* minimum threshold
    and 1.4× overcollateralisation ratio below. Firms relying on this code path
    must self-certify Art. 199(6)(a)–(d) compliance for each collateral type
    before submission.

### Lease Exposures Treated as Collateralised (CRR Art. 199(7) / Art. 211)

CRR Art. 199(7) — *"where the requirements set out in Article 211 are met, exposures
arising from transactions whereby an institution leases property to a third party
may be treated in the same manner as loans collateralised by the type of property
leased"* — lets a lessor's F-IRB exposure be secured by the **leased asset** rather
than treated as unsecured. PRA PS1/26 Art. 199(7) retains this verbatim (both regimes).

**Input convention.** The calculator has no dedicated lease exposure type; instead a
lease is represented through the ordinary non-financial collateral machinery. Supply
the leased asset as a `COLLATERAL_SCHEMA` row pledged to the lease exposure:

| Field | Value |
|-------|-------|
| `collateral_type` | `real_estate` (property leases) or `other_physical` (equipment / plant / vehicle leases) |
| `beneficiary_type` / `beneficiary_reference` | the lease exposure the leased asset secures |
| `market_value` | the leased asset's market value |
| `original_maturity_years` | the lease term (a finance lease intrinsically has one) |
| `is_lease_collateral_attested` | `True` — the Art. 211 attestation (see below) |

The row then flows through the Foundation Collateral Method exactly like any pledged
non-financial collateral: the Art. 230(2) FCM haircut for the leased-asset type,
the 1.4× overcollateralisation ratio, the 30% C\* minimum, and the LGD\* blend of the
LGDS ([F-IRB LGDS Values](#f-irb-lgds-values-art-230--art-161)) over the secured
portion with LGDU over the residual.

**Art. 211 attestation.** The conditions Art. 211 requires:

| Condition | How handled |
|-----------|-------------|
| (a) the Art. 208 (immovable property) / 210 (other physical) eligibility of the leased-asset type is met | **subsumed** — attesting Art. 211 attests a superset of the Art. 208/210 conditions that `is_eligible_irb_collateral` otherwise carries |
| (b) robust lessor risk management (use, location, age, planned duration, value monitoring) | attested by `is_lease_collateral_attested` |
| (c) the lessor's legal ownership and timely enforcement rights | attested by `is_lease_collateral_attested` |
| (d) the unamortised-amount vs market-value gap does not overstate the CRM | attested by `is_lease_collateral_attested` |

`is_lease_collateral_attested` is an **independent** eligibility route in the FCM gate
(`engine/crm/collateral.py::_apply_collateral_unified`): a lease row is recognised on
its own attestation, without also setting the general `is_eligible_irb_collateral`
flag. The field has **no Boolean default** — null means "not a lease-collateralised
row / no lease attestation supplied" and resolves to `False` (conservative), so
existing non-lease collateral is unaffected. It is consulted only for non-financial
collateral. Without any attestation the leased asset is not recognised: the FCM gate
zeroes its `effectively_secured` amount, LGD reverts to the senior unsecured
supervisory value (Art. 161(1)(a) 45% CRR / Art. 161(1)(aa) 40% B31 non-FSE), and one
`CRM014` warning is raised.

!!! note "Scope"
    P1.273 covers the F-IRB Foundation Collateral Method secured-LGD path only. Three
    adjacent lease mechanics are separate and unaffected by it:

    - The **lease input convention** — `drawn_amount` must arrive as the discounted
      minimum lease payments. It is not SA-only: the identical rule binds the IRB
      exposure value (CRR Art. 166(4) / PS1/26 Art. 166A(4)) and the SA exposure value
      (Art. 134(7) in both frameworks). Documented at
      [Lease exposures — the `drawn_amount` convention](../../data-model/input-schemas.md#lease-exposures-the-drawn_amount-convention).
    - **Residual-value treatment** (Art. 134(7), the `other_residual_lease` entity type
      → OTHER class 100% RW at 1/t × 100%).
    - The **third-party residual-value payment obligation**, recognisable as unfunded
      credit protection under Art. 201 and Art. 213-215 — the closing sentence of
      CRR Art. 134(7) and Art. 166(4), and of PS1/26 Art. 134(7) and Art. 166A(4).
      Art. 213(1)(c)(iii) sets its payout test at lease expiry (no clause may prevent
      timely payment "when the leasing contract has expired"). It is supplied as an
      ordinary guarantee row whose `beneficiary_reference` is the residual-value
      exposure, and takes the generic SA risk-weight substitution
      (Art. 235(1)) with its Art. 193(1) benefit test — no lease-specific code. Pinned
      by `tests/acceptance/{crr,basel31}/test_p1_300_residual_value_guarantee.py`
      (1,000,000 residual value, CQS 2 institution guarantor: 500,000 RWA under CRR,
      300,000 under Basel 3.1; a CQS 5 corporate guarantor is declined). See
      [Lease exposures](../../data-model/input-schemas.md#lease-exposures-the-drawn_amount-convention),
      which also records the open IRB question.

### Overcollateralisation Ratios

The code implements overcollateralisation ratios (1.25x receivables, 1.4x RE/physical) and 30% minimum thresholds for RE and other physical collateral. These ratios divide the haircut-adjusted collateral value before it enters the LGD* waterfall, effectively reducing the recognised secured portion.

| Category | OC Ratio | Min Threshold |
|----------|----------|---------------|
| Financial | 1.00 | 0% |
| Receivables | 1.25 | 0% |
| Real estate | 1.40 | 30% of EAD |
| Other physical | 1.40 | 30% of EAD |
| Life insurance | 1.00 | 0% |

Regulatory basis: These ratios appear in CRR Art. 230(2) (conditions for non-financial collateral recognition) and are preserved under PRA PS1/26. They are not the same as the supervisory volatility haircuts in Art. 224.

### Prior Claims on Immovable Property (CRR Art. 229(1))

CRR Art. 229(1): "The value of the collateral shall be the market value or mortgage
lending value reduced as appropriate to reflect the results of the monitoring required
under Article 208(3) and to take account of any prior claims on the immovable
property." So the property's `C` is its market value less the claims that rank ahead
of the institution's, **before** the C\* test and the C\*\* split:

```
C = max(0, MV - P)        P = prior_charge_ltv × MV
```

`prior_charge_ltv` is the collateral row's prior-charge input (a share of the property
value — the same input the SA real-estate LTV derivation adds in). The deduction is made in
`engine/crm/haircuts.py::apply_haircuts` (`prior_claim_amount_expr`), on
`value_after_haircut`, so it reaches the Art. 231 waterfall, the C\* test and the
Foundation-limb carrier `collateral_re_value` (COREP C 08.01 col 0190 — Annex II:
"values shall be determined in accordance with ... Article 229 CRR"). The AIRB
market-value carrier `collateral_re_market_value` stays the gross property value.
A null or zero `prior_charge_ltv` deducts nothing. Only real-estate rows read it: any
`REAL_ESTATE_COLLATERAL_TYPES` spelling in any letter case (`real_estate`,
`residential_property`, `CRE`, ...), the set `collateral_category_expr` files as real
estate and so carries into the C\* test. A maturity mismatch scales the net value,
`C = (MV − P) × MM` (Art. 237-239), because Art. 229(1) sets the value it applies to.

| Prior charge | C (10m loan, 10m property) | Outcome | LGD\* |
|---|---|---|---|
| 0% | 10m | ES = 10m / 1.4 | 37.86% |
| 30% | 7m | ES = 7m / 1.4 = 5m | 40.00% |
| 60% | 4m | ES = 4m / 1.4 | 42.14% |
| 80% | 2m | C/E = 20% < C\* 30% — fully unsecured, `CRM022` | 45.00% |

The input carries prior **and** pari-passu claims in one figure, and CRR Art. 229(1)
names prior claims only, so deducting a pari-passu claim in full is conservative. A
split of the input into prior, pari-passu and own-share amounts is P1.449. Pinned by
`tests/acceptance/crr/test_p1_415_art_229_firb_prior_claims.py` and
`tests/unit/crm/test_p1_415_fcm_prior_claims.py`.

### Minimum Coverage Requirements

Art. 230 specifies conditions for collateral eligibility:
- The collateral must be properly valued and regularly revalued
- The collateral value must be sufficient to justify the LGDS applied
- Specific conditions apply per collateral type (e.g., real estate valuation requirements per Art. 229)

!!! warning "`CRM022` — below C\* is treated as fully unsecured, and now says so"
    Where `C/E` falls below the 30% C\* threshold, the whole collateral category
    leaves the Art. 231 waterfall and LGD reverts to LGDU — the exposure is treated
    as **fully unsecured**, not partially secured. The `collateral_*_value` carrier
    still reports the pledge (COREP C 08.01/02 cols 0190/0200 report the Art. 199
    adjusted `C_i`, which the threshold does not scope), so the run legitimately
    shows a populated collateral column beside an unsecured LGD.

    That pairing used to be reachable with no diagnostic at all. `CRM022`
    (`engine/crm/min_collateralisation.py`) now emits one rolled-up warning per
    collateral category naming the count, the C\* percentage and up to five affected
    exposures. It is **F-IRB only** (C\* gates the Foundation LGD\* formula), needs a
    **positive Art. 199-eligible `C_i`** (an unattested pledge is `CRM014`'s cause,
    not this one), and is a **no-op under Basel 3.1**, which removes C\*/C\*\*
    entirely per PS1/26 Art. 230(1).

    The C\* condition itself has a single home,
    `below_min_collateralisation_expr`, read by both the zeroing and the warning.

## Maturity Mismatch (CRR Art. 237-239)

CRR Section 5 of Chapter 4 covers maturity mismatches across **both funded
and unfunded** credit protection. Art. 238(1A) (carried into PRA Rulebook
unchanged) enumerates the in-scope CRM methods; Art. 237 sets the
eligibility gates; Art. 239 sets the per-method valuation formula.

!!! info "B31 alignment"
    PRA PS1/26 (effective 1 January 2027) carries Art. 237/238/239 forward
    unchanged in substance — each PS1/26 article carries the note "This
    rule corresponds to Article 237/238/239 of CRR as it applied
    immediately before revocation by the Treasury". The B31 spec
    [b31/credit-risk-mitigation.md#maturity-mismatch-art-237-239](../basel31/credit-risk-mitigation.md#maturity-mismatch-art-237-239)
    holds the authoritative restatement.

### Methods in Scope (CRR Art. 238(1A))

The CRR maturity-mismatch framework applies to credit protection recognised
under any of the following methods:

| Letter | Method | Type |
|--------|--------|------|
| (a) | On-balance sheet netting (Art. 219) | Funded |
| (b) | FCCM (excluding SFTs covered by a master netting agreement) | Funded |
| (c) | Foundation Collateral Method (Art. 230) | Funded |
| (d) | Other Funded Credit Protection Method (Art. 232) | Funded |
| (e) | Risk-Weight Substitution Method — SA / Slotting guarantees and CDS (Art. 235) | **Unfunded** |
| (f) | Parameter Substitution Method — F-IRB / A-IRB guarantees and CDS (Art. 236) | **Unfunded** |

The same eligibility gates and adjustment formulas therefore apply to
collateral *and* to guarantees/CDS — there is no separate maturity-mismatch
treatment for unfunded protection in CRR. **FCSM** (Art. 222) and the A-IRB
**own-LGD** treatment (Art. 183) are the only CRM methods that sit outside
this perimeter (FCSM is excluded by Art. 239(1); own-LGD captures maturity
mismatches inside the LGD model).

## Maturity Mismatch Eligibility (CRR Art. 237)

When a maturity mismatch exists (protection residual maturity < exposure
residual maturity), credit protection is only eligible if **all** of the
following conditions are met:

1. **Art. 237(1) — combined test:** if the protection has residual maturity
   < 3 months *and* protection maturity < underlying exposure maturity,
   *"that protection **does not qualify** as eligible credit protection"*
   (CRR Art. 237(1) verbatim, `docs/assets/crr.pdf` p. 232).
2. **Art. 237(2)(a) — original maturity ≥ 1 year:** *"Where there is a
   maturity mismatch the credit protection **shall not qualify** as
   eligible"* (CRR Art. 237(2) chapeau verbatim) where the original
   maturity of the protection is less than one year.
3. **Art. 237(2)(b) — not a 1-day M-floor exposure:** the same chapeau
   applies where the exposure is a short-term exposure specified as
   subject to a one-day floor rather than a one-year floor in respect of
   the maturity value M under Art. 162(3) (repos, SFTs with daily
   margining, short-term trade-finance IRB exposures).

If any condition fails, the protection value is zeroed (collateral value =
0 for the mismatched portion). These gates apply uniformly to funded **and**
unfunded protection — a guarantee or CDS with original maturity < 1 year is
ineligible for an exposure with residual maturity > 1 year, just as a
financial-collateral instrument with the same characteristics is.

!!! info "CRR → Basel 3.1 wording change (resolves D2.55)"
    CRR Art. 237 uses **outcome-voiced** language — the protection "does
    not qualify" / "shall not qualify" as eligible. PS1/26 Art. 237
    (effective 1 January 2027) re-casts the same gates in
    **obligation-voiced** form — *"an institution **shall not use** that
    protection as eligible credit protection"*. The near-final
    instrument appended to PS9/24 rendered this as *"may not use"*
    (potentially discretionary); the final PS1/26 instrument replaces
    *"may not"* with *"**shall not**"* in both Art. 237(1) and
    Art. 237(2) chapeau, removing any residual drafting ambiguity. See
    the comparison document at
    `docs/assets/comparison-of-the-final-rules.pdf` pp. 221–223 for the
    strikethrough / insert mark-up. The functional outcome is identical
    across CRR and both PS9/24-near-final and PS1/26-final drafts — the
    protection is simply not recognised — but the precision matters
    when cross-referencing the text of individual paragraphs.

## Maturity Mismatch Adjustment (CRR Art. 239)

Two parallel formulas — Art. 239(2) for funded methods (a)–(d) and
Art. 239(3) for unfunded methods (e)–(f). The multiplier
`(t − 0.25) / (T − 0.25)` is identical between the two; only the
protection input differs.

**Art. 239(2) — funded protection (methods (a)–(d)):**

```
CVAM = CVA × (t - 0.25) / (T - 0.25)
```

`CVAM` substitutes for `CVA` in the FCCM E* formula at Art. 223(5), or
flows through Art. 219(3) for on-balance sheet netting.

**Art. 239(3) — unfunded protection (methods (e)–(f)):**

```
GA = G* × (t - 0.25) / (T - 0.25)
```

`GA` is used as the credit-protection amount input to the **RWSM** (Art.
235, SA / slotting) or the **PSM** (Art. 236, IRB) — the same formula
governs guarantee and credit-derivative maturity mismatches under both
SA and IRB.

In both formulas: `t` = residual protection maturity (years, capped at T);
`T` = min(residual exposure maturity, 5) years. **No adjustment** when
`t ≥ T` (the multiplier collapses to 1).

## Multi-Level Collateral Allocation

Collateral is allocated at three levels, distributed pro-rata:

1. **Exposure level** - Collateral pledged directly against an exposure
2. **Facility level** - Collateral pledged against a facility, shared across its exposures
3. **Counterparty level** - Collateral pledged against a counterparty, shared across all exposures

Financial and non-financial collateral are tracked separately to apply the correct overcollateralisation ratios and minimum thresholds.

### Nested facilities — ancestor cascade

The facility level is **hierarchy-aware**: facilities may nest (a facility whose
parent is another facility, expressed via `FACILITY_MAPPING_SCHEMA` with
`child_type = "facility"`). Collateral pledged at **any ancestor facility**
(immediate parent, grandparent, … root) cascades pro-rata (by `ead_for_crm`) to
**every descendant exposure** of that facility, not just the exposures whose
immediate `parent_facility_reference` matches the pledged facility.

The `HierarchyResolver` emits an `ancestor_facilities` list column on each
exposure (its parent plus every ancestor up to the root, including the facility
itself). The CRM stage (`_build_facility_lookup` for `pledge_percentage`
resolution, and `_cascade_facility_collateral` for the allocation) consumes it:

- A `pledge_percentage` at an ancestor facility `F` resolves against the **whole
  subtree EAD** of `F` (Σ `ead_for_crm` over all descendants), not `F`'s direct
  exposures only.
- Each descendant's share of `F`'s collateral is `ead_for_crm / subtree_ead(F, pool)`.
- Pledges made at several ancestor levels **stack** on a descendant.
- A pledge at a specific facility reaches only that facility's subtree — sibling
  subtrees sharing a common root are unaffected.

The cascade is pool-aware (see below) and **reduces exactly to single-level
allocation** when no facility hierarchy is present (`ancestor_facilities` =
`[parent]`).

The **same ancestor cascade applies to facility-level provisions and
guarantees** (`engine/crm/provisions.py`, `engine/crm/guarantees.py`): a
provision (CRR Art. 111(2)) or guarantee (CRR Art. 213-217) pledged at any
ancestor facility is allocated pro-rata across the whole descendant subtree
(by EAD-equivalent weight / `ead_after_collateral` respectively), so all three
credit-protection types behave consistently across nested facilities.

### Pool-Aware Pro-Rata for AIRB Mixes (CRR Art. 181)

Under A-IRB, the firm's own modelled LGD already reflects the credit-risk-mitigating effect of any collateral incorporated in the model. To prevent double-counting when a counterparty has both A-IRB and non-A-IRB exposures, the pipeline splits the pro-rata base by pool:

- **AIRB-eligible pool** = exposures where the modelled LGD is preserved by CRM (`approach == AIRB` and the row is not falling back to the supervisory formula).
- **Non-AIRB pool** = FIRB / SA / Slotting (and AIRB rows that fall back to the supervisory formula under Art. 169B insufficient-data fallback or Foundation election under Basel 3.1).

Behaviour:

| Collateral row | Direct (`beneficiary_type` = `loan` / `exposure`) | Facility / Counterparty pro-rata |
|---|---|---|
| `is_airb_model_collateral = False` (default) | 1:1 to the named exposure (unchanged) | Pro-rata over the **non-AIRB pool only**; AIRB-pool rows get zero |
| `is_airb_model_collateral = True`            | 1:1 if the named exposure is in the AIRB pool; otherwise zero allocation + **CRM006** warning | Pro-rata over the **AIRB pool only**; non-AIRB rows get zero |

Setting `is_airb_model_collateral = True` is the firm's assertion that the collateral has been used to construct the internal LGD model. The flag has no numerical effect on AIRB rows (their modelled LGD is preserved either way) but it ensures the collateral is excluded from CRM allocation to non-AIRB exposures of the same counterparty / facility.

## Guarantee Substitution (CRR Art. 213-217)

!!! note "Slotting-approach beneficiaries (RWSM — fixed 2026-07-12)"
    Guaranteed **slotting** exposures substitute via the Risk-Weight
    Substitution Method exactly like SA beneficiaries: the covered
    ``__G_`` leg takes the guarantor's SA risk weight when beneficial, and
    the covered part's Art. 158(6) slotting EL is zeroed (PS1/26
    Art. 235(1)/(1A); the covered part is an exposure to a guarantor
    treated under SA, which carries no slotting EL). Gated by the cited
    pack Feature ``slotting_guarantee_substitution`` — enabled under BOTH
    regimes by recorded operator decision (2026-07-12): PS1/26 Part 3
    mandates RWSM; the CRR black-letter basis is recorded as unsettled
    (COREP Annex II para 43 + the Art. 235 analogy) and reverts with a
    one-line pack flag flip. Non-beneficial guarantees are never applied
    (the guarantee cannot increase RWA or erase EL).

### Approach

The guarantor's risk weight replaces the borrower's risk weight for the guaranteed portion of the exposure, but only when this is beneficial.

### Application Logic

1. Look up the guarantor's risk weight based on entity type and CQS
2. Compare to the borrower's risk weight
3. If guarantor RW < borrower RW, apply substitution on the guaranteed portion
4. If guarantor RW ≥ borrower RW, no substitution (guarantee is non-beneficial)

### Blended Risk Weight

For partially guaranteed exposures:

```
RW_blended = (unguaranteed_portion x borrower_RW + guaranteed_portion x guarantor_RW) / EAD
```

### Tracking Fields

The calculator tracks pre- and post-CRM values for audit:

- `pre_crm_counterparty_reference` / `post_crm_counterparty_guaranteed`
- `pre_crm_exposure_class` / `post_crm_exposure_class_guaranteed`
- `guaranteed_portion` / `unguaranteed_portion`
- `is_guarantee_beneficial`

## Unfunded Credit Protection Adjustments (Art. 233)

### FX Mismatch for Guarantees/CDS (Art. 233(3-4))

When a guarantee or credit derivative is denominated in a different currency from the exposure:

```
G* = G × (1 - H_fx)
```

Where `H_fx` is from Art. 224 Table 4 at the applicable liquidation period (8% at 10-day, scaled by Art. 226(1) if not daily revalued). The guaranteed amount must be reduced before applying substitution.

### Art. 114(4)/(7) Domestic Sovereign Treatment Under Substitution

Under the substitution approach (Art. 215-217), the guaranteed portion is treated as an exposure to the guarantor. For an EU/UK central government or central bank guarantor, Art. 114(4) (and Art. 114(7) for Basel 3.1) grants a 0% risk weight when that substituted exposure is denominated in the sovereign's domestic currency.

The domestic-currency test is therefore evaluated against the **guarantee** currency, not the currency of the underlying exposure. A GBP loan guaranteed by an EU sovereign in EUR still qualifies for 0% RW on the guaranteed portion, because the substituted claim against the sovereign is in EUR. The cross-currency mismatch between the guarantee and the underlying loan is handled separately by the Art. 233(3) 8% FX haircut above.

This short-circuit takes precedence over the internal-rating routing: a sovereign guarantor with an internal PD and IRB permission still receives the 0% SA treatment when the guarantee is in the sovereign's domestic currency.

### Art. 114(3) ECB Guarantor — 0% Unconditionally

Art. 235(1) prices the covered part at the risk weight of a (comparable) direct
exposure to the protection provider, and a direct exposure to the European Central Bank
is 0% under Art. 114(3) in both regimes: CRR "Exposures to the ECB shall be assigned a
0 % risk weight"; PS1/26 "Exposures to the European Central Bank shall be assigned a 0%
risk weight". The provision has no rating limb and no currency limb, and Art. 235(3)
restricts only the 114(4) / 114(7) treatments to domestic-currency guarantees funded in
that currency. So an ECB guarantor (`entity_type = "central_bank_ecb"`) prices at 0%
whatever its CQS, its country tag, the guarantee currency or the funding currency.

The guarantor risk-weight chain
(`engine/sa/guarantor_rw.py::build_guarantor_rw_expr`) evaluates the ECB branch first,
ahead of the domestic-sovereign and Table 1 branches. It keys on the **guarantor's**
entity type — never the obligor's `cp_entity_type`, so a guarantee *of* a loan to the ECB
keeps its own guarantor's weight. Like every branch it also requires a guarantor class,
so an ECB guarantor declined by the Art. 201 gate still prices nothing.

Reach: the chain is shared, so the 0% applies to SA beneficiaries, to slotting
beneficiaries, to IRB beneficiaries routed to risk-weight substitution
(`guarantor_approach = "sa"`), and — under Basel 3.1 — to the SA-equivalent risk weight
of every row that feeds the output floor's S-TREA. It does not reach an ECB guarantor
that carries an internal PD on an IRB beneficiary where the firm holds IRB permission
for the central-government class: that guarantee goes to parameter substitution.

Until P1.358 the chain had no ECB branch. The ECB fell into the central government /
central bank class and onto the Table 1 ladder — 100% unrated, 20% / 50% / 150% at
CQS 2 / 3 / 6 — so an unrated ECB guarantee on a 100%-weighted borrower was declined as
non-beneficial. It reached 0% only at CQS 1, or by the 114(7) EU-domestic branch when
tagged with a euro-area country and guaranteed and funded in EUR.

### Valuation of G (Art. 233(1)) — amount, percentage and one cap per contract

Art. 233(1): G is "the amount that the protection provider has undertaken to pay in the
event of the default or non-payment of the borrower". The calculator resolves it in
[`engine/crm/protection_value.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/master/src/rwa_calc/engine/crm/protection_value.py)
after multi-level expansion, against E at the CCF=100% basis (`ead_for_crm`, Art. 235(1)(a)):

| Inputs | G |
|---|---|
| `amount_covered` only | `amount_covered` |
| `percentage_covered` only (amount null or 0) | `percentage_covered × E` |
| both | `min(percentage_covered × E, amount_covered)` — "x% of the exposure, up to the amount" |

Rows that share a `guarantee_reference` are **one contract with one cap**. Its cap (the
largest `amount_covered` on its rows, read before multi-level expansion rescales the
amount) is shared across the rows pro-rata to each row's covered demand `min(G, E)`, so
the contract is never recognised more than once — also when the same contract is entered
at counterparty and at loan level. A contract repeated for the same beneficiary and
guarantor restates one undertaking, so only its largest row is used — the cap alone could
not stop that double count for a percentage-only contract, which states no amount. This is
how a pool guarantee over obligors in different counterparty or facility trees is stated.
Rows that disagree on the amount (the largest is used) or repeat one beneficiary raise
**`CRM028`** (Art. 213(1)(b): the extent of the
protection must be clearly defined and incontrovertible).

### CDS Restructuring Exclusion (Art. 233(2))

For a credit derivative that does not include restructuring as a credit event
(`includes_restructuring = False`), Art. 233(2), identical in CRR and PS1/26:

- (a) where G is not higher than the exposure value, G is **reduced by 40%**
  (pack `restructuring_exclusion_haircut`);
- (b) where G is higher than the exposure value, the protection is valued at **no more
  than 60% of the exposure value** (pack `restructuring_exclusion_exposure_cap`).

The calculator applies it to every such credit derivative whether the cover was stated as
an amount or as a percentage (G is resolved first), with E at the CCF=100% basis, and
**before** the Art. 233(3) currency haircut. PS1/26 Art. 233(3) defines G there as "the
value of the credit protection as determined by paragraph 1 and 2"; CRR calls it "the
nominal amount of the credit protection". The calculator uses the PS1/26 order in both
regimes — under CRR it is the more conservative order where the two differ (G > E with a
currency mismatch).

A `guarantee_type` naming a credit derivative (`credit_derivative`, `cds`,
`credit_default_swap`, `total_return_swap`, `trs`) makes the row a credit derivative even
where `protection_type` says otherwise; the disagreement raises **`CRM030`**.

!!! note "Not implemented"
    The PS1/26 Art. 216(3) derogation for corporate exposures (restructuring need not be a
    credit event where a 100% vote is needed to amend the underlying and the domicile has a
    well-established bankruptcy code) is not implemented: the cut always applies.

## Partial Protection and Tranching (Art. 234 / Art. 235(2))

### Proportional Coverage

When unfunded credit protection covers only a proportion of the exposure:

- The **covered portion** receives the protection provider's risk weight (substitution)
- The **uncovered portion** retains the obligor's risk weight
- The split is simple pro-rata: `covered = guarantee_amount / exposure_value`

Art. 235(2) allows this only "where the protected and unprotected parts of the exposure
are of equal seniority" — which is what a pro-rata share is.

### Tranched Coverage (Art. 234)

CRR Art. 234: "Where an institution transfers a part of the risk of a loan in one or more
tranches, the rules set out in Chapter 5 shall apply." (PS1/26 Art. 234(1) to the same
effect, and adds that a materiality threshold below which no payment is made "shall" be
treated as a retained first-loss position.) A guarantee of a band of the loss — first loss
`[0, d)` or mezzanine `[a, d)` — is not of equal seniority with the retained parts, so
Art. 235(2) forbids the substitution.

The calculator does not run Chapter 5 for such protection. A guarantee row with an
`attachment_amount` above zero, or any `detachment_amount`, is therefore **not recognised**:
the eligibility screen
([`engine/crm/protection_screen.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/master/src/rwa_calc/engine/crm/protection_screen.py))
drops it before the split and raises **`CRM027`** naming it. The exposure keeps its
unprotected requirement — the CRR Art. 268(1) upper bound of the Chapter 5 result.

!!! note "Implementation Status"
    Proportional coverage is implemented. Tranched coverage is declined (no relief), never
    substituted on the band. The previous P1.30(e) behaviour — splitting the exposure into
    first-loss, protected and senior legs and substituting on the protected band — is
    withdrawn. Deductibles / payment thresholds have no input field.

### Letters of Comfort and Keepwells (Art. 213(1)(b)-(d), Art. 215(1)(b))

A guarantee must be "an explicitly documented obligation assumed by the guarantor"
(Art. 215(1)(b)). A row whose `guarantee_type` is `letter_of_comfort`, `comfort_letter`,
`keepwell` or `keepwell_agreement` (matched case-insensitively, spaces and hyphens folded)
is **not recognised** and raises **`CRM029`**.

## Cross-Approach CCF Substitution (CRR Art. 153(3))

When an IRB exposure is guaranteed by a counterparty under the Standardised Approach, the guaranteed portion uses SA CCFs instead of IRB supervisory CCFs.

### Guarantor Approach Determination

The guarantor's approach is "sa" when:
- The firm lacks IRB permission for the guarantor's exposure class, OR
- The guarantor has only an external rating (no internal PD)

The guarantor's approach is "irb" only when both conditions are met:
- The firm has IRB permission for the guarantor's exposure class, AND
- The guarantor has an internal rating with PD

### EAD Split

```
ead_guaranteed = guarantee_ratio × (drawn + undrawn × ccf_sa)
ead_unguaranteed = (1 - guarantee_ratio) × (drawn + undrawn × ccf_irb)
```

### Only a Recognised Guarantee Keeps the SA Factor (P1.398)

The CRM stage makes the split as soon as the guarantor routes to SA, but whether the
guarantee is **recognised** is decided later, in the IRB stage (the RW-only benefit
test of Art. 193). A guarantee the IRB stage declines is not recognised, so the leg
keeps the exposure value of an IRB exposure with no protection: CRR Art. 166(8)-(10)
(Art. 193(3) "may amend"; not amending changes nothing) and PS1/26 Art. 166A-166D
(Art. 193(2A): an item of protection the firm disregards). Double default is priced
on that same value — CRR Art. 153(3): "RW · exposure value · (0.15 + 160 · PD_pp)".

So the swap is provisional:

| Final treatment of the covered part | Exposure value of the covered leg |
|---|---|
| SA risk-weight substitution (`guarantee_status = SA_RW_SUBSTITUTION`) | SA factor: `drawn + undrawn × ccf_sa` (as above) |
| Declined (`GUARANTEE_NOT_APPLIED_NON_BENEFICIAL`) | own IRB value: `drawn + undrawn × ccf_irb` (or the A-IRB own EAD) |
| Double default (`DOUBLE_DEFAULT`, CRR only) | own IRB value |

The CRM stage keeps the leg's pre-swap value on `ead_pre_cross_approach_ccf` (null where
it did not swap). After the benefit decision, `engine/irb/guarantee.py::
_settle_cross_approach_ccf` puts every swapped leg on its final value:

- a leg that ends SA risk-weight substituted takes its CRM-exit value on the SA factor;
  its portions and CCF carriers stay as the CRM stage left them;
- every other swapped leg (declined, or double default) takes the own value:
  `guaranteed_portion` and `unguaranteed_portion` become `own × guarantee_ratio` and
  `own × (1 − guarantee_ratio)` (the pre-swap covered share), `ead_after_collateral`
  their sum, `double_default_unfunded_protection` (C 08.01 col 0220) the own covered
  amount, and `ccf_guaranteed` returns to `ccf_original`, so C 08.01 / OF 08.01
  column 0110 reports the Art. 166 / 166A-166D value and a declined leg books no
  substitution outflow (cols 0040 / 0070).

Every IRB amount derived from `ead_final` — RWEA, EL, the post-model adjustments and the
pre-substitution copies `rwa_irb_original`, `pre_crm_rwa`, `expected_loss_irb_original`
— is linear in it, so the settle step rescales each by `final value / ead_final as the
formulas saw it`. The result therefore does not depend on which value the formulas ran
on: the IRB calculator runs them on the own value (`restore_own_irb_exposure_value`,
before `apply_all_formulas`), so a declined leg needs no rescale, and a caller composing
the transforms without that step settles to the same figures. The one leg a rescale
cannot repair — amounts computed on a zero `ead_final` with a non-zero final value — is
left as it reached the settle step; no CRM-stage frame produces one. A leg that ends SA
risk-weight substituted carries the same figures as before P1.398, to floating-point
rounding.

Multi-guarantor groups. `redistribute_non_beneficial` runs before the settle step, on
the CRM-exit amounts. A reverted row it zeroed (its cover handed to a beneficial
co-guarantor) keeps zero portions. A reverted row it filled (a double-default row) keeps
the absorbed cover unscaled — it is the co-guarantor's cover, not this row's — and only
up to the protection still unused on the own basis, so its covered portion never
exceeds the protection amount `original_guarantee_amount` (CRR Art. 236(1)/(3)). On
those redistributed rows `guaranteed_portion + unguaranteed_portion` does not equal
`ead_final`. That is not new with P1.398: `redistribute_non_beneficial` compares the
CCF = 100% `original_guarantee_amount` with a post-CCF `guaranteed_portion`, so any leg
with a conversion factor below 100% shows headroom its guarantor does not have, and the
row it takes cover from keeps its whole RWEA. That is an open residual, not handled
here.

Measured direction: CRR F-IRB commitments rise (Art. 166(8)(d) 75% against SA
50/20/0%); a CRR short-term trade letter of credit booked medium-risk issued falls
(Art. 166(8)(b) 20% against the SA 50%); A-IRB own estimates — an own conversion
factor (CRR Art. 166(8), PS1/26 Art. 166D(1)(a)) or a Basel 3.1 own estimate of EAD
(Art. 166D(3)) — move either way. A Basel 3.1 F-IRB leg on the plain Table A1 factor
does not move (Art. 166C(1) makes the F-IRB factor the SA one); one whose F-IRB factor
carries an engine override the swap's raw Table A1 lookup omits (Row 4(b) UK
residential commitments, the Art. 111(1)(c) lower-of, Art. 166A(5) purchased
receivables) can, and is not measured here. The SA-equivalent for the Basel 3.1
output floor (`sa_rwa`) is computed by the
SA calculator before the IRB stage runs, on the CRM-exit value — on a swapped covered
leg that is the Art. 111 basis — and is not changed; the floor threshold moves only
through OF-ADJ, because the IRB expected loss moves.

### Output Fields

- `ccf_original`, `ccf_guaranteed`, `ccf_unguaranteed`
- `guarantee_ratio`, `guarantor_approach`, `guarantor_rating_type`
- `ead_pre_cross_approach_ccf` (CRM exit only): the covered leg's own IRB exposure
  value before the swap; null where no swap was made

## Provision Resolution (Before CRM)

Provisions are resolved **before** the CRM waterfall (and before CCF application). See [Provisions Specification](provisions.md) for the drawn-first deduction approach and multi-level beneficiary resolution. The CRM waterfall (collateral → guarantees) operates on the provision-adjusted EAD.

## CRM Method Selection (PRA PS1/26 Art. 191A)

Basel 3.1 replaces the old Art. 108 with Art. 191A, introducing a formal decision tree
for CRM method selection. Key structural rules:

- **Para 2(d)**: No double-counting — funded and unfunded CRM must not be recognised
  simultaneously on the same portion of an exposure.
- **Para 3**: Consistency — an institution must use the same CRM method for the same type
  of unfunded credit protection across its portfolio.
- **Para 5 (Art. 193)**: Multiple CRM forms on a single exposure require the exposure to
  be subdivided into separately-covered parts.
- **Para 6 (Art. 193)**: Multiple items of the same CRM form with different maturities
  require the exposure to be subdivided by maturity.
- **Para 7 (Art. 193)**: Single collateral item covering multiple exposures must be allocated
  without double-counting.

### Part 1 — Funded CRM with CCR Exposure
CCR exposures → IMM / SFT VaR Method / Financial Collateral Comprehensive Method (FCCM) /
Financial Collateral Simple Method (FCSM, SA only)

### Part 2 — Funded CRM without CCR
1. On-balance sheet netting → Art. 219
2. Financial collateral → FCSM (Art. 222, SA only) / FCCM (Art. 223)
3. Immovable property / receivables / other physical → Foundation Collateral Method
   (Art. 229-231, F-IRB) / LGD Modelling (A-IRB)
4. Life insurance / instruments from institutions → Other Funded Protection Method (Art. 232)

### Part 3 — Unfunded CRM
- SA / Slotting → Risk-Weight Substitution Method (Art. 235)
- F-IRB / A-IRB → Parameter Substitution Method (Art. 236)
- A-IRB (own estimates) → LGD Adjustment Method (Art. 183)

### Part 4 — Unfunded Covered by Funded
Where an unfunded credit protection contract is itself covered by funded credit protection,
the funded CRM is applied to the unfunded protection first (Parts 1-2), then the adjusted
unfunded protection is applied to the original exposure (Part 3).

## CRM Eligibility Principles (Art. 193-194)

### Art. 193 — General Principles

- **Para 5**: Where multiple forms of CRM cover a single exposure (e.g., collateral + guarantee),
  the institution must subdivide the exposure into the portion covered by each form and
  calculate the risk-weighted exposure amount for each portion separately.
- **Para 6**: Where multiple items of the **same** CRM form have different maturities (e.g.,
  two guarantees with different expiry dates), the institution must subdivide the exposure
  according to the maturity of each protection item.
- **Para 7**: Where a single collateral item covers multiple exposures, the institution must
  allocate the collateral value across the exposures without double-counting. The total
  recognised collateral value across all covered exposures must not exceed the collateral's
  market value.

### Art. 194 — Eligibility Conditions

**Funded credit protection** (Art. 194(1)-(4)):

- Must be from the eligible lists in Art. 197-200
- Must be sufficiently liquid and stable in value over time
- No material positive correlation between the collateral value and the obligor's credit quality
  (own-issued debt is excluded)

**Unfunded credit protection** (Art. 194(5)-(6)):

- Must be an eligible agreement type per Art. 203 (guarantees) or Art. 204(1) (credit derivatives)
- Must be legally effective and enforceable in all relevant jurisdictions
- Protection provider must be from the eligible list in Art. 201

## Eligible Collateral (Art. 197)

Art. 197 lists eligible financial collateral for the FCSM, FCCM, and Foundation Collateral
Method:

| Art. 197(1) Para | Collateral Type | CQS Eligibility |
|------------------|-----------------|-----------------|
| (a) | Cash on deposit or cash-assimilated instruments | N/A |
| (b) | Central government/CB debt securities | CQS 1-4 (CQS 5-6 ineligible) |
| (c) | Institution/PSE debt securities | CQS 1-3 (CQS 4-6 ineligible) |
| (d) | Other entity debt securities (corporate rules) | CQS 1-3 (CQS 4-6 ineligible) |
| (e) | Short-term credit assessment debt securities | CQS 1-3 |
| (f) | Main index equities and convertible bonds | N/A |
| (g) | Gold | N/A |
| (h) | Non-resecuritisation securitisation positions | RW <= 100% |

### Additional Comprehensive-Method Collateral (Art. 198)

Art. 198(1) extends the eligible list **only where the institution uses the
Financial Collateral Comprehensive Method** (the calculator's default):

| Art. 198(1) Para | Collateral Type | Condition |
|------------------|-----------------|-----------|
| (a) | Non-main-index equities / convertible bonds | Listed on a recognised exchange |
| (b) | Units/shares in CIUs | Daily quote; underlying limited to Art. 197/198 instruments |

**Non-main-index equity eligibility (P1.271).** An equity that is neither included
in a main index (Art. 197(1)(f), eligible under all methods) nor attested listed on
a recognised exchange (Art. 198(1)(a)) is **ineligible** — the engine zeroes its
value, clears `is_eligible_financial_collateral`, and raises a `CRM018` warning. The
`is_listed` flag carries the recognised-exchange attestation; null resolves
conservatively to *not listed*. The Art. 224 Table 3/4 other-listed haircut
(25% CRR / 30% Basel 3.1) is a valuation parameter and is unaffected by the
eligibility gate. The condition is comprehensive-method scope, **not** a repo/SFT
restriction. PS1/26 carries Art. 197(1)(f)/198(1)(a) forward unchanged.

### Requirements for Financial Collateral (Art. 207)

CRR Art. 207(1): *"Under all approaches and methods, financial collateral and gold
shall qualify as eligible collateral where all the requirements laid down in
paragraphs 2 to 4 are met."* Paragraphs 2-4 are the correlation test (no material
positive correlation; the obligor's own securities are excluded), legal certainty
(enforceability in every relevant jurisdiction) and the operational requirements
(documentation, risk control, revaluation at least every six months, segregation).
Paragraph 5 (residual maturity at least the exposure's) binds the Simple Method only.

`is_eligible_financial_collateral` is the firm's attestation of paragraphs 2-4. One
predicate reads it for every method (`engine/crm/expressions.py::art207_attested_expr`):
the Comprehensive Method's E\*, the Simple Method's substitution and, since P1.445
(review CL-06), the Foundation Collateral Method. On F-IRB an unattested cash or
financial row (`art207_unattested_expr`) is zeroed on the Art. 231 waterfall feed and
on the col 0180 carriers (`collateral_financial_value` / `collateral_cash_value`)
beside the Art. 199 gate, so it gives no LGD\* relief and reports in no C 08.01 col
0180 cell; a rolled-up `CRM031` warning names it. The loader seals an absent or null
flag to `False`, so "never populated" and "marked as failing" are treated alike.
Covered bonds, life insurance and the non-financial categories are outside this gate
(Art. 199 / Art. 232). A collateral frame with no flag column at all (a direct
caller's, never the production path) is eligible by type alone.

Example (F-IRB senior corporate, E = 10,000,000, 6,000,000 cash): attested LGD\* =
0.45 x 4,000,000 / 10,000,000 = 0.18; unattested LGD\* = 0.45.

## Eligible Unfunded Protection Providers (Art. 201)

Art. 201(1) is an exhaustive list; Art. 194(5) admits only a provider *"included in the
list of eligible protection providers set out in Article 201 or 202, as applicable"*.
The engine gates it in `engine/crm/guarantor_eligibility.py::assign_guarantor_approach`
and names each rejected guarantor in a CRM013 warning.

| Provider type | Limb | SA / slotting beneficiary | F-IRB beneficiary |
|---------------|------|---------------------------|-------------------|
| Central governments and central banks | (1)(a) | Yes | Yes |
| Regional governments and local authorities | (1)(b) | Yes | Yes |
| Multilateral development banks | (1)(c) | Yes | Yes |
| International organisations (0% RW under Art. 117) | (1)(d) | Yes | Yes |
| Public sector entities | (1)(e) | Yes | Yes |
| Institutions (and Art. 119(5) financial institutions) | (1)(f) | Yes | Yes |
| Corporates with an ECAI credit assessment | (1)(g)(i) | Yes | Yes |
| Corporates with an internal rating only | (1)(g)(ii), (2) | No | Yes (parameter substitution) |
| Qualifying central counterparties (`entity_type` `ccp`, `is_qccp` True) | (1)(h) | Yes | Yes |
| Non-qualifying central counterparties (`ccp`, `is_qccp` False or not supplied) | as a corporate, (1)(g)(i) / (ii), (2) | With an ECAI assessment only (otherwise CRM013) | With an ECAI assessment or an internal rating |
| Natural persons (`is_natural_person` True, or `entity_type` `individual` / `natural_person` / `retail`) | none | **No** (CRM013) | **No** (CRM013) |

Art. 201(1)(g)(ii) admits an internally rated corporate for *"institutions calculating
risk-weighted exposure amounts and expected loss amounts under the IRB Approach"*. The
engine applies it to F-IRB and A-IRB beneficiaries, not to slotting.

**The guarantor's `is_natural_person` flag decides, whatever its `entity_type`.** Limb (g)
admits *"other corporate entities"*. A sole trader booked `entity_type` `corporate`,
`company` or `specialised_lending` with `is_natural_person` True is a natural person, not
a corporate entity, so neither its ECAI assessment nor its internal rating admits it: the
guarantee is declined on SA, slotting and F-IRB beneficiaries with the natural-person
CRM013 (P1.395). The signal is the one the classifier uses for the obligor
(`natural_person_expr`), read on the guarantor's own counterparty row, never the
obligor's. A flagged row booked under any other type (for example `sovereign`,
`institution` or `ccp`) is contradictory input; the engine takes the conservative reading
and declines it too, including the domestic-currency CGCB 0% short-circuit, and the CRM013
names the flag and the entity type so the record can be corrected.

A declined guarantee is declined in the outcome, not only in its labels. The gate clears
the guarantor class, and the guarantor risk-weight chain (`build_guarantor_rw_expr`, used
by both the SA and the IRB substitution paths) prices nothing for an empty class: its one
branch that also reads the entity type (named MDB) requires a class too. The covered leg
therefore keeps the borrower's own risk weight, PD and LGD, and its output-floor
SA-equivalent, for a flagged guarantor of every entity type. This is pinned end to end in
both regimes by `tests/acceptance/test_p1_395_flagged_natural_person_guarantor_pipeline.py`.

**A CCP guarantor is an institution or a corporate, never 2% / 4% (P1.396).** A guarantee
is not a trade exposure. Art. 107(2), identical in CRR and PS1/26: *"For trade exposures
and for default fund contributions to a central counterparty, institutions shall apply the
treatment set out in [Section 9] ... For all other types of exposures to a central
counterparty, institutions shall treat those exposures as follows: (a) as exposures to an
institution for other types of exposures to a qualifying CCP; (b) as exposures to a
corporate for other types of exposures to a non-qualifying CCP."* Art. 235(1) prices the
covered part at the weight *"of exposures to the protection provider as specified under
Chapter 2"* (PS1/26: *"of a comparable direct exposure to the protection provider"* under
the SA). So:

- a qualifying CCP (`is_qccp` True) keeps the institution class the entity map gives
  `ccp`, is admitted by (1)(h), and its guarantee takes the institution weight: CRR
  Art. 120 Table 3 / Art. 121, Basel 3.1 ECRA Table 3 or SCRA for an unrated one;
- any other CCP (`is_qccp` False; the loader seals a null or unsupplied flag to False) is
  booked `corporate` before the gate runs
  (`guarantor_eligibility.demote_non_qualifying_ccp_guarantors`). It is then an "other
  corporate entity": eligible with an ECAI assessment (corporate weight, CRR Table 5 /
  Basel 3.1 Table 6), or with an internal rating on an IRB beneficiary (parameter
  substitution under the corporate class), and otherwise declined with a CRM013 that names
  the non-qualifying CCP. Its guaranteed part flows into the corporate class in COREP.

The CCR (CRR) Part Art. 306(1) / 305(3) 2% / 4% weights apply only to SA-CCR and FCCM trade
rows facing a qualifying CCP (`engine/sa/ccp_exposures.py`). The guarantor RW chain no
longer has a CCP branch, and the guarantor's `is_ccp_client_cleared` flag, a property of a
trade rather than of a protection provider, is not read. Pinned in both regimes by
`tests/unit/crm/test_p1_396_ccp_guarantor.py` and, end to end with the Basel 3.1
output-floor SA-equivalent, `tests/acceptance/test_p1_396_ccp_guarantor_pipeline.py`.

**A-IRB (own-LGD) beneficiaries are outside this list.** Art. 108(2): *"For an exposure to
which an institution applies the IRB Approach by using their own estimates of LGD and
conversion factors under Article 151, the institution may use credit risk mitigation in
accordance with Chapter 3."* Recognition then follows Art. 161(3), 164(2) and 183, where
the firm sets the guarantor types it recognises. So a natural person's guarantee of an
A-IRB exposure keeps parameter substitution, while the same guarantee of an SA, slotting
or F-IRB exposure is declined (P1.384).

## Financial Collateral Simple Method — FCSM (Art. 222)

Paragraph references below verified verbatim against `docs/assets/crr.pdf` pp. 216–217
(UK-onshored CRR Art. 222, as amended to 1 Jan 2022).

**Scope (Art. 222(1)).** SA-only method. *"Institutions **shall not use** both the
Financial Collateral Simple Method and the Financial Collateral Comprehensive Method,
except for the purposes of Articles 148(1) and 150(1)"* (CRR Art. 222(1) verbatim —
permanent partial use / phased IRB roll-out), and *"Institutions **shall not use** this
exception selectively with the purpose of achieving reduced own funds requirements or
with the purpose of conducting regulatory arbitrage"*.

Under the FCSM the risk weight of the collateral substitutes for the obligor risk weight
on the secured portion of the exposure. The unsecured remainder keeps the counterparty's
unsecured risk weight.

### Art. 222(3) — 20% RW Floor

The collateralised portion takes the risk weight that would apply to a direct exposure
to the collateral instrument (Art. 222(3), first sub-paragraph), subject to a minimum
**20%** floor (Art. 222(3), second sub-paragraph), **except as specified in paragraphs
4 to 6**.

### Art. 222(4) — 0% / 10% Floor for SFTs (Art. 227 Criteria)

CRR Art. 222(4) verbatim (`docs/assets/crr.pdf` p. 217):

!!! quote "CRR Art. 222(4)"
    *"Institutions shall assign a risk weight of 0 % to the collateralised portion of
    the exposure arising from repurchase transaction and securities lending or borrowing
    transactions which fulfil the criteria in Article 227. Where the counterparty to the
    transaction is not a core market participant, institutions shall assign a risk weight
    of 10 %."*

For **repurchase transactions and securities lending or borrowing transactions** that
meet the criteria in Art. 227, the collateralised portion receives:

- **0%** RW where the counterparty is a **core market participant** (as enumerated in
  Art. 227(3) — sovereigns / central banks eligible for 0% RW under Art. 114, supervised
  institutions and investment firms, certain insurance undertakings, regulated CIUs
  subject to capital requirements, regulated pension funds, and recognised clearing
  organisations);
- **10%** RW where the counterparty is **not** a core market participant — that is, the
  counterparty fails the Art. 227(3) enumeration even though all other Art. 227(2)
  preconditions are met. The 10% reflects the higher counterparty-credit-risk tail under
  a re-margining failure when the obligor sits outside the closed circle of regulated
  market participants who underpin the 0% treatment.

Art. 222(4) is a **risk-weight floor**, not a haircut. It substitutes for the obligor
risk weight on the collateralised portion of the SFT — it does not modify the collateral's
market value. Volatility haircuts are an FCCM mechanic (Art. 223–227) that does not exist
under FCSM; FCSM uses the unadjusted market value of the collateral (Art. 222(2)) and
expresses risk mitigation purely through the substituted RW.

Art. 222(4) governs SFTs only — it does not extend to non-SFT transactions or to OTC
derivative collateralisation (those fall under paragraphs 5 and 6 respectively).

#### Art. 227(2)(a)–(h) — Preconditions for the FCSM SFT Carve-Out

Art. 222(4) is gated by the eight conditions in Art. 227(2). All eight must be met
for the 0% / 10% RW to apply; otherwise the SFT falls back to the Art. 222(3) 20%
RW floor. The conditions cover (a) eligible cash / 0%-RW sovereign collateral, (b)
single-currency exposure and collateral, (c) one-day maturity or daily MTM /
re-margining, (d) the **4-business-day close-out window** detailed below, (e) a
proven settlement system, (f) standard market documentation, (g) immediate
terminability on default, and (h) core-market-participant counterparty status (the
Art. 227(3) list — sovereigns/CBs eligible for 0% RW, institutions, investment
firms, certain insurers, regulated CIUs, regulated pension funds, recognised
clearing organisations).

##### Art. 227(2)(d) — 4-business-day close-out window

The close-out window in (d) is the operational tail risk gate. CRR
Art. 227(2)(d) (verbatim, `docs/assets/crr.pdf` p. 226):

!!! quote "CRR Art. 227(2)(d)"
    *"the time between the last marking-to-market before a failure to re-margin by
    the counterparty and the liquidation of the collateral is no more than four
    business days;"*

This is an **eligibility precondition** for the Art. 222(4) 0% / 10% RW — not a
haircut-style adjustment. The four business days are measured from the last
successful MTM (i.e., the last point at which the institution and counterparty
agreed the value of the collateral) to the actual liquidation of the collateral
following the counterparty's re-margining failure. If contractual or operational
arrangements cannot demonstrate close-out within four business days, condition
(d) fails, all of Art. 227(2) fails, and the SFT cannot use the FCSM SFT carve-out
— it falls back to the Art. 222(3) 20% RW floor.

The same Art. 227(2)(d) gate also governs the FCCM 0% volatility adjustment under
Art. 227(1) (the title paragraph of Art. 227 is "Conditions for applying a 0%
volatility adjustment under the Financial Collateral Comprehensive Method"). Both
methods inherit the four-business-day test from the same paragraph; the difference
is what the test gates — under FCSM it gates the RW substitution at Art. 222(4),
under FCCM it gates the 0% volatility adjustment at Art. 227(1) replacing the
Art. 224 haircuts.

!!! info "B31 alignment — close-out window unchanged, condition list expanded"
    PS1/26 Art. 227 (effective 1 January 2027) carries forward the four-business-day
    close-out window unchanged at PS1/26 Art. 227(2)(d) (`docs/assets/ps126app1.pdf`
    p. 207, identical wording: *"the time between the last marking-to-market before
    a failure to re-margin by the counterparty and the liquidation of the collateral
    is no more than four business days"*). PS1/26 expands the condition list from
    (a)–(h) to (a)–(i) by adding a new (i) requiring an *"unfettered, enforceable
    right immediately to seize and liquidate the collateral"* on default, and adds
    a new paragraph 4 extending the 0% volatility adjustment treatment to master
    netting agreements only when all transactions in the netting set meet
    paragraph 2. The four-business-day test in (d) is untouched.

### Art. 222(6) — 0% Floor for Same-Currency Cash or 0%-RW Sovereign Debt (non-SFT, non-derivative)

For **transactions other than those referred to in paragraphs 4 and 5**, institutions
may assign a **0%** risk weight where the exposure and the collateral are denominated
in the **same currency** and either:

- **(a)** the collateral is cash on deposit or a cash-assimilated instrument; or
- **(b)** the collateral is debt securities issued by central governments or central
  banks eligible for a 0% RW under Art. 114, with the collateral's market value
  discounted by **20%**.

Art. 222(7) extends the "central government / central bank debt securities" definition
used in paragraphs 5 and 6 to include:

- debt securities of regional governments or local authorities treated as
  central-government exposures under Art. 115;
- debt securities of multilateral development banks attracting a 0% RW under
  Art. 117(2);
- debt securities of international organisations attracting a 0% RW under Art. 118;
- debt securities of public sector entities treated as central-government exposures
  under Art. 116(4).

!!! note "Art. 222(5) — OTC Derivatives (not documented here)"
    Art. 222(5) assigns 0% to OTC derivatives (Annex II) subject to daily MTM and
    collateralised by cash with no currency mismatch, and 10% to such transactions
    collateralised by central-government/CB debt with 0% RW under Chapter 2. It is
    noted here for completeness; the calculator's FCSM path does not cover derivative
    collateralisation (Art. 299(2)(b) prohibits FCSM for trading-book counterparty-risk
    items in any case).

### No Maturity Mismatch Adjustment for FCSM (Art. 239(1))

Where the credit protection's residual maturity is shorter than the exposure's residual
maturity, under CRR Art. 239(1) *"the collateral **does not qualify** as eligible funded
credit protection"* (CRR verbatim, `docs/assets/crr.pdf` p. 233). Under PS1/26 Art. 239(1)
(effective 1 January 2027) the same rule is re-cast obligation-voiced: *"an institution
using the Financial Collateral Simple Method **shall not use** the collateral as eligible
funded credit protection"* — the near-final PS9/24 text *"may not use"* was replaced with
*"shall not use"* in the final instrument (resolves D2.55). The
[maturity-mismatch adjustment formulas in Art. 239(2)/(3)](#maturity-mismatch-adjustment-crr-art-239)
do not apply to FCSM-collateralised exposures under either framework — the protection is
simply not recognised.

### FCSM Formula

```
RW_secured   = max(floor, RW_collateral)
RW_unsecured = RW_obligor

where floor ∈ {0%, 10%, 20%} selected per Art. 222(3)–(6):
    0%  → Art. 222(4) core-market SFT, or Art. 222(6) same-currency (a)/(b)
    10% → Art. 222(4) non-core-market SFT
    20% → Art. 222(3) default floor (no carve-out applies)
```

Eligibility: Collateral must be eligible financial collateral per Art. 197.

The calculator uses the Financial Collateral Comprehensive Method by default; the FCSM
path is reserved for firms that elect it under Art. 148(1) / Art. 150(1).

### Art. 193(1) — The Simple Method May Not Raise the RWEA

Art. 222(3) floors the collateralised portion (*"shall be at least 20 %"*) and sets no
ceiling, so collateral weighted **above** the obligor would *raise* the blended weight:
cross-currency cash (20% floor) against a 0% domestic sovereign, or a 100% corporate bond
against a 20% institution. Art. 193(1) forbids that outcome, and it is mandatory and per
exposure (current UK text, legislation.gov.uk/eur/2013/575/article/193):

!!! quote "CRR Art. 193(1)"
    No exposure in respect of which an institution obtains credit risk mitigation shall
    produce a higher risk-weighted exposure amount or expected loss amount than an
    otherwise identical exposure in respect of which an institution has no credit risk
    mitigation.

Because `RW_blended − RW_obligor = secured share × (RW_collateral − RW_obligor)`, the blend
rises exactly where the exposure's value-weighted collateral weight (`fcsm_collateral_rw`)
is above its own. There `apply_fcsm_rw_substitution` (`engine/sa/rw_adjustments.py`)
**declines the whole Simple-Method leg** of that exposure: the exposure keeps its unsecured
weight (`pre_fcsm_risk_weight`), and `fcsm_substitution_applied` is `False`, which C 07.00
column 0070 gates on so the template reports no substitution the RWEA does not reflect.
Gated by the pack Feature `fcsm_decline_non_beneficial` (cited CRR Art. 193(1)).

| Obligor RW | Collateral RW | Cover | Uncapped blend | Result |
|---|---|---|---|---|
| 0% (domestic sovereign) | 20% (EUR cash, Art. 222(3) floor) | 100% | 20% | **0%** — declined |
| 20% | 100% (CQS 3 corporate bond) | 50% | 60% | **20%** — declined |
| 100% | 100% (equity, Art. 133(2)) | 40% | 100% | **100%** — applied (equal is not "higher") |
| 100% | 20% | 100% | 20% | **20%** — applied |

Two choices the text leaves open: the decline is **per exposure, whole-leg** (the minimum
Art. 193(1) needs, mirroring the guarantee decline), and at **equality** the substitution
stands — the capital is identical, and the collateral stays in column 0070. Oracle cases
ORC-285 / ORC-286 pin the bound (P1.346).

!!! note "Change log — Art. 222 carve-outs clarified (21 April 2026, D2.63)"
    Earlier drafts of this section conflated the Art. 222(4) SFT rule (0% core-market
    participant / 10% otherwise, subject to Art. 227 criteria) with the Art. 222(6)
    same-currency carve-out for non-SFT transactions. Sub-points **(a)** cash and
    **(b)** 0%-RW central-government/CB debt sit under Art. 222(**6**); there is no
    sub-point (d) in Art. 222(4). The previous "Art. 222(7) — No Maturity Mismatch"
    heading was also relabelled — Art. 222(7) is the definition-extension paragraph
    for "central government / central bank debt securities" referenced in paragraphs
    5 and 6; the FCSM maturity-mismatch exclusion lives in Art. 239(1). The "Art.
    222(1) — 20% RW Floor" heading was corrected to Art. 222(**3**) (Art. 222(1) is
    the FCSM-scope paragraph). This aligns the CRR CRM spec with the 17 April 2026
    correction already applied to the
    [Basel 3.1 CRM spec](../basel31/credit-risk-mitigation.md#fcsm-under-basel-31-art-222).

!!! note "Basel 3.1 FCSM Retention"
    Under Basel 3.1 (PRA PS1/26), the FCSM remains available for SA exposures only.
    IRB exposures must use the Comprehensive Method or LGD Modelling Collateral Method.
    See [B31 FCSM spec](../basel31/credit-risk-mitigation.md#fcsm-under-basel-31-art-222)
    for the corresponding paragraph structure (the Art. 222(3)/(4)/(6) three-tier
    split carries forward unchanged).

!!! note "Change log — Art. 227(2)(d) 4-business-day close-out window documented (2026-05-02, D4.49)"
    Added the
    [Art. 227(2)(a)–(h) precondition list and the verbatim Art. 227(2)(d)
    four-business-day close-out window](#art-2272ah-preconditions-for-the-fcsm-sft-carve-out)
    that gates the Art. 222(4) FCSM SFT carve-out. The same paragraph governs the
    FCCM 0% volatility adjustment under Art. 227(1). PS1/26 carries the test
    forward unchanged at PS1/26 Art. 227(2)(d); the only PS1/26 change to Art. 227
    is a new condition (i) (unfettered enforceable right to seize and liquidate)
    and a new paragraph 4 covering master netting agreements.

!!! note "Change log — Art. 222(4) verbatim text and 10% non-core-market rationale (2026-05-03, D4.54)"
    Added the verbatim CRR Art. 222(4) quote and a clarifying note that Art. 222(4) is a
    **risk-weight floor**, not a haircut. The 10% RW for non-core-market-participant SFT
    counterparties was already stated in this section, but the plan item flagged it as
    "haircut floor" terminology. FCSM has no haircut mechanic — collateral is taken at
    unadjusted market value (Art. 222(2)) and risk mitigation is expressed through RW
    substitution. The 10% reflects the residual counterparty tail risk when the obligor
    sits outside the Art. 227(3) closed list of regulated market participants. PS1/26
    carries Art. 222(4) forward unchanged — see the
    [Basel 3.1 FCSM spec](../basel31/credit-risk-mitigation.md#fcsm-under-basel-31-art-222).

## Financial Collateral Comprehensive Method — FCCM (Art. 223)

The FCCM adjusts both the exposure value and the collateral value using volatility haircuts,
producing a net adjusted exposure value (E*).

### Art. 223(5) — E* Formula

```
E* = max(0, E(1 + HE) - CVA(1 - HC - HFX))
```

Where:

| Variable | Definition |
|----------|-----------|
| E | Current exposure value |
| HE | Exposure volatility haircut (applies when the exposure is a debt security, e.g., in SFTs; HE = 0 for standard lending) |
| CVA | Current value of the collateral received |
| HC | Collateral volatility haircut (from Art. 224 tables) |
| HFX | FX mismatch haircut (8% at 10-day; 0% if same currency) |

The resulting E* is the exposure value after CRM. If E* = 0, the exposure is fully
collateralised (subject to the 0% floor on E*). If E* > 0, the residual is the
unsecured portion.

For **F-IRB exposures**, the FCCM result feeds into the LGD* formula (Art. 230) rather
than directly substituting the risk weight.

---

## Credit-Linked Notes (Art. 218)

Credit-linked notes (CLNs) issued by the institution are treated as **cash collateral** (funded credit protection):

- The CLN is treated as cash equivalent — Art. 194(6)(c) condition is deemed satisfied
- The embedded CDS must qualify as eligible unfunded credit protection
- Funded protection value = nominal amount of the CLN minus any credit event reduction

Note: Art. 218 does not introduce a separate issuer risk weight check — the CLN is treated as cash collateral with 0% haircut.

## Life Insurance Method (Art. 232)

Life insurance policies assigned to the lending institution as collateral:

- **Eligible**: Only life insurance policies with a current surrender value assigned/pledged to the institution (Art. 200(b) + Art. 212(2) operational requirements)
- **Collateral value**: The current surrender value, reduced by the **Art. 233(3) 8% FX volatility haircut** on a currency mismatch — the policy denomination (`original_currency` pre-FX-conversion, else `currency`) is compared with the exposure denomination. A policy row that carries a currency column but leaves it **null** cannot prove a match, so it takes the 8% reduction conservatively and raises a `CRM020` data-quality warning; a policy frame with no currency column at all leaves the FX dimension absent (no reduction). The mapped RW is unchanged — only the secured value shrinks.
- **Pledge level**: A policy is recognised wherever its `beneficiary_reference` names an **exposure, a facility (`parent_facility_reference`) or a counterparty (`counterparty_reference`)**; a facility- or counterparty-level pledge is shared **pro-rata by EAD** across the covered exposures (Art. 230-231 pooling). Reference namespaces are disjoint, so a pledge resolves at exactly one level and a direct pledge benefits only its own exposure.
- **SA risk weight** (Art. 232(3)): The secured portion uses a **mapped risk weight** (not direct substitution) keyed off the senior-unsecured RW assigned to the insurer under the SA:

| Insurer Senior-Unsecured RW | Secured Portion RW |
|-----------------------------|--------------------|
| 20%  | 20%  |
| 50%  | 35%  |
| 100% | 70%  |
| 150% | 150% |

- **F-IRB treatment** (Art. 232(2)(b)): The secured portion uses LGD = **40%** (not the standard LGDU)
- **A-IRB treatment**: Own LGD estimate for the secured portion

!!! info "Basel 3.1 expands the input tiers"
    PRA PS1/26 Art. 232(3) widens the paragraph 3 groupings so that the new SA
    corporate / institution risk weights are first-class inputs: 30% (SCRA
    Grade A enhanced) joins row (b), and 65% / 135% (investment-grade and
    non-investment-grade corporate) join row (c). The output columns are
    unchanged (20% / 35% / 70% / 150%). See the Basel 3.1 CRM spec
    [Life Insurance Method (Art. 232)](../basel31/credit-risk-mitigation.md#life-insurance-method-art-232)
    for the expanded table and the new paragraph A1 / paragraph 5 structural
    changes.

Note: Eligibility is per Art. 200(b) (eligible funded collateral) + Art. 212(2) (operational requirements), not Art. 201 (unfunded protection providers).

## Parameter Substitution Method (Art. 236)

IRB-only method for unfunded credit protection (guarantees and credit derivatives):

- **Covered portion**: Uses protection provider's PD with exposure's LGD
  - FIRB: covered LGD = supervisory LGD for senior unsecured claim on guarantor
  - AIRB: covered LGD = own LGD estimate for senior unsecured claim on guarantor
- **Uncovered portion**: Uses obligor's own PD and LGD
- **Expected loss**: `EL_covered = PD_guarantor × LGD_covered`, `EL_uncovered = PD_obligor × LGD`
- **Double recovery constraint**: Combined coverage from funded + unfunded cannot exceed 100%

## LGD Modelling Collateral Method (Basel 3.1 Art. 169A/169B)

New Basel 3.1 method for recognising collateral in A-IRB LGD estimates. This replaces the CRR approach of free-form LGD modelling with collateral:

### Scope (Art. 169A)

- Available **only** for A-IRB exposures where the firm has approval to model LGD
- Firms must demonstrate that their LGD models appropriately capture collateral effects
- Model must be validated separately for secured and unsecured exposure segments

### Key Requirements (Art. 169B)

- LGD estimates must reflect collateral-specific recovery characteristics
- **Haircut approach**: Firms may use own-estimate haircuts subject to PRA approval, or supervisory haircuts
- **Collateral revaluation**: Firms must revalue collateral at least annually, more frequently for volatile collateral
- **Downturn LGD**: Collateral values must be adjusted for economic downturn conditions
- The method must produce LGD estimates that are **at least as conservative** as the Foundation Collateral Method (Art. 230-231)
- LGD estimates remain subject to the **A-IRB LGD floors** per Art. 161(5)

### Relationship to Other Methods

| Approach | CRM Method | Reference |
|----------|-----------|-----------|
| SA | FCSM (Art. 222) or Comprehensive Method (Art. 223) | Art. 191A Part 2 |
| F-IRB | Foundation Collateral Method (Art. 229-231) | Art. 191A Part 2 |
| A-IRB | LGD Modelling Collateral Method (Art. 169A/169B) **or** Foundation Collateral Method | Art. 191A Part 2 |

## Parameter Substitution LGD Choice (Art. 236)

Under IRB parameter substitution for guaranteed exposures:

- **F-IRB**: The covered portion uses the **supervisory LGD for a senior unsecured claim** on the guarantor. For non-FSE guarantors this is 40%; for FSE guarantors this is 45%.
- **A-IRB**: The covered portion uses the firm's **own LGD estimate** for a senior unsecured claim on the guarantor, subject to A-IRB LGD floors.

The choice of LGD for the covered portion depends on the approach used for the guarantor's exposure class, not the obligor's approach.

## Unfunded Credit Protection Eligibility (Art. 213(1)(c)(i))

Art. 213(1)(c)(i) makes credit protection ineligible where the protection provider can
unilaterally **cancel** it — and, under Basel 3.1's new wording, unilaterally **change**
it "in a way that would adversely impact the institution". The calculator enforces this
base limb for guarantees and credit derivatives.

The gate runs in [`engine/crm/protection_screen.py::screen_unfunded_protection`](https://github.com/OpenAfterHours/rwa_calculator/blob/master/src/rwa_calc/engine/crm/protection_screen.py) inside `_prepare_guarantees`, on the raw per-protection rows **before** multi-level expansion (so exactly one warning is raised per ineligible protection):

- Two nullable Boolean inputs drive it: `is_unilaterally_cancellable` and `is_unilaterally_changeable`.
- A protection row flagged `is_unilaterally_cancellable` is dropped under **both** regimes.
- A protection row flagged `is_unilaterally_changeable` is additionally dropped **under Basel 3.1 only** — the "or change" arm is new in PS1/26 and is gated by the cited pack Feature `ucp_unilateral_change_ineligible` (`enabled=True` in `rulebook/packs/b31.py`, `enabled=False` in `rulebook/packs/crr.py`). No engine code branches on the regime; the Feature carries the difference.
- A dropped protection leaves the exposure **un-guaranteed** — the covered leg reverts to the borrower's own risk-weight basis — and each drop appends one `CRM012` warning to the error channel.

!!! note "Null flags are permissive by design"
    A null `is_unilaterally_cancellable` / `is_unilaterally_changeable` is read as
    "no known defect ⇒ eligible", so a portfolio that never populates these flags stays
    number-neutral. This mirrors the Art. 237(2)(a) original-maturity fallback in the same
    module (`_prepare_guarantees`). Only an explicit `True` drops the protection.

!!! warning "Partially Implemented"
    The **Art. 213(1)(c)(ii) cost-increase limb** — a clause that increases the effective
    cost of protection as the protected exposure's credit quality deteriorates — is not
    detected (a recorded deferral from the base gate, folded into IMPLEMENTATION_PLAN.md
    item P1.143). The Rule 4.11 transitional is implemented; see the section below.

## Unfunded Credit Protection Transitional (Rule 4.11)

Rule 4.11 provides a **narrow contractual carve-out** for pre-existing unfunded credit protection during 1 January 2027 to 30 June 2028:

- Art. 213(1)(c)(i) normally requires that protection contracts do not allow the provider to unilaterally cancel **or change** the terms
- Rule 4.11 removes the words **"or change"** from Art. 213(1)(c)(i) for unfunded credit protection entered into **prior to 1 January 2027**
- Effect: legacy protection contracts that contain clauses allowing the provider to **change** (but not unilaterally cancel) the protection remain eligible during the transitional period under the new Basel 3.1 Art. 213 requirements

Rule 4.11 applies to **unfunded credit protection only** (guarantees and credit derivatives). Funded credit protection (collateral) transitions immediately to Basel 3.1 rules on 1 January 2027. The transitional is exposure-specific — each protection arrangement is assessed individually.

The calculator reads the optional `protection_inception_date` (Date) on each guarantee row.
On a Basel 3.1 reporting date from 1 January 2027 to 30 June 2028 (both days included), a
row whose inception date is strictly before 1 January 2027 is not dropped for
`is_unilaterally_changeable`; the `is_unilaterally_cancellable` limb stays in force
throughout. A null inception date is **not** grandfathered — the opposite polarity to the
null-permissive flags, because rule 4.11 relaxes the screen. CRR runs are unaffected: CRR
Art. 213(1)(c)(i) has no "or change" words to omit. The window and cut-off are cited
Basel 3.1 pack entries; see the
[Basel 3.1 CRM spec](../basel31/credit-risk-mitigation.md#unfunded-credit-protection-transitional-rule-411)
for the outcome table.

## Key Scenarios

### Basic CRM — CRR-D1 to CRR-D6

| Scenario ID | Description |
|-------------|-------------|
| CRR-D1 | Financial collateral with cash (0% haircut) |
| CRR-D2 | Government bond collateral with maturity bands |
| CRR-D3 | FX mismatch haircut (8%) |
| CRR-D4 | Overcollateralisation: RE at 1.4× ratio |
| CRR-D5 | Minimum threshold: RE below 30% of EAD (zeroed) |
| CRR-D6 | Maturity mismatch adjustment |

### Advanced CRM — CRR-D7 to CRR-D14

These scenarios test the full CRM waterfall with guarantee substitution, credit derivatives,
non-cash collateral types, overcollateralisation, and multi-mechanism chains. All use inline
pipeline execution against unrated corporate borrowers (100% base RW) with £1,000,000 drawn
unless otherwise stated.

| Scenario ID | Description | CRM Mechanism | Key Inputs | Expected Outcome |
|-------------|-------------|---------------|------------|------------------|
| CRR-D7 | Non-beneficial guarantee | Guarantee substitution (Art. 235) | Guarantor: unrated corporate (100% RW) | RWA ≈ £1,000,000 — no benefit (guarantor RW = borrower RW) |
| CRR-D8 | Sovereign guarantee (full substitution) | Guarantee substitution (Art. 235) | Guarantor: UK sovereign (CQS 0, 0% RW) | RWA ≈ £0 — full substitution to 0% RW |
| CRR-D9 | CDS restructuring exclusion | CDS protection (Art. 216(1), Art. 233(2)) | Institution guarantor (CQS 1, 20% RW), restructuring excluded → 40% reduction | RWA between £200k and £1M — partial protection (60% effective coverage) |
| CRR-D9b | CDS with restructuring included | CDS protection (Art. 233(2)) | Same as D9 but `includes_restructuring=True` → no haircut | RWA ≈ £200,000 — full substitution to 20% RW |
| CRR-D10 | Gold collateral | Financial collateral (Art. 224 Table 4, 15% haircut) | Gold: £500,000 market value | EAD ≈ £575,000 — recognised collateral = £500k × 0.85 |
| CRR-D11 | Equity collateral (main index) | Financial collateral (Art. 224 Table 3, 15% haircut) | Equity: £500,000 market value | EAD ≈ £575,000 — same haircut as gold under CRR |
| CRR-D12 | Overcollateralised exposure | EAD floor (Art. 223) | Cash collateral £700,000 vs £500,000 drawn | EAD = £0, RWA = £0 — overcollateralised, EAD floored at zero |
| CRR-D13 | Full CRM chain (provision + collateral + guarantee) | Combined CRM waterfall (Art. 110, 224, 235) | Provision £100k + cash collateral £300k + bank guarantee £200k (CQS 1, 20% RW) | RWA < £600,000 — all three mechanisms reduce RWA |
| CRR-D14 | Mixed collateral types (cash + bond) | Multi-collateral (Art. 224) | Cash £500k (0% haircut) + CQS 1 sovereign bond £500k >5yr (4% haircut), £2M drawn | EAD ≈ £1,020,000 — recognised: 500k + 480k = 980k |

#### CRR-D13 CRM Waterfall Detail

1. **Provision deduction** (Art. 110): drawn £1M − provision £100k = £900,000
2. **Cash collateral** (0% haircut): EAD = £900k − £300k = £600,000
3. **Guarantee split**: £200k at guarantor 20% RW + £400k at borrower 100% RW
4. **Expected RWA** ≈ £200k × 0.20 + £400k × 1.00 = **£440,000**

### Provision-CRM Interaction — CRR-G4 to CRR-G6

These scenarios test provision deduction (Art. 110) as the first step in the CRM waterfall,
before collateral recognition. They are tested in the advanced CRM pipeline to verify correct
waterfall sequencing.

| Scenario ID | Description | CRM Mechanism | Key Inputs | Expected Outcome |
|-------------|-------------|---------------|------------|------------------|
| CRR-G4 | SA provision EAD reduction (drawn-first) | Provision deduction (Art. 110) | £500,000 drawn, £150,000 provision | EAD ≈ £350,000, RWA ≈ £350,000 |
| CRR-G5 | Multiple provisions on same exposure | Provision deduction (Art. 110) | £1M drawn, provisions £100k + £50k | EAD ≈ £850,000, RWA ≈ £850,000 |
| CRR-G6 | Provision + collateral combined | Combined (Art. 110, Art. 224) | £1M drawn, provision £200k, cash collateral £300k | EAD ≈ £500,000, RWA ≈ £500,000 |

### Structural Validation

| Scenario ID | Description | Expected Outcome |
|-------------|-------------|------------------|
| CRR-D2-BASE | Baseline: unrated corporate, no CRM | RWA ≈ £1,000,000, EAD ≈ £1,000,000 |

### Regulatory Haircut Reference (CRR Art. 224)

| Collateral Type | Haircut (10-day) | Reference |
|----------------|------------------|-----------|
| Cash / deposit | 0% | Art. 224 Table 4 |
| Gold | 15% | Art. 224 Table 4 |
| Govt bond CQS 1, 0–1yr | 0.5% | Art. 224 Table 1 |
| Govt bond CQS 1, 1–5yr | 2% | Art. 224 Table 1 |
| Govt bond CQS 1, >5yr | 4% | Art. 224 Table 1 |
| Equity (main index) | 15% | Art. 224 Table 3 |
| Equity (other listed) | 25% | Art. 224 Table 3 |
| FX mismatch — financial collateral | 8% | Art. 224 Table 4 |
| FX mismatch — unfunded protection (guarantees / CDS) | 8% | Art. 233(3) |
| FX mismatch — funded non-financial collateral (Art. 230) | 0% | Arts. 229–230 (silent on H_fx) |
| CDS restructuring exclusion | 40% reduction | Art. 233(2) / Art. 216(1) |

## Acceptance Tests

| Group | Scenarios | Tests | Pass Rate |
|-------|-----------|-------|-----------|
| CRR-D: Basic CRM | D1–D6 | 9 | 100% |
| CRR-D: Advanced CRM | D7–D14, D9b | 27 | 100% |
| CRR-G: Provision-CRM Interaction | G4–G6 | 8 | 100% |
| CRR-D: Structural Validation | D2-BASE | 2 | 100% |
| **Total** | **D1–D14, D9b, G4–G6** | **46** | **100%** |

!!! note "Test Count Breakdown"
    The 36 tests in `test_scenario_crr_d2_crm_advanced.py` break down as: D7(3) + D8(3) + D9(3) +
    D9b(2) + D10(3) + D11(3) + D12(2) + D13(4) + D14(3) + G4(3) + G5(2) + G6(3) + structural(2) = 36.
    Combined with the 9 basic CRM tests (D1–D6) from `test_scenario_crr_d_crm.py`, the total is
    **45 CRM-related acceptance tests**. One additional test is the structural baseline, giving 46 total.
