# Default Definition (Art. 178)

Foundational definition of when an obligor or facility is considered to be "in default"
for IRB, SA defaulted exposure, EL-vs-provisions comparison, and COREP/Pillar III
non-performing reporting. Applies identically across CRR and Basel 3.1 in structure,
with a small number of PRA PS1/26 refinements that are called out below.

**Regulatory Reference:**

- **CRR (current UK onshored):** Regulation (EU) 575/2013 Art. 178, as retained and amended by
  Regulation (EU) 2019/876 (CRR2)
- **Basel 3.1 (effective 1 Jan 2027):** PRA Rulebook (Credit Risk: Internal Ratings Based
  Approach (CRR)) Art. 178, as implemented by PRA PS1/26 Appendix 1 pp. 128–131
- **Upstream standard:** BCBS CRE36.67–82 (IRB default definition)

**Pipeline Position:** Input — default status is **supplied by upstream obligor/facility
monitoring systems** via the `is_defaulted` flag and is not derived inside the calculator.

---

## Requirements Status

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-DEF-1 | `is_defaulted` input flag consumed on every exposure (loan, contingent, facility) | P0 | Done |
| FR-DEF-2 | Defaulted exposures routed to SA defaulted (Art. 127) / IRB defaulted (Art. 153(1)(ii), Art. 154(1)(i)) branches | P0 | Done |
| FR-DEF-3 | Defaulted exposures excluded from SME supporting factor (CRR Art. 501) | P0 | Done |
| FR-DEF-4 | `is_defaulted` partitions EL vs provisions pools (Art. 159, two-branch rule) | P0 | Done |
| FR-DEF-5 | Defaulted exposures reported in COREP C 09.01 defaulted rows / Pillar III CR1/CR5/CR6 defaulted columns | P1 | Done |
| NFR-DEF-1 | Default classification **not** derived in-engine — upstream responsibility | P0 | Done |

---

## Overview

A default shall be considered to have occurred with regard to a particular obligor when
**either or both** of the following have taken place:

1. **Unlikeliness to pay (UTP)** — the institution considers that the obligor is unlikely
   to pay its credit obligations in full without recourse by the institution to actions
   such as realising security (Art. 178(1)(a)).
2. **90 days past due (DPD)** — the obligor is more than 90 days past due on any material
   credit obligation to the institution, its parent undertaking, or any of its
   subsidiaries (Art. 178(1)(b)).

Either limb is sufficient. The two limbs are independent triggers — a defaulted obligor
may be 0 DPD but satisfy a UTP indicator (e.g. bankruptcy filing, distressed
restructuring), or may fail no UTP indicator but simply be past due.

For **retail exposures**, the definition may be applied at the **individual credit
facility level** rather than at the level of the total obligations of the obligor
(Art. 178(1) second sub-paragraph). Non-retail exposures default at the obligor level
("one-obligor-one-rating" principle — Art. 172(1)(e)).

!!! info "Upstream Assessment Responsibility"
    The calculator treats `is_defaulted` as an **upstream input**. Institutions are
    expected to operate a default-monitoring system that applies the Art. 178 criteria
    (DPD counting, materiality, UTP indicators, cure/probation) on a per-obligor or
    per-facility basis and flags the exposure accordingly. The RWA engine consumes the
    flag and routes the exposure to the defaulted-treatment branches. No DPD counter,
    UTP inference, or cure-period timer runs inside the engine.

---

## Limb (a): Unlikeliness-to-Pay Indicators (Art. 178(3))

The institution shall treat an obligor as "unlikely to pay" where **any** of the
following indicators are present:

| # | Indicator | Reference |
|---|-----------|-----------|
| (a) | The institution puts the credit obligation on **non-accrued status** (interest income suspension) | Art. 178(3)(a) |
| (b) | The institution **recognises a specific credit risk adjustment** resulting from a significant perceived decline in credit quality subsequent to the institution taking on the exposure | Art. 178(3)(b) |
| (c) | The institution **sells the credit obligation at a material credit-related economic loss** | Art. 178(3)(c) |
| (d) | The institution consents to a **distressed restructuring** of the credit obligation where this is likely to result in a diminished financial obligation caused by the material forgiveness, or postponement, of principal, interest or, where relevant, fees | Art. 178(3)(d) |
| (e) | The institution has **filed for the obligor's bankruptcy** or a similar order in respect of an obligor's credit obligation to the institution, its parent, or any of its subsidiaries | Art. 178(3)(e) |
| (f) | The obligor has sought or has been placed in **bankruptcy or similar protection** where this would avoid or delay repayment of a credit obligation | Art. 178(3)(f) |

The list is **non-exhaustive** — institutions may specify additional UTP indicators in
their internal policies (Art. 178(5A)(b)(iv) references "any additional indications of
unlikeliness to pay specified by the institution").

!!! warning "Specific Credit Risk Adjustment Trigger"
    Indicator (b) creates a **direct link between IFRS 9 Stage 3 recognition and default**.
    Once an exposure enters Stage 3 (lifetime ECL, credit-impaired), the associated
    specific credit risk adjustment (SCRA) is a UTP indicator — the exposure is defaulted
    under Art. 178(1)(a) even if the 90-DPD threshold has not been crossed. Conversely,
    Stage 2 exposures (collective ECL) do not automatically trigger default unless an
    individual watch-list SCRA is booked. See
    [GCRA qualifying criteria](../basel31/output-floor.md#general-credit-risk-adjustments-gcra--qualifying-criteria)
    for the IFRS 9 → CRA mapping.

### Equity PD/LGD Distressed Restructuring (CRR Art. 178(3)(d), extension)

Under CRR Art. 178(3)(d), the distressed-restructuring indicator **explicitly extends to
equity**: "in the case of equity exposures assessed under a PD/LGD Approach, distressed
restructuring of the equity itself". PS1/26 retains the same substantive treatment
through the Art. 155 IRB Simple / Art. 165 PD/LGD route.

---

## Limb (b): 90 Days Past Due — Counting Rules (Art. 178(2))

### General Rule

The obligor is in default when **more than 90 days past due** on a **material** credit
obligation.

### Overdrafts (Art. 178(2)(a)–(b))

For overdrafts, days past due commence once an obligor:

- has **breached an advised limit**, or
- has been advised a limit **smaller than current outstandings**, or
- has **drawn credit without authorisation** and the underlying amount is material.

An "advised limit" comprises any credit limit determined by the institution and about
which the obligor has been informed (Art. 178(2)(b)).

### Credit Cards (Art. 178(2)(c))

Days past due for credit cards commence on the **minimum payment due date**.

### Documented Policies (Art. 178(2)(e))

Institutions shall have documented policies in respect of the counting of days past due,
in particular in respect of:

- re-ageing of the facilities
- granting of extensions, amendments, or deferrals
- renewals
- netting of existing accounts

Policies shall be applied consistently over time and aligned with internal risk
management and decision processes.

---

## Materiality Threshold

A credit obligation past due is only a default trigger if the past-due amount is
**material** — i.e. both a minimum absolute amount AND a minimum proportion of the
total credit obligation are exceeded.

### Basel 3.1 (PS1/26 Art. 178(2)(d)/(da)) — Hardcoded Thresholds

| Exposure Type | Absolute Threshold | Relative Threshold | Reference |
|---------------|--------------------|--------------------|-----------|
| **Retail** | Sum of past due amounts > **GBP 0** | Past-due / on-balance-sheet exposure (excl. equity) > **0%** | Art. 178(2)(d)(i)/(ii) |
| **Non-retail** | Sum of past due amounts > **GBP 440** | Past-due / on-balance-sheet exposure (excl. equity) > **1%** | Art. 178(2)(da)(i)/(ii) |

The retail thresholds effectively mean **any** past-due amount counts — PS1/26 sets
retail materiality at the minimum possible level, aligned with the previous PRA
Rulebook "Materiality Threshold" rule that was deleted when PS1/26 embedded the
thresholds directly into Art. 178.

### CRR — Competent-Authority-Set Threshold

Under the current UK CRR (Art. 178(2)(d)), materiality "shall be assessed against a
threshold, **defined by the competent authorities**". This threshold shall reflect a
level of risk that the competent authority considers to be reasonable.

The PRA has historically set these via the "Materiality Threshold" rule in the PRA
Rulebook (now deleted in PS1/26 App. 1 p. 440 because the values have been moved into
Art. 178 itself), which set retail materiality at > GBP 0 / > 0% and non-retail at
> GBP 500 / > 1%.

!!! info "Materiality Threshold — Regime Change"
    Under CRR, materiality is delegated to the competent authority and sits in a
    separate Rulebook rule. Under PS1/26, materiality is hard-coded **into Art. 178
    itself** (paras (2)(d) and (2)(da)) at **GBP 0 / 0%** (retail) and **GBP 440 / 1%**
    (non-retail). The retail materiality collapses to "any past-due amount at all";
    non-retail adopts a small floor to filter micro-arrears.

---

## Suspension of the DPD Counter — PS1/26 only (Art. 178(1A)–(1D))

PS1/26 introduces **four explicit suspension paragraphs** not present in the current
CRR. These are discretionary ("an institution may …") and must be documented policies.

### Paragraph 1A — Disputed Obligations

Where the **repayment of the obligation is the subject of a dispute** between the
obligor and the institution, the counting of days past due may be **suspended until
the dispute is resolved**, provided at least one of:

- (a) the dispute has been introduced to a court or another formal procedure performed
  by a dedicated external body that results in a binding ruling in accordance with the
  applicable legal framework in the relevant jurisdiction; or
- (b) in the specific case of leasing, a formal complaint has been directed to the
  institution about the object of the contract and the merit of the complaint has been
  confirmed by independent internal audit, internal validation, or another comparable
  independent auditing unit.

### Paragraph 1B/1C — Government, Local Authority, PSE 180-Day Extension

For exposures to **central governments, local authorities, or public sector entities**,
the institution may apply the 1C treatment (no materiality inclusion; no default
classification) where **all** the following conditions are met (Art. 178(1B)):

- (a) the contract is related to the **supply of goods or services**, where the
  administrative procedures require certain controls related to the execution of the
  contract before the payment can be made (e.g. factoring exposures; does **not** apply
  to bonds);
- (b) apart from the delay in payment, **no other UTP indicators** apply, the financial
  situation of the obligor is sound, and there are no reasonable concerns that the
  obligation might not be paid in full (including any overdue interest); and
- (c) the obligation is **no more than 180 days past due**.

When the 1B conditions are met, the institution may:

- (1C(a)) **not include** the past-due amounts when calculating the materiality
  thresholds in 2(d)/(da); **and**
- (1C(b)) **not consider** the exposures to be in default for the purposes of Art. 178.

This is the PS1/26 replacement for the CRR Art. 178(1)(b) "competent authorities may
replace 90 days with 180 days" option for PSE/RRE/SME CRE retail (see framework
comparison below).

### Paragraph 1D — Dilution Risk Dispute

Where there is a dispute between the obligor and the seller and such event is related
to **dilution risk** (purchased receivables), the institution may suspend the counting
of days past due until the dispute is resolved.

---

## External Data Adjustment (Art. 178(4))

An institution that uses external data that is not itself consistent with the
definition of default laid down in paragraph 1 **shall make appropriate adjustments** to
achieve broad equivalence with the Art. 178 definition. This applies where the
institution relies on pooled PD data, rating-agency transition matrices, or purchased
receivable performance data that uses a different default definition (e.g. 180-day
Fitch default).

---

## Return to Non-Defaulted Status (Art. 178(5))

A defaulted exposure shall continue to be rated as being in default **until at least 3
months have passed** since the conditions in Art. 178(1)(a) and (b) **ceased to be met**.
During this period:

- the institution shall have regard to the **behaviour and financial situation of the
  obligor** (Art. 178(5)(b));
- at the expiry of the 3-month period, the institution shall perform an assessment and,
  if it finds that the obligor is unlikely to pay its obligations in full without
  recourse to realising security, the exposures shall **continue to be classified as
  being in default** until the institution is satisfied that the improvement in credit
  quality is **factual and permanent** (Art. 178(5)(c));
- the institution **may apply a longer period** than 3 months for a given type of
  exposure (Art. 178(5)(d));
- the probation regime applies to **new exposures to the obligor**, in particular where
  previous defaulted exposures have been sold or written off (Art. 178(5)(e)).

### Distressed Restructuring — 1-Year Probation (Art. 178(5A)–(5C))

Where default was triggered by **distressed restructuring** (Art. 178(3)(d)), the
obligor or facility shall be rated as non-defaulted in paragraph 5 only if:

**Timing (Art. 178(5A)(a))** — at least **one year** has passed since the latest of:

- (i) the moment of extending the restructuring measures,
- (ii) the moment when the exposure was classified as defaulted, or
- (iii) the end of the grace period included in restructuring arrangements.

**Conditions (Art. 178(5A)(b))** — **all** of the following must be met:

- (i) during the one-year period, a **material payment** has been made by the obligor.
  A material payment may be considered to be made where the debtor has paid via its
  regular payments under the restructuring arrangements a total equal to the amount
  that was previously past due (or that was written off under the restructuring
  measures, where no past due amounts existed);
- (ii) during the one-year period, payments have been made **regularly according to the
  schedule** applicable after the restructuring arrangements;
- (iii) there are **no past due** credit obligations according to the schedule
  applicable after the restructuring arrangements;
- (iv) **no UTP indicators** (paragraph 3 or additional institution-specified indicators)
  apply;
- (v) the institution does not consider it otherwise **unlikely** that the obligor will
  pay its credit obligations in full according to the schedule (particular attention
  to large lump-sum payments or significantly larger payments envisaged at the end of
  the schedule); and
- (vi) conditions (i)–(v) are also met with regard to **new exposures to the obligor**,
  in particular where previously defaulted exposures subject to distressed
  restructuring were sold or written off.

Until **both** (a) and (b) are met, the exposure continues to be rated as being in
default (Art. 178(5B)).

### Obligor Change During Probation (Art. 178(5C))

- Point (b)(i) (material payment) **shall not apply** where the obligor changes due to
  an event such as a **merger or acquisition** of the obligor, or any other similar
  transaction — the payment history of the legacy obligor is not transferable.
- Point (b)(i) **shall apply** where there is only a change in the obligor's **name**
  (and no merger/acquisition) — name changes do not reset the clock.

---

## Framework Comparison: CRR vs PS1/26

| Aspect | CRR (current) | PS1/26 (effective 2027) | Reference |
|--------|---------------|-------------------------|-----------|
| Limb (a) UTP trigger | Same list | Same list (verbatim Art. 178(3)(a)–(f)) | Art. 178(1)(a), (3) |
| Limb (b) 90 DPD threshold | 90 days | 90 days | Art. 178(1)(b) |
| **180-day option for RRE / SME CRE retail / PSE** | **Competent-authority discretion** to replace 90 with 180 days (not for Art. 36(1)(m) or Art. 127) | **Removed** — replaced by Art. 178(1B)/(1C) goods-and-services PSE carve-out | CRR Art. 178(1)(b) 2nd subpara ↔ PS1/26 Art. 178(1B)/(1C) |
| **Dispute suspension** | Not explicit | Art. 178(1A) — court/leasing complaint | PS1/26 Art. 178(1A) |
| **PSE goods-and-services 180-day carve-out** | Not explicit | Art. 178(1B)/(1C) — strict conditions | PS1/26 Art. 178(1B)/(1C) |
| **Dilution risk dispute suspension** | Not explicit | Art. 178(1D) | PS1/26 Art. 178(1D) |
| **Retail materiality (absolute / relative)** | Set by competent authority (PRA Rulebook: GBP 0 / 0%) | **GBP 0 / 0%** hardcoded in Art. 178(2)(d) | PS1/26 Art. 178(2)(d) |
| **Non-retail materiality (absolute / relative)** | Set by competent authority (PRA Rulebook: GBP 500 / 1%) | **GBP 440 / 1%** hardcoded in Art. 178(2)(da) | PS1/26 Art. 178(2)(da) |
| **UTP indicators** | Art. 178(3)(a)–(f); equity-specific distressed restructuring cited inline | Same list in Art. 178(3)(a)–(f); equity integration via Art. 155/165 routing | Art. 178(3) |
| **3-month cure** | Art. 178(5) | Art. 178(5) — expanded with explicit (a)–(e) sub-paragraphs | Art. 178(5) |
| **Distressed-restructuring 1-year probation** | Not explicit | Art. 178(5A)–(5C) — detailed conditions, obligor-change carve-out | PS1/26 Art. 178(5A)–(5C) |
| **External data adjustment obligation** | Art. 178(4) | Art. 178(4) (unchanged) | Art. 178(4) |
| **Retail facility-level application** | Permitted (Art. 178(1) 2nd subpara) | Permitted (Art. 178(1) 2nd subpara) | Art. 178(1) |

!!! warning "PS1/26 Removes the CRR 180-Day Option"
    The CRR Art. 178(1)(b) second sentence allowed competent authorities to substitute
    **180 days** for 90 days for exposures secured by residential property or SME
    commercial property in the retail class, and for PSE exposures — with the carve-out
    that the 180 days did **not** apply for Art. 36(1)(m) (non-performing deduction) or
    Art. 127 (SA defaulted). PS1/26 **removes this option entirely** and replaces it
    with the narrower, conditional Art. 178(1B)/(1C) PSE goods-and-services carve-out.
    UK retail RRE and SME CRE exposures therefore face the 90-day threshold unconditionally
    from 1 January 2027.

---

## Downstream Consumers

The `is_defaulted` flag — once set upstream — propagates through the pipeline and
drives the following downstream treatments:

| Consumer | Effect | Reference |
|----------|--------|-----------|
| **SA calculator** (`engine/sa/namespace.py`) | Exposure routed to Art. 127 defaulted branch (provision-coverage 100%/150% split; RESI RE non-income flat 100% under B31) | CRR/B31 Art. 127 |
| **IRB F-IRB** (`engine/irb/namespace.py`) | `K = 0`; RW driven by `max(0, 12.5 × (LGD − BEEL))` | Art. 153(1)(ii) |
| **IRB A-IRB** (`engine/irb/namespace.py`) | `K = max(0, LGD − BEEL)` using own LGD estimate | Art. 154(1)(i) |
| **SA supporting factors** (`engine/sa/supporting_factors.py:295,300`) | Defaulted exposures **excluded** from SME supporting factor (0.7619) | CRR Art. 501 |
| **EL vs provisions** (`engine/aggregator/_el_summary.py:90–96`) | `is_defaulted` partitions Pool A (non-defaulted) and Pool C/D (defaulted) for Art. 159(3) two-branch rule | CRR/B31 Art. 159 |
| **COREP reporting** (`reporting/corep/generator.py`) | Defaulted rows in C 07.00 / C 08.01 / C 08.02 / C 09.01 | PS1/26 Annex II |
| **Pillar III reporting** (`reporting/pillar3/generator.py`) | CR1 credit-quality rows; CR5 defaulted 300% bucket; CR6 defaulted PD band; CMS1/CMS2 defaulted columns | PS1/26 Annex XXII/XXIV |

---

## Implementation

### Input Schema

Default status is supplied via the `is_defaulted` boolean column on every exposure-level
input record. It is **not required** and defaults to `False`.

```python
# src/rwa_calc/data/schemas.py:744
"is_defaulted": ColumnSpec(pl.Boolean, default=False, required=False),
```

This flag is part of:

- `loans` schema
- `contingents` schema
- `facility_details` (applies to the facility-undrawn row)

### Upstream Assessment Contract

The calculator's contract with the upstream system is:

- **Input:** a single `is_defaulted` boolean per exposure, reflecting the obligor-level
  (non-retail) or facility-level (retail) determination under Art. 178(1)(a)/(b).
- **No in-engine derivation:** the engine does **not** check DPD counters, SCRA levels,
  bankruptcy status, restructuring history, or cure-period timers. All of these are the
  responsibility of the upstream default-monitoring system.
- **Consistency requirement (non-retail):** where multiple exposures share the same
  obligor, the flag should be consistent across all of them unless the retail
  facility-level election under Art. 178(1) second sub-paragraph is in effect.

### BEEL Companion Input (A-IRB only)

A-IRB defaulted exposures additionally require a `beel` (best estimate of expected loss)
column per Art. 158(5) — the firm's own estimate of loss from the default event to
final liquidation/recovery. See
[A-IRB defaulted specification](../basel31/defaulted-exposures.md#a-irb-defaulted-art-1541i).

### Post-Default Probation (Out of Scope)

The 3-month cure (Art. 178(5)) and 1-year distressed-restructuring probation
(Art. 178(5A)–(5C)) **must be enforced upstream** before the `is_defaulted` flag can be
flipped from `True` back to `False`. The calculator does not maintain per-obligor state
between calculation runs.

---

## Key Scenarios

| Scenario ID | Description | Expected Routing |
|-------------|-------------|------------------|
| DEF-1 | Non-retail obligor 91 DPD, material credit obligation > GBP 440 and > 1% of on-balance-sheet | `is_defaulted = True` upstream → SA Art. 127 or IRB defaulted branch |
| DEF-2 | Retail obligor 91 DPD, any past-due amount > GBP 0 | `is_defaulted = True` → retail defaulted route |
| DEF-3 | Non-retail obligor 91 DPD, past-due amount GBP 100 (below GBP 440 floor) | **Not** a default (materiality floor not breached) |
| DEF-4 | Obligor files for bankruptcy (UTP indicator (f)), 0 DPD | `is_defaulted = True` — UTP limb (a) |
| DEF-5 | Obligor granted distressed restructuring with principal write-off (UTP indicator (d)), 0 DPD | `is_defaulted = True` — UTP limb (a), enters Art. 178(5A) 1-year probation on exit |
| DEF-6 | PSE exposure 120 DPD on goods-and-services contract, no UTP indicators, sound financial state | **Not** in default under PS1/26 Art. 178(1B)/(1C) — past-due amount excluded from materiality |
| DEF-7 | Retail RRE exposure 100 DPD under CRR with competent-authority 180-day option | **Not** in default under CRR; **is** in default under PS1/26 (180-day option removed) |
| DEF-8 | Defaulted exposure cured for 3 months, UTP re-assessment finds improvement factual and permanent | Upstream flips flag to `False`; engine routes as non-defaulted |
| DEF-9 | Distressed-restructured exposure cured for 11 months (< 1 year) | Upstream keeps `is_defaulted = True` — Art. 178(5A)(a) timing condition not met |
| DEF-10 | Disputed obligation subject to court proceedings, 150 DPD | Upstream may suspend DPD counter under Art. 178(1A); `is_defaulted` remains `False` |
| DEF-11 | Obligor undergoing merger — payment history of legacy entity not transferable | Art. 178(5C)(a): material-payment condition does not apply; new clock starts |
| DEF-12 | External pooled PD data uses 180-day default definition | Upstream adjusts per Art. 178(4) before feeding into calculator |

---

## Related Specifications

- [B31 Defaulted Exposures](../basel31/defaulted-exposures.md) — SA Art. 127 provision-coverage split and IRB K-formula
- [CRR Provisions](../crr/provisions.md) — EL vs provisions comparison and Art. 159(3) two-branch rule
- [B31 Provisions](../basel31/provisions.md) — Basel 3.1 Art. 158 reinstatement and post-model EL adjustment
- [CRR F-IRB](../crr/firb-calculation.md) — Foundation IRB capital formula
- [B31 F-IRB](../basel31/firb-calculation.md) — Basel 3.1 F-IRB with PD floors
- [CRR A-IRB](../crr/airb-calculation.md) — Advanced IRB with own LGD estimates
- [B31 A-IRB](../basel31/airb-calculation.md) — Basel 3.1 A-IRB with LGD floors and BEEL
- [Hierarchy and Classification](hierarchy-classification.md) — Exposure-class assignment
