# Model Permissions Specification (CRR)

CRR permanent partial use (PPU) conditions under Article 150(1) governing when a firm
that has IRB permission may nonetheless apply the **Standardised Approach** permanently
to specified exposures, and the Article 150(2) materiality thresholds for the equity
exposure class.

**Regulatory Reference:** CRR Art. 150(1)(a)–(j); Art. 150(2)
**Test Group:** CRR-M (no acceptance scenarios — PPU is a firm-level governance
permission, not a per-exposure RWA calculation; see [Engine
Inputs](#engine-inputs) below).

!!! warning "Time-limited regime — sunset 31 December 2026"
    CRR Art. 150 (as onshored) remains in force in UK law **until 31 December 2026**.
    From **1 January 2027** PRA PS1/26 replaces the conditions-based PPU framework in
    Art. 150(1) with the **materiality-threshold** framework in Art. 150(1A) — see
    [`../basel31/model-permissions.md#permanent-partial-use-materiality-thresholds-art-1501a`](../basel31/model-permissions.md#permanent-partial-use-materiality-thresholds-art-1501a).
    The Art. 150(2) equity 10% / 5% materiality thresholds documented on this page
    are **not** carried forward into PS1/26 in the same form; they apply to firms
    operating under the CRR pathway through to end-2026.

---

## Overview

Under CRR, a firm that has been granted permission to use the **IRB Approach** for one
or more exposure classes **may** nonetheless apply the **Standardised Approach**
permanently to certain enumerated exposures within those IRB-eligible classes. This is
the **permanent partial use** (PPU) regime. PPU is distinct from:

- **Sequential roll-out** under Art. 148, which permits **temporary** SA usage during a
  PRA-approved IRB implementation plan; and
- **Reverting** from IRB to SA under Art. 149, which requires demonstration that the
  reversion is not driven by capital-arbitrage motives.

CRR Art. 150(1) lists ten specific conditions (a)–(j) under which permanent SA usage is
permitted. Each condition targets a population where applying IRB would either be
disproportionate (immaterial / non-significant) or where a 0% risk weight under SA is
already definitionally appropriate (sovereigns, intra-group exposures, subsidised equity).

The Standardised Approach RWAs from PPU exposures continue to feed into the firm's
overall consolidated RWA — the permission relates to **how** the RWA is calculated, not
**whether** the exposure consumes capital.

## Art. 150(1) — Conditions for Permanent Partial Use

### Verbatim opening

> "Where institutions have received the prior permission of the competent authorities,
> institutions permitted to use the IRB Approach in the calculation of risk-weighted
> exposure amounts and expected loss amounts for one or more exposure classes may
> apply the Standardised Approach for the following exposures:"
>
> — CRR Art. 150(1), crr.pdf p.145

### Verbatim conditions (a)–(j)

The CRR enumerates ten alphabetical conditions. Verbatim text from `docs/assets/crr.pdf`
pp. 145–146 (post-EU-Exit consolidated UK CRR, document generated 2026-03-02):

> **(a)** the exposure class laid down in Article 147(2)(a), where the number of
> material counterparties is limited and it would be unduly burdensome for the
> institution to implement a rating system for these counterparties;
>
> **(b)** the exposure class laid down in Article 147(2)(b), where the number of
> material counterparties is limited and it would be unduly burdensome for the
> institution to implement a rating system for these counterparties;
>
> **(c)** exposures in non-significant business units as well as exposure classes or
> types of exposures that are immaterial in terms of size and perceived risk profile;
>
> **(d)** exposures to the central government of the United Kingdom, the Bank, a
> regional government of the United Kingdom, or a public sector entity or local
> authority in the United Kingdom, provided —
>
> > **(i)** there is no difference in risk between the exposures to the central
> > government and Bank and those other exposures because of specific public
> > arrangements; and
> >
> > **(ii)** exposures to central governments and central banks are assigned a 0 %
> > risk weight under Article 114(2) or (4);
>
> **(e)** exposures of an institution to a counterparty which is its parent
> undertaking, its subsidiary or a subsidiary of its parent undertaking provided that
> the counterparty is an institution or a financial holding company, mixed financial
> holding company, financial institution, asset management company or ancillary
> services undertaking subject to appropriate prudential requirements or an
> undertaking linked by a common management relationship;
>
> **(f)** exposures between institutions which meet the requirements set out in
> Article 113(7);
>
> **(g)** equity exposures to entities whose credit obligations are assigned a 0 %
> risk weight under Chapter 2 including those publicly sponsored entities where a
> 0 % risk weight can be applied;
>
> **(h)** equity exposures incurred under legislative programmes to promote specified
> sectors of the economy that provide significant subsidies for the investment to the
> institution and involve some form of government oversight and restrictions on the
> equity investments where such exposures may in aggregate be excluded from the IRB
> Approach only up to a limit of 10 % of own funds;
>
> **(i)** the exposures identified in Article 119(4) meeting the conditions specified
> therein;
>
> **(j)** State and State-reinsured guarantees referred to in Article 215(2).
>
> — CRR Art. 150(1)(a)–(j), crr.pdf pp.145–146

### Plain-English summary table

| Condition | Population | Eligibility test | Cross-references |
|-----------|------------|------------------|-------------------|
| **(a)** | Sovereigns / central banks (Art. 147(2)(a)) | Number of material counterparties is **limited**; building an IRB rating system would be **unduly burdensome** | CRR Art. 147(2)(a) — central government and central bank exposure class |
| **(b)** | Institutions (Art. 147(2)(b)) | Same "limited material counterparties + unduly burdensome" test as (a) | CRR Art. 147(2)(b) — institution exposure class |
| **(c)** | Non-significant business units; **immaterial** exposure classes or types | Immateriality measured both by **size** and by **perceived risk profile** | Materiality is qualitative under CRR — not bound to a specific numeric threshold (cf. PS1/26 Art. 150(1A) which introduces explicit 5% / 95% / 50% thresholds) |
| **(d)** | UK central government, Bank of England, UK RGLAs and PSEs | Both: (i) no difference in risk vs central government / Bank because of **specific public arrangements**; AND (ii) the central government / central bank legs would attract a **0% RW under Art. 114(2) or (4)** | CRR Art. 114(2) (national-currency sovereign), Art. 114(4) (third-country equivalent treatment); UK CRR amendment SI 2018/1401 reg. 129(2)(a) substitutes "United Kingdom" wording |
| **(e)** | Intra-group exposures to parent / subsidiary / sister entities | Counterparty must be one of: institution, financial holding company, mixed financial holding company, financial institution, asset management company, ancillary services undertaking — all **subject to appropriate prudential requirements** — or an undertaking linked by a **common management relationship** | UK CRR amendment SI 2018/1401 reg. 129(2)(b) replaced the original "Art. 12(1) of Directive 83/349/EEC" wording with "common management relationship" |
| **(f)** | Inter-institution exposures meeting Art. 113(7) requirements | Refers to the institutional protection scheme (IPS) eligibility conditions in Art. 113(7) — written agreement, joint and several liability, equivalent regulation, regular reporting | CRR Art. 113(7) |
| **(g)** | Equity exposures to **0% RW** entities under Chapter 2 | Includes equity in publicly sponsored entities entitled to a 0% sovereign-equivalent RW | CRR Chapter 2 (SA risk weights) — typically Art. 114, Art. 116, Art. 117, Art. 118 0%-RW entities |
| **(h)** | Equity under government **subsidy programmes** | All four limbs required: (1) **legislative programme** to promote specified economic sectors; (2) **significant subsidies** to the institution for the investment; (3) **government oversight**; (4) **restrictions** on the equity investment. Cap: aggregate exclusions under (h) ≤ **10% of own funds** | The 10% cap in (h) is distinct from the Art. 150(2) materiality test on the wider equity class (see below) |
| **(i)** | Exposures meeting Art. 119(4) — minimum reserves with the Bank | Minimum-reserve balances at the Bank of England may be risk-weighted as exposures to the Bank, subject to the conditions in Art. 119(4)(a)–(c) (national-requirement equivalence, no penal repayment provisions, etc.) | CRR Art. 119(4), crr.pdf p.118 |
| **(j)** | State / State-reinsured guarantees within Art. 215(2) scope | Refers to the unfunded credit protection eligibility conditions for State or State-reinsured guarantees | CRR Art. 215(2) |

!!! info "Art. 150(1)(a) and (b) — 'Limited material counterparties + unduly burdensome'"
    Conditions (a) and (b) share the same two-limb eligibility test for sovereign and
    institution exposure classes respectively. Both limbs must hold:

    - **Limb 1 — limited population**: the number of material counterparties in the
      class is small enough that statistical IRB modelling would be unreliable.
    - **Limb 2 — disproportionate cost**: the burden of building, validating, and
      maintaining a rating system for those counterparties would be disproportionate
      to the prudential benefit.

    "Material" is not numerically defined in CRR. The PRA evaluates these conditions
    case-by-case at the point of granting the IRB permission and on subsequent
    Art. 143 model-change applications.

!!! info "Art. 150(1)(c) — Immateriality is qualitative under CRR"
    Unlike PS1/26 Art. 150(1A) which introduces explicit numeric materiality
    thresholds (95% RWA non-reduction, 5% group-RWA, 50% within roll-out class), the
    CRR Art. 150(1)(c) test is **qualitative**: "immaterial in terms of size and
    perceived risk profile". The PRA's supervisory expectations for what constitutes
    a non-significant business unit or an immaterial exposure type are set out in
    SS11/13 and the Banking Capital Requirements Directive (BCRD) materiality
    regime, both of which sit outside the CRR rulebook.

!!! note "Art. 150(1)(d) — UK-specific re-targeting"
    The original EU CRR text in Art. 150(1)(d) referred to exposures of **Member
    States**' central governments, regional governments, and PSEs. The 2018 EU Exit
    onshoring (SI 2018/1401, regs. 129(2)(a)(i)–(ii)) substituted "the United
    Kingdom" / "the Bank" throughout, narrowing the carve-out to **UK-resident**
    sovereigns, RGLAs, PSEs, and local authorities. Non-UK sovereigns now route
    through condition (a) (limited material counterparties) or directly via the
    standard SA path under Art. 114.

!!! note "Art. 150(1)(h) — 10% own-funds cap is exposure-side, not portfolio-side"
    The 10% cap in condition (h) limits the aggregate equity exposures **excluded
    from IRB under (h) only**. It does **not** apply to other equity exposures
    excluded under conditions (g), (i), or to the wider materiality test in
    Art. 150(2). A firm could in principle have:

    - some equity exempted under (g) (0%-RW counterparties),
    - up to 10% of own funds exempted under (h) (subsidised equity),
    - and the remainder of its equity book treated under IRB,

    all simultaneously.

## Art. 150(2) — Equity Materiality Thresholds

### Verbatim text

> "For the purposes of paragraph 1, the equity exposure class of an institution shall
> be material if their aggregate value, excluding equity exposures incurred under
> legislative programmes as referred to in point (h) of paragraph 1, exceeds on
> average over the preceding year 10 % of the own funds of the institution. Where
> the number of those equity exposures is less than 10 individual holdings, that
> threshold shall be 5 % of the own funds of the institution."
>
> — CRR Art. 150(2), crr.pdf p.146

### Mechanics

Art. 150(2) sets the **materiality test** that determines whether the equity exposure
class can be excluded from IRB at all under the Art. 150(1)(c) "immaterial" route. It
applies a two-tier threshold to the **aggregate** equity book (excluding the
subsidised-equity carve-out from (h)):

| Tier | Condition | Threshold (aggregate equity / own funds, average over preceding year) |
|------|-----------|----------------------------------------------------------------------|
| **Tier 1 — diversified book** | Number of individual equity holdings ≥ 10 | **10% of own funds** |
| **Tier 2 — concentrated book** | Number of individual equity holdings < 10 | **5% of own funds** |

If the aggregate exceeds the applicable threshold, the equity class is **material**
and cannot be permanently excluded from IRB under Art. 150(1)(c). Below the threshold,
the class qualifies for PPU under (c) (subject to the qualitative business-unit /
risk-profile leg of (c)).

### Worked example

A firm with own funds of GBP 5,000m has:

- 12 individual equity holdings totalling **GBP 460m** average over the preceding year
  — none falling under Art. 150(1)(h);
- Plus a separate **GBP 80m** equity position under a government-subsidised
  legislative programme (excluded from the Art. 150(2) numerator under the
  parenthetical "excluding equity exposures incurred under legislative programmes as
  referred to in point (h)").

Calculation:

- Diversified book: 12 holdings ≥ 10 → applicable threshold is **10%** of own funds
  = **GBP 500m**.
- Aggregate equity (excluding (h)): GBP 460m → ratio = 460 / 5,000 = **9.2%**.
- 9.2% < 10% threshold → equity class is **immaterial** for Art. 150(2) purposes.

The firm may therefore (subject to qualitative conditions in (c) and Art. 150(1)
opening words) apply for permanent SA permission on the equity class.

If the firm instead held only **8** equity holdings totalling GBP 460m, the threshold
would drop to **5%** = GBP 250m, the aggregate (GBP 460m) would breach it, and the
equity class would be **material** — the carve-out under Art. 150(1)(c) would not be
available.

### Engine implementation note

!!! warning "Art. 150(2) materiality test is not enforced by the calculator"
    The RWA engine **does not** evaluate the Art. 150(2) 10% / 5% thresholds. The
    materiality test is a firm-level governance and permission decision that
    operates at the **point of applying for / maintaining** an IRB permission, not at
    the per-exposure RWA calculation stage. The calculator trusts the
    `model_permissions` data source as evidence of the permissions actually held.

    Consistent with this, there is **no `apply_partial_ppu` flag on
    `CalculationConfig`** — early drafts of `DOCS_IMPLEMENTATION_PLAN.md` D4.64
    speculated such a field; the actual config (see
    [`config.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/master/src/rwa_calc/contracts/config.py))
    expresses PPU implicitly via the `IRBPermissions` mapping (an exposure class
    with no IRB approach permitted falls back to SA per the
    [routing precedence in `basel31/model-permissions.md`](../basel31/model-permissions.md#routing-precedence)).
    Whether that permission corresponds to a CRR Art. 150(1) PPU permission, an
    Art. 148 sequential-roll-out permission, or a fresh STANDARDISED-mode firm with
    no IRB at all is **not** distinguished by the engine.

    See the [Engine Inputs](#engine-inputs) section below for the data that **is**
    consumed at runtime.

## CRR ↔ B31 Comparison

CRR Art. 150(1) and PS1/26 Art. 150(1A) implement the same regulatory objective —
permanent partial use of SA inside an IRB framework — but with materially different
mechanics. The CRR approach is **conditions-based** (ten enumerated populations);
the B31 approach is **materiality-threshold-based** (numeric 95% / 5% / 50% bounds).

| Aspect | CRR Art. 150(1)–(2) (effective ≤ 31 Dec 2026) | PS1/26 Art. 150(1A) (effective ≥ 1 Jan 2027) |
|--------|-----------------------------------------------|----------------------------------------------|
| **Mechanism** | Enumerated conditions (a)–(j) plus equity materiality test in (2) | Numeric materiality thresholds at roll-out class level |
| **Sovereign / institution carve-out** | Explicit (Art. 150(1)(a) / (b)) — "limited material counterparties + unduly burdensome" | Subsumed into Art. 147A(1)(a)/(b) hard SA-only / F-IRB-only restrictions; PPU is no longer the routing mechanism for sovereigns and institutions |
| **Immateriality test** | Qualitative — "non-significant business units" + "immaterial in size and perceived risk profile" (Art. 150(1)(c)) | Quantitative — SA RWA ≤ 5% of total group credit-risk RWA (Art. 150(1A)(b)); type-level cap 5% of IRB-eligible total group RWA (Art. 150(1A)(c)) |
| **Anti-cherry-picking** | Implicit via "perceived risk profile" wording in (c) | Explicit — SA RWA must be ≥ 95% of IRB RWA for the roll-out class (Art. 150(1A)(a)); SA must not exceed 50% of RWA within a roll-out class (Art. 150(1A)(d)) |
| **UK government / BoE carve-out** | Explicit in Art. 150(1)(d) (UK central govt / Bank / RGLA / PSE / local authority) | Subsumed into Art. 147A(1)(a) hard SA-only restriction for sovereigns and 0%-RW quasi-sovereigns; the Art. 150(1)(d) carve-out becomes redundant |
| **Intra-group / inter-institution** | Explicit conditions (e), (f) | Not separately codified — intra-group treatment continues under the wider IRB scope of application rules in Art. 18 / Part 1 Title II |
| **Equity carve-outs** | Explicit conditions (g), (h) plus 10% (h)-cap | Subsumed into Art. 147A(1)(h) — equity is **SA only** under B31; no IRB equity approach available; the (g) / (h) PPU routes become redundant |
| **Equity materiality test** | Art. 150(2) — 10% of own funds (≥10 holdings) / 5% (<10 holdings), aggregate over preceding year | Not carried forward — Art. 147A(1)(h) applies SA universally to equity, so a materiality test for IRB-equity exclusion is unnecessary |
| **State guarantee carve-out** | Explicit in Art. 150(1)(j) — Art. 215(2) State / State-reinsured guarantees | Routing handled under the standard CRM framework; no PPU carve-out required |
| **Minimum-reserve carve-out** | Explicit in Art. 150(1)(i) — Art. 119(4) reserves at Bank of England | Carry-forward — Bank-of-England minimum reserves continue to be risk-weighted as Bank exposures via the Art. 119 lineage in PS1/26, outside the PPU framework |
| **Form of permission** | Permission of the **competent authority** (PRA), granted at IRB permission stage and on Art. 143 model-change applications | Same — permission under sections 144G / 192XC of FSMA, Capital Requirements Regulations Part 8 procedural rules |

> **Cross-reference.** The B31 materiality-threshold table is documented in detail at
> [`../basel31/model-permissions.md#permanent-partial-use-materiality-thresholds-art-1501a`](../basel31/model-permissions.md#permanent-partial-use-materiality-thresholds-art-1501a)
> and at [`../basel31/irb-approach.md`](../basel31/irb-approach.md) (sections covering
> COREP OF 08.07 columns 0160–0180). The Art. 147A approach restrictions that
> displace many of the CRR Art. 150(1) carve-outs from the routing pipeline are
> documented at
> [`../basel31/model-permissions.md#art-147a-approach-restrictions`](../basel31/model-permissions.md#art-147a-approach-restrictions).

## Engine Inputs

CRR Art. 150(1) is a **firm-level permission** rather than a per-exposure parameter.
The calculator does not explicitly model PPU as a configuration concept; instead, PPU
is **implicit** in the combination of `permission_mode`, `IRBPermissions`, and the
per-exposure `model_id` lookup against the `model_permissions` data source.

### Configuration surface

| Field | Type | Effect on PPU routing |
|-------|------|------------------------|
| `CalculationConfig.permission_mode` | `PermissionMode.STANDARDISED` \| `PermissionMode.IRB` | `STANDARDISED` forces the entire portfolio to SA (equivalent to "no IRB permission held"). `IRB` switches to model-permission-driven routing per Art. 147A / Art. 150(1). |
| `CalculationConfig.irb_permissions` | `IRBPermissions` (derived from `permission_mode` in `__post_init__`) | A class-by-class map of permitted approaches. An exposure class whose permitted set is `{ApproachType.SA}` is effectively under permanent partial use for that class. |
| `model_permissions` data source row | `(model_id, exposure_class, approach)` triples | Per-exposure / per-model approach grant. An exposure whose `model_id` is missing or whose `approach` is `SA` falls back to SA — the runtime equivalent of an Art. 150(1) carve-out applied to that specific exposure. |

### How the engine encodes each Art. 150(1) condition

| Art. 150(1) condition | Engine representation |
|------------------------|------------------------|
| **(a)** Sovereign limited-population PPU | Set `IRBPermissions.permissions[ExposureClass.CENTRAL_GOVT_CENTRAL_BANK] = {ApproachType.SA}` (or omit the key — the default fallback in `is_permitted` is SA only). No per-exposure flag is required; all sovereign exposures route to SA. |
| **(b)** Institution limited-population PPU | Set `IRBPermissions.permissions[ExposureClass.INSTITUTION] = {ApproachType.SA}`. |
| **(c)** Non-significant BU / immaterial type | No native engine representation. PPU at the **business unit** level is achieved by tagging the relevant exposures with a `model_id` that has no IRB grant in `model_permissions` — the classifier then routes them to SA. The aggregate materiality test under Art. 150(1)(c) / Art. 150(2) is **not** validated by the engine. |
| **(d)** UK government / Bank / UK RGLA / PSE | These exposures already attract a 0% RW under SA Art. 114(2) / Art. 116. Setting `IRBPermissions` to `{SA}` for the relevant classes (CGCB, RGLA, PSE) achieves the routing; the 0% RW comes from the standard SA tables. |
| **(e), (f)** Intra-group / inter-institution PPU | Achieved at exposure level via `model_permissions` — exposures to in-scope group counterparties carry a `model_id` with no IRB grant. The Art. 113(7) IPS eligibility check itself is **not** validated by the engine. |
| **(g)** Equity to 0%-RW counterparties | Equity is SA-only under Art. 147A in B31 and routed via `ExposureClass.EQUITY → {SA}` under CRR's `full_irb` permissions map. The 0% RW for sovereign-equivalent equity counterparties is applied via the SA equity tables (Art. 133 lineage). |
| **(h)** Subsidised equity, 10% own-funds cap | Routing identical to (g). The **10% cap** is a firm-level governance test, not enforced by the engine. |
| **(i)** Art. 119(4) Bank minimum reserves | These are typically modelled as separate sovereign (Bank) exposures with the appropriate 0% sovereign RW; the PPU permission to treat them as Bank-equivalent is built into the SA risk-weight tables for sovereign exposures. |
| **(j)** State / State-reinsured guarantees | Handled inside the CRM stage (unfunded credit protection substitution, Art. 215(2) eligibility). The PPU permission overlaps with the standard SA route for the residual unsecured exposure. |

### Code references

- Approach permissions live in
  [`contracts/config.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/master/src/rwa_calc/contracts/config.py)
  — `IRBPermissions`, `PermissionMode`, `CalculationConfig.permission_mode`.
- Per-exposure `model_id` lookup against the `model_permissions` data source happens
  in [`engine/stages/classify/permissions.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/master/src/rwa_calc/engine/stages/classify/permissions.py)
  (the `engine/classifier.py` shim re-exports it for back-compat)
  — fall-back to SA on missing/invalid `model_id` is documented there.
- Schema for the `model_permissions` data source is in
  [`data/schemas.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/master/src/rwa_calc/data/schemas.py)
  (constraints map entry `"model_permissions"`).

!!! info "Roadmap"
    A future enhancement could introduce an explicit `ppu_reason` column on the
    `model_permissions` data source enumerating the Art. 150(1) condition under
    which a model-permission-less exposure is being treated as SA (e.g.
    `"art_150_1_a"`, `"art_150_1_d"`). This would give COREP OF 08.07 / C 08.07
    column-0050 ("of which: Exposures under permanent partial use of SA")
    deterministic provenance under the CRR pathway. The current implementation
    aggregates all SA-routed IRB-class exposures into the column without
    distinguishing PPU, sequential roll-out (Art. 148), or no-permission cases.
    See [`../../features/corep-reporting.md`](../../features/corep-reporting.md)
    for the column populated today.

---

## Fallback Behaviour

When no `model_permissions` row matches an exposure under the CRR pathway:

- The exposure is routed to the **Standardised Approach** (SA) via the default branch
  of `IRBPermissions.is_permitted`.
- No error is raised — this is the expected outcome for exposures sitting outside any
  IRB permission scope, including PPU exposures.
- The fallback is logged as a data-quality note, not an error.

This mirrors the B31 routing fallback documented at
[`../basel31/model-permissions.md#fallback-behaviour`](../basel31/model-permissions.md#fallback-behaviour).

---

## Related Specifications

- [Basel 3.1 Model Permissions](../basel31/model-permissions.md) — Art. 147A approach
  restrictions, Art. 150(1A) materiality thresholds, Art. 143(6)–(8) Overseas Model
  Approach.
- [Hierarchy and Classification](../common/hierarchy-classification.md) — exposure
  class assignment that gates which Art. 150(1) condition is in scope.
- [SA Risk Weights](sa-risk-weights.md) — risk weights applied to PPU exposures once
  they have been routed away from IRB.
- [F-IRB Calculation](firb-calculation.md) and
  [A-IRB Calculation](airb-calculation.md) — IRB pathways from which PPU exposures
  are excluded.
