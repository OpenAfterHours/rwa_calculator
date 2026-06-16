# Model Permissions Specification

Basel 3.1 approach restrictions under Art. 147A limiting which exposure classes may use A-IRB,
and routing exposures to F-IRB, slotting, or SA based on regulatory constraints.

**Regulatory Reference:** PRA PS1/26 Art. 147A; PS1/26 Glossary p. 78 (LFSE definition, corresponds to CRR Art. 142(1)(4))
**Test Group:** B31-M

---

## Requirements Status

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-11.1 | Art. 147A approach restriction routing | P0 | Done |
| FR-11.2 | FSE restriction: all FSEs → F-IRB only (Art. 147A(1)(e)) | P0 | Done |
| FR-11.3 | Large corporate restriction: revenue >£440m → F-IRB only (Art. 147A(1)(e)) | P0 | Done |
| FR-11.4 | Institution exposure → F-IRB only, Art. 147A(1)(b) (no A-IRB) | P0 | Done |
| FR-11.5 | Equity exposure → SA only (Art. 147A(1)(h) per Art. 147(2)(e)) | P0 | Done |
| FR-11.6 | Sovereign + all quasi-sovereigns (RGLA, PSE, MDB per Art. 117, Int'l Org per Art. 118) → SA only (Art. 147A(1)(a)) | P0 | Done |
| FR-11.7 | IPRE/HVCRE → Slotting only, Art. 147A(1)(c) (if no A-IRB permission) | P0 | Done |
| FR-11.8 | Model permissions config and fallback logic | P0 | Done |

---

## Overview

Art. 147A introduces **mandatory approach restrictions** that limit which exposure classes may use
the Advanced IRB (A-IRB) approach under Basel 3.1. These restrictions address concerns about
model risk in areas where internal estimates have proven unreliable or insufficiently validated.

The restrictions are enforced in the classifier stage of the pipeline, after hierarchy resolution
and before calculation. Exposures that fail the Art. 147A check are routed to a permitted approach.

## Art. 147A Approach Restrictions

### Restriction Table

The letter scheme in Art. 147A(1) points to sub-classes in **Art. 147(2)**
(verified against PRA PS1/26 ps126app1.pdf pp.88, 92–93, 17 Apr 2026). Financial
corporates and large corporates are **grouped together** under point (c)(ii) of
Art. 147(2) — both are handled by Art. 147A(1)(**e**), not by separate letters.

| Exposure Class | Permitted Approaches | Restriction | Reference |
|---------------|---------------------|-------------|-----------|
| Sovereign (incl. central banks and quasi-sovereigns: RGLA, PSE, MDB, Int'l Org with 0% RW) | SA only | No IRB permission | Art. 147A(1)(a) → Art. 147(2)(a) |
| Institution | F-IRB only (SA with permission) | A-IRB not permitted | Art. 147A(1)(b) → Art. 147(2)(b) |
| SL IPRE / HVCRE | SA or Slotting only | No F-IRB or A-IRB | Art. 147A(1)(c) → Art. 147(2)(c)(i) |
| SL — OF / PF / CF | SA, F-IRB, A-IRB or Slotting | Subject to granted permission | Art. 147A(1)(d) → Art. 147(2)(c)(i) |
| **Financial corporate (all FSEs) AND Large corporate (revenue > £440m)** | **F-IRB only** (SA with permission) | A-IRB not permitted — both sub-classes share one rule under Art. 147(2)(c)(ii) | **Art. 147A(1)(e)** → Art. 147(2)(c)(ii) |
| Other general corporate (non-FSE, revenue ≤ £440m) | F-IRB (default); A-IRB with Art. 143(2A)/(2B) permission | A-IRB available only with explicit permission | Art. 147A(1)(f) → Art. 147(2)(c)(iii) |
| Retail (mortgage, QRRE, other) | A-IRB (SA with permission) | **Carry-forward from CRR** — retail has always been A-IRB-only (CRR Art. 151(7) mandated own-LGD/own-CCF for retail; F-IRB was only available for sovereign/institution/corporate under CRR Art. 151(8)). Not a new B31 restriction. | Art. 147A(1)(g) → Art. 147(2)(d); cf. CRR Art. 151(7) |
| Equity | SA only | IRB equity approaches removed (Art. 155 left blank) | Art. 147A(1)(h) → Art. 147(2)(e) |

!!! info "Art. 147A(1)(a) Scope — All 0% RW Quasi-Sovereigns Are SA-Only"
    Art. 147A(1)(a) restricts the whole of Art. 147(2)(a) — "central governments, central
    banks **or quasi-sovereigns**" — to the Standardised Approach. The "quasi-sovereign"
    scope captures every SA exposure that the Part routes to a 0% sovereign-equivalent
    risk weight, including:

    - **UK / third-country RGLAs** treated as central government (Art. 115(1)-(2), Art. 115(3A));
    - **Public sector entities (PSEs)** treated as central government (Art. 116(1)-(2),
      Art. 116(3A)) or assigned 0% by the competent authority (Art. 116(4), not retained
      under PS1/26);
    - **Multilateral development banks (MDBs)** listed in Art. 117(2) — IBRD, IFC, IADB,
      ADB, AfDB, CoE Development Bank, Nordic Investment Bank, Caribbean Development Bank,
      EBRD, EIB, EIF, MIGA, IFFIm, IsDB, IDA, AIIB. Other (rated) MDBs under Art. 117(1)
      also fall within Art. 147(2)(a) for approach-routing purposes even when their SA
      weight is not 0%;
    - **International organisations** listed in Art. 118(1) — European Union, IMF, BIS,
      and the other named bodies.

    All of the above are therefore **excluded from any IRB approach** regardless of the
    firm's model permissions. This mirrors the classifier rule in
    [`../common/hierarchy-classification.md#basel-31-approach-restrictions-art-147a`](../common/hierarchy-classification.md#basel-31-approach-restrictions-art-147a).

!!! note "Art. 147A(1)(e) — FSEs and Large Corporates Share One Restriction"
    Under PRA PS1/26, **Art. 147A(1)(e)** covers both financial sector entities (FSEs,
    defined in Art. 4(1)(27)) and large corporates (revenue > £440m) because Art. 147(2)(c)(ii)
    groups them into the single sub-class "financial corporates and large corporates".
    Both are restricted to **F-IRB** (or SA with permission) — A-IRB is not available.
    The LFSE **total-assets** threshold — **GBP 79 billion** under PS1/26 Glossary p. 78
    (corresponds to CRR Art. 142(1)(4), which sets **EUR 70 billion** under CRR) — is a
    **separate** provision that drives the 1.25× correlation multiplier (Art. 153(2));
    it does NOT determine the approach restriction in Art. 147A(1)(e). Small FSEs below
    the LFSE threshold are still restricted to F-IRB under Art. 147A(1)(e).

!!! note "Earlier drafts incorrectly cited Art. 147A(1)(d) for large corporates"
    Previous versions of this spec cited "Art. 147A(1)(d)" for the large-corporate
    F-IRB restriction. That letter actually covers object/project/commodities finance
    under Art. 147(2)(c)(i). The authoritative rule for both large corporates and FSEs
    is Art. 147A(1)(**e**), verified against ps126app1.pdf p.92.

!!! info "Retail A-IRB-Only Is a CRR Carry-Forward, Not a New B31 Restriction"
    Art. 147A(1)(g) formalises — in the new structured Basel 3.1 wording — a rule that
    has been in force since the original CRR. Under **CRR Art. 151(7)**, firms applying
    IRB to retail (Art. 147(2)(d)) were **required** to provide own estimates of LGDs
    and conversion factors, i.e. A-IRB. **CRR Art. 151(8)** restricted F-IRB (supervisory
    LGDs under Art. 161(1) and supervisory CCFs under Art. 166(8)(a)–(d)) to exposure
    classes (a)–(c) — sovereigns, institutions, and corporates — with retail explicitly
    excluded from that list.

    The Basel 3.1 changes for retail are **not** about removing F-IRB (it was never
    available) — they are:

    - **New input floors**: PD floor 0.05% QRRE transactor / 0.10% non-transactor / 0.05% mortgage /
      0.10% other retail (Art. 160(1a)/(2)); LGD floors per Art. 164(4); EAD floors per
      Art. 166 — see [`airb-calculation.md`](airb-calculation.md).
    - **Subclass redefinition**: QRRE transactor/non-transactor split (PRA Glossary p.9);
      £90k single-obligor threshold in Art. 147(5A)(c).
    - **Maturity parameter unchanged**: `M = 1` continues to apply to retail under
      Art. 154(1)(c), as it did under CRR. This is a property of the retail IRB formula,
      not an Art. 147A restriction.

    See [`../../framework-comparison/key-differences.md#irb-approach-restrictions`](../../framework-comparison/key-differences.md#irb-approach-restrictions)
    for the full CRR-vs-B31 approach matrix, where the retail row correctly shows "A-IRB | A-IRB".

### Large Corporate Definition

**Art. 147A(1)(e) via Art. 147(2)(c)(ii):** A corporate exposure is classified as
"large corporate" if:

- The obligor's **consolidated annual revenue** exceeds **£440 million** (GBP)

!!! warning "Distinct Thresholds — Approach Restriction vs Correlation Multiplier"
    The **£440m revenue** threshold (Art. 147A(1)(e), via Art. 147(2)(c)(ii)) for the
    large-corporate approach restriction is entirely distinct from the LFSE
    **total-assets** threshold (**GBP 79 billion** under PS1/26 Glossary p. 78;
    EUR 70 billion under CRR Art. 142(1)(4)) for the FSE correlation multiplier.
    They target different populations and use different metrics:

    - **Art. 147A(1)(e)**: revenue-based (large corporates) and entity-type based (all FSEs),
      restricts A-IRB → F-IRB.
    - **LFSE threshold** (PS1/26 Glossary / CRR Art. 142(1)(4)): asset-based, applies 1.25×
      correlation uplift under Art. 153(2).

### Financial Sector Entity (FSE) Definition

**Art. 4(1)(27), Art. 147A(1)(e):** An FSE is an entity whose primary business involves:

- Banking, insurance, asset management, or financial intermediation

**All FSEs** (regardless of size) are restricted to F-IRB under Art. 147A(1)(e). This includes
both regulated and unregulated financial entities.

Separately, a **large FSE (LFSE)** — total assets ≥ **GBP 79 billion** under PS1/26 Glossary
p. 78 (CRR equivalent: ≥ EUR 70 billion per Art. 142(1)(4)) — receives the 1.25x correlation
multiplier under Art. 153(2). This correlation uplift is distinct from the approach restriction —
even small FSEs that do not trigger the correlation multiplier are still restricted to F-IRB.

### IPRE/HVCRE Routing

**Art. 147A(1)(c)** (via Art. 147(2)(c)(i)): Income-producing real estate (IPRE) and
high-volatility commercial real estate (HVCRE) exposures must use either the
**Standardised Approach** (with Art. 148 / Art. 150 permission) or the **Slotting Approach**.
F-IRB and A-IRB are **not** available for IPRE/HVCRE. In practice, most firms without
an Art. 148/150 SA permission for these sub-classes will route to slotting.

## Permission Configuration

Model permissions are configured via the `model_permissions` input data source, which specifies
per-exposure-class and per-model approach permissions:

```python
config = CalculationConfig.basel_3_1(
    irb_approach_permissions={
        ExposureClass.CORPORATE: ApproachType.AIRB,
        ExposureClass.RETAIL: ApproachType.AIRB,
        ExposureClass.INSTITUTION: ApproachType.FIRB,  # A-IRB not permitted
    }
)
```

### Routing Precedence

The classifier applies restrictions in the following order:

1. **Art. 147A hard constraints** — exposure class-level restrictions (equity→SA,
   sovereign/RGLA/PSE/MDB/international organisation→SA, institution→F-IRB, all FSEs→F-IRB,
   IPRE/HVCRE→slotting, retail→A-IRB) override any permission
2. **Threshold-based restrictions** — large corporate (>£440m revenue) overrides A-IRB permission
   to F-IRB
3. **Model permissions** — firm-specific approach permissions from the `model_permissions` table
4. **Fallback** — exposures with no valid permission fall back to SA

!!! note "Implementation"
    Art. 147A routing is implemented in the classify stage package
    `src/rwa_calc/engine/stages/classify/` (specifically `approach.py` / `permissions.py`).
    Model permissions are loaded from the `model_permissions` data source and resolved
    at the exposure level. Invalid `model_id` values fall back to SA silently.

## Art. 143(2A)/(2B) — A-IRB Permission Conditions for Other General Corporates

For "other general corporates" (Art. 147(2)(c)(iii) — non-FSE corporates with consolidated
revenue ≤ £440m), Art. 147A(1)(f) makes the **Foundation IRB Approach the default** IRB
treatment, and the **Advanced IRB Approach is available only where the PRA has granted
permission under Art. 143(2A) or Art. 143(2B)**. This subsection documents the substantive
conditions a firm must satisfy to obtain that A-IRB permission.

### Routing Reminder (Art. 147A(1)(f))

| Condition | Approach used |
|-----------|---------------|
| SA permission granted under Art. 148 or Art. 150 | Standardised Approach |
| **A-IRB permission granted under Art. 143(2A) or (2B)** | **Advanced IRB Approach** |
| All other other-general-corporate exposures | Foundation IRB Approach (default) |

> **Verbatim source:** PRA PS1/26 Appendix 1, p. 92 (Art. 147A(1)(f)).

### When Each Permission Article Applies

| Article | Trigger | Object of the application |
|---------|---------|---------------------------|
| **Art. 143(2A)** | Initial IRB permission application (firm has no current IRB permission for the class/subclass/type) | Firm declares, **per exposure class / subclass / type**, whether it proposes to adopt the Slotting Approach, the Foundation IRB Approach, or the Advanced IRB Approach **instead of the Standardised Approach** |
| **Art. 143(2B)** | Subsequent application by a firm that already has an IRB permission, seeking to **move up the IRB hierarchy** (e.g. SA → IRB, Slotting → F-IRB, Slotting → A-IRB, **F-IRB → A-IRB**) | The "more sophisticated" approach for the chosen exposure class / subclass / type |

For other general corporates, an A-IRB application will be **Art. 143(2B)** in the typical
case — the firm is already running F-IRB (the Art. 147A(1)(f)(iii) default) on those
exposures and is now applying for A-IRB on top.

### Substantive Permission Test — "Materially Comply With This Part"

Both Art. 143(2A) and Art. 143(2B) gate permission on the same substantive standard: the
applicant must **demonstrate to the satisfaction of the PRA** that its proposed
arrangements **materially comply with Part 3 (Credit Risk: IRB)**. The two paragraphs
operationalise that test slightly differently:

**Art. 143(1)(b) standard (referenced by Art. 143(2A) initial applications):**

> "An institution shall be considered to materially comply with this Part if:
> (i) the effect of any non-compliance is immaterial for each of its rating systems; and
> (ii) the overall effect of any non-compliance is immaterial."
>
> — PRA PS1/26 Appendix 1, p. 81 (Art. 143(1)(b))

**Art. 143(2C) standard (referenced by Art. 143(2B) sophistication applications):**

> "The change proposed in an application shall be considered to materially comply with
> this Part if it fully complies with this Part or if both of the following conditions
> are met:
> (a) the effect of any non-compliance for each of the institution's relevant rating
> systems would be immaterial if the institution made the proposed change; and
> (b) the overall effect of the non-compliance would be immaterial if the institution
> made the proposed change."
>
> — PRA PS1/26 Appendix 1, p. 82 (Art. 143(2C))

Both tests apply at **two levels**: the individual rating system, and the overall IRB
permission perimeter. Material non-compliance at either level is sufficient to deny
permission.

### High-Level Requirements the Rating System Must Meet (Art. 144(1))

"Materially comply with this Part" is a forward-reference to the substantive minimum
requirements in Article 144 onwards. For an A-IRB other-general-corporate application,
each rating system in scope must satisfy **all** of the following (PRA PS1/26 Appendix 1,
pp. 86–87, Art. 144(1)):

| Letter | Requirement (paraphrased; see PDF for verbatim text) |
|--------|--------------------------------------------------------|
| (a) | Meaningful assessment of obligor and transaction characteristics, meaningful differentiation of risk, accurate and consistent quantitative estimates of risk |
| (b) | **Use test** — internal ratings, default and loss estimates play an *essential role* in risk management, decision-making, credit approval, internal capital allocation and corporate governance |
| (c) | **Independent credit risk control unit** responsible for each rating system, free from undue influence |
| (d) | All relevant data collected and stored to support credit risk measurement and management |
| (e) | Each rating system **documented** (design rationale) and **validated** |
| (f) | Each rating system has been validated **prior to permission** for an appropriate time period, with assessed suitability for the rating system's range of application and any necessary changes made |
| (g) | Firm has computed IRB own-funds requirements and can submit Reporting (CRR) Part Article 430 returns |
| (h) | Each exposure in the rating system's range of application has been (and continues to be) assigned to a rating grade or pool |

Article 144(1A) extends each of these obligations to **third-party (vendor) rating
systems and models** — the firm cannot offload compliance to a vendor.

### Minimum Data History — Art. 145

Article 145 sets the minimum **prior experience** thresholds. For A-IRB on
other general corporates, the relevant requirements are (PRA PS1/26 Appendix 1, pp. 87–88):

| Paragraph | Requirement |
|-----------|-------------|
| **Art. 145(1)** | The applicant must demonstrate it has been using rating systems "broadly in line with the requirements set out in Section 6 for internal risk measurement and management purposes for **at least three years** prior to its qualification to use the IRB Approach" — for the IRB exposure classes in question. |
| **Art. 145(2)** | A firm applying for A-IRB on **non-retail** exposures (which includes other general corporates) must demonstrate that it "has been **estimating and employing own estimates of LGDs, and conversion factors or EADs**, in a manner that is broadly consistent with the requirements for use of own estimates of those parameters set out in Section 6 for **at least three years** prior to qualification to use the Advanced IRB Approach for non-retail exposures." |
| **Art. 145(3)** | When extending an existing IRB permission to additional exposures, the firm must demonstrate that its prior experience is sufficient for the additional scope. If the new exposures are *significantly different* from the existing coverage, the firm must submit fresh documentary evidence that the three-year tests in (1) and (2) are met for the new scope. |

The Art. 145(2) three-year own-estimate track record is the **A-IRB-specific gate** —
F-IRB applicants need only the (1) three-year IRB-broadly-consistent track record, while
A-IRB applicants must also evidence three years of own-LGD and own-CCF/EAD estimation.

> **Cross-reference to Section 6 minimum requirements.** Art. 144(1) and Art. 145 both
> point to the detailed minimum requirements in Section 6 of Part 3 (Articles 169–191 in
> the PS1/26 numbering — rating system structure, risk quantification, validation, use
> test, data maintenance, internal governance, and the Article 181 / Article 182
> requirements specific to **own estimates of LGD** and **own estimates of conversion
> factors**). Those articles are the substantive content the PRA tests against the
> "materially complies" standard. They are out of scope for this routing-focused page.

### Application Process (PS1/26 / FSMA Framework)

The mechanical process for lodging an Art. 143(2A) or (2B) application is governed by
the FSMA permission framework rather than by Art. 143 itself:

- **Permission instrument:** Art. 143(1) and (2A), and Art. 143(2B) together with (2C),
  are each flagged as *"a permission under sections 144G and 192XC of FSMA to which
  Part 8 of the Capital Requirements Regulations applies"* (PS1/26 Appendix 1, pp. 81–82).
  The Capital Requirements Regulations Part 8 sets out the procedural rules (form of
  application, fees, PRA decision timetable, modification powers).
- **Per-class declaration (Art. 143(2A)):** The application must "make clear in relation
  to each exposure class, exposure subclass or type of exposures, as the case may be,
  its proposal to adopt one or more of [the Slotting Approach, F-IRB, A-IRB] instead of
  the Standardised Approach" (PS1/26 Appendix 1, p. 81). For other general corporates
  the relevant subclass is Art. 147(2)(c)(iii).
- **Documentation requirements:** Article 143E (PS1/26 Appendix 1, p. 86) prescribes
  the documentation that must accompany any change requiring PRA permission — including
  (a) description of the change, its rationale and objective, (d) technical and process
  documents, (e) reports of the institution's independent review or validation,
  (f) confirmation of management body approval under Article 189(1), and (g) the
  quantitative impact on RWA / EL where applicable.
- **Annual confirmation (Art. 143(4)(a)):** Once permission is granted, the firm must
  "at least annually, submit details to the PRA of all rating systems that are included
  within the scope of its IRB permission" (PS1/26 Appendix 1, p. 83).

### Ongoing Obligations After Permission Is Granted

Permission is not a one-shot event. Three articles impose continuing duties on a firm
holding A-IRB permission for other general corporates:

| Article | Continuing obligation |
|---------|------------------------|
| Art. 143(3) | **Material changes** to the range of application of a rating system, or to the rating system itself, require fresh PRA permission. The thresholds for "material" are quantified in Art. 143C — primarily a 1.5% change in group-level RWA or a 15% change in the rating system's own RWA range. |
| Art. 143(4) | Annual rating-system inventory submission and notification of all non-material changes via Art. 143D. |
| Art. 146 | If the firm **ceases to comply** with the requirements, it must notify the PRA "promptly" and either (a) demonstrate that the non-compliance is immaterial, or (b) submit and execute a remediation plan. Where the non-compliance results in a material RWA / EL reduction, **post-model adjustments** under Art. 146(3) must offset the impact. |

> **Stress testing and model risk management** are not addressed substantively in
> Art. 143 itself. The PRA's stress-testing obligations for IRB models flow from
> Section 6 (Art. 177 — stress tests used in assessment of capital adequacy) and from
> SS1/23 *Model risk management principles for banks* (which sits outside the CRR
> rulebook but applies to all PRA-authorised firms running internal models). Both apply
> to A-IRB models for other general corporates as for any other IRB rating system.

### Worked Routing Example

A firm with the following position:

- Has F-IRB permission for the corporate exposure class.
- Has not previously held A-IRB permission for any corporate subclass.
- Wishes to use A-IRB on other general corporates only (revenue ≤ £440m, non-FSE).

Submits an **Art. 143(2B)** application (existing IRB permission → more sophisticated
approach within the same class) for the *other general corporates* subclass under
Art. 147(2)(c)(iii). The application must:

1. Demonstrate at least **three years** of own-LGD and own-CCF/EAD estimates broadly
   consistent with Section 6 for the corporate population in scope (Art. 145(2)).
2. Show that each rating system in the proposed perimeter satisfies all eight
   high-level requirements in Art. 144(1)(a)–(h), including the use test and an
   independent credit risk control unit.
3. Pass the Art. 143(2C) materiality test — non-compliance immaterial both per rating
   system and overall.
4. Include the Art. 143E documentation pack (rationale, scope, technical docs, validation
   reports, management body approval, quantitative impact).

Until PRA permission is granted, **the classifier continues to route the relevant
exposures via Art. 147A(1)(f)(iii) to the Foundation IRB Approach** — the calculator
treats absence of an A-IRB `model_permissions` record exactly as the regulation does:
F-IRB by default for other general corporates, A-IRB only with explicit permission.

> **Implementation note.** The calculator does **not** evaluate any of the substantive
> Art. 143(2A)/(2B) gating criteria above; it trusts the `model_permissions` table as
> evidence that the firm holds the relevant PRA permission. See [Permission
> Configuration](#permission-configuration) for the data model and
> [`hierarchy-classification.md`](../common/hierarchy-classification.md#basel-31-approach-restrictions-art-147a)
> for the runtime routing logic.

## Art. 143(6)–(8) — Overseas Model Approach

Basel 3.1 introduces a structured **Overseas Model Approach** at Art. 143(6), with a
transitional grandfathering rule at Art. 143(7) for firms that already had a CRR
Art. 143 permission for the same approach as at 31 December 2026, and an ongoing
compliance requirement at Art. 143(8). This is a UK-specific addition — **CRR
Art. 143 contained no equivalent structured Overseas Model Approach**; PS1/26
codifies the substantive conditions and the eligible scope.

The "Overseas Model Approach" is defined in PS1/26 Glossary p. 79 as:

> "the use of non-UK rating systems developed to meet non-UK IRB requirements, in
> the calculation of UK consolidated capital requirements in accordance with a
> permission granted under Article 143(6)."
>
> — PRA PS1/26 Appendix 1, p. 79 (Glossary, "Overseas Model Approach")

!!! warning "Plan paraphrase correction"
    `DOCS_IMPLEMENTATION_PLAN.md` item D4.60 paraphrased Art. 143(7) as "institutions
    may continue using IRB approaches previously approved by an overseas regulator,
    subject to PRA notification". The actual rule is narrower: Art. 143(7) is a
    **transitional grandfathering** for firms that **already held a PRA permission**
    under CRR Art. 143 (as it stood on 31 December 2026) to use the Overseas Model
    Approach. After 31 December 2026 those firms are deemed to hold a permission
    under the new Art. 143(6); a fresh PRA application is **not** required, and the
    mechanism is **not** a unilateral notification by the firm. The substantive
    permission framework for the Overseas Model Approach itself sits in Art. 143(6),
    and the eligible scope is restricted to retail and SME corporate exposures of
    overseas subsidiaries in equivalent jurisdictions, capped at 7.5% of group RWA
    and 7.5% of group exposure value.

### Art. 143(6) — Substantive Permission to Use the Overseas Model Approach

Verbatim opening of Art. 143(6) (PS1/26 Appendix 1, p. 83):

> "An institution may, with the prior permission of the PRA, use the Overseas Model
> Approach, if it can demonstrate to the satisfaction of the PRA that its use of
> the Overseas Model Approach complies with the following conditions: …"

Conditions (a)–(k) (paraphrased; verbatim text on p. 83):

| Condition | Requirement |
|-----------|-------------|
| **(a) Aggregate cap** | Risk-weighted exposure amounts calculated under the Overseas Model Approach must be **≤ 7.5% of group credit-risk RWA** *and* the aggregate exposure value must be **≤ 7.5% of the group's total exposure value**, both measured on a consolidated basis **before** the output floor. |
| **(b) Equivalent-jurisdiction subsidiary** | The rating system's scope is limited to exposures **located within a subsidiary in an equivalent jurisdiction** (as determined under CRR Art. 114(7)); the model has been **reviewed and approved by the relevant overseas regulator** for the institution to calculate its **local** capital requirements; and the institution actually uses that model to calculate local capital requirements in that jurisdiction. |
| **(c) Eligible exposure types** | Only one or both of: (i) **retail exposures**; or (ii) **exposures to SMEs in the corporate exposure class** (Art. 147(5)(a)(ii)). |
| **(d) Empirical estimation** | PD / LGD / CCF / EAD outputs are derived using historical experience and empirical evidence, not purely judgement; estimates plausible, intuitive, and based on material drivers. |
| **(e) Comparable population** | Estimation data population, lending standards, and other relevant characteristics are comparable with the institution's exposures. |
| **(f) Sufficient sample / data period** | Sample size and data history sufficient to give confidence in accuracy and robustness. |
| **(g) Risk differentiation** | Rating system gives meaningful differentiation of risk and produces accurate, consistent quantitative estimates. |
| **(h) Compensating adjustments** | Material weaknesses adequately compensated by parameter-estimate adjustments. |
| **(i) Internal governance** | Appropriate internal governance, with overseas-subsidiary senior management possessing a general understanding of the rating system and detailed comprehension of its management reports. |
| **(j) Validation** | Subject to an objective, consistent, accurate validation-of-internal-estimates process. |
| **(k) Use** | Used to inform credit-risk decisions. |

> Art. 143(6) is flagged in the PS1/26 note as "a permission under sections 144G
> and 192XC of FSMA to which Part 8 of the Capital Requirements Regulations
> applies" — i.e. the same FSMA / Capital Requirements Regulations Part 8
> permission framework that governs Art. 143(1) and Art. 143(2A)/(2B) applications
> (see [Art. 143(2A)/(2B) — Application Process](#application-process-ps126--fsma-framework)).

### Art. 143(7) — Transitional Grandfathering

Verbatim text (PS1/26 Appendix 1, p. 84):

> "Where, on 31 December 2026, an institution had PRA permission to use the
> Overseas Model Approach as part of its IRB permission under Article 143 of CRR,
> as that provision existed on 31 December 2026, the institution shall, after
> 31 December 2026, be treated as having permission under paragraph 6."
>
> — PRA PS1/26 Appendix 1, p. 84 (Article 143(7))

Plain-English summary:

- **Trigger**: the firm already held a **PRA-granted** permission under CRR
  Art. 143 (as that article stood at 31 December 2026) for use of the Overseas
  Model Approach as **part of its IRB permission**. The grandfathering pivots on
  an existing **PRA** permission, not on a standalone overseas-regulator approval.
- **Effect**: from 1 January 2027 onwards the firm is **automatically treated as
  having permission under Art. 143(6)**. No fresh application or PRA decision is
  required for continuity; the existing CRR permission is mapped across.
- **No firm-side notification step**: Art. 143(7) does **not** itself impose a
  notification obligation on the firm. The plan-item paraphrase ("subject to PRA
  notification") was incorrect — the rule is a deeming provision, not a
  notification gate.
- **Time-limit**: Art. 143(7) does not impose a sunset on the grandfathering. The
  firm continues to hold the deemed permission indefinitely, **provided** it
  satisfies the ongoing-compliance test in Art. 143(8) below. Material changes to
  the grandfathered rating system would still trigger Art. 143(3) / Art. 143C in
  the normal way.

### Art. 143(8) — Ongoing Compliance

Verbatim text (PS1/26 Appendix 1, p. 84):

> "An institution with PRA permission to use the Overseas Model Approach shall
> ensure that its use of the Overseas Model Approach complies with each of the
> conditions in paragraph 6 on an ongoing basis."
>
> — PRA PS1/26 Appendix 1, p. 84 (Article 143(8))

Art. 143(8) applies to **all** holders of an Overseas Model Approach permission —
both fresh Art. 143(6) permissions and Art. 143(7) grandfathered permissions. If
the firm ceases to comply with any of the (a)–(k) conditions (e.g. the aggregate
breaches the 7.5% cap, the overseas regulator withdraws its approval, the
subsidiary's jurisdiction loses CRR Art. 114(7) equivalence, the rating system
extends beyond retail / SME corporate scope), the firm is in breach of Art. 143(8)
and Art. 146 (cessation of compliance) is engaged — see the
[Ongoing Obligations](#ongoing-obligations-after-permission-is-granted) section
above for Art. 146 mechanics.

### Interaction With Other Articles

| Other rule | Interaction |
|------------|-------------|
| **Art. 143(1) / (2A) / (2B)** | The Overseas Model Approach is a **distinct** permission track. A firm without a UK Art. 143(2A)/(2B) IRB permission for the underlying exposure class can still hold an Art. 143(6) permission, provided the exposures sit in an equivalent-jurisdiction overseas subsidiary and fall within the retail / SME-corporate scope. The aggregate cap (7.5% of group RWA / 7.5% of group exposure value) is measured at the consolidated UK level. |
| **Art. 147A approach restrictions** | Art. 147A routes **UK-level** exposures by class. The Overseas Model Approach addresses overseas-subsidiary exposures consolidated up to the UK parent. Where Art. 147A would restrict an exposure class to F-IRB / SA at the UK level (e.g. institutions, FSEs, large corporates), the Overseas Model Approach does **not** override that restriction — Art. 143(6)(c) limits eligible scope to retail and SME corporate, which are unaffected by the headline Art. 147A(1)(b)/(e) F-IRB-only restrictions. |
| **Art. 150(1A) materiality / PPU** | The Art. 143(6)(a) **7.5% cap** is a separate ceiling specifically on the Overseas Model Approach, measured before the output floor. It is **not** the same as the Art. 150(1A) Permanent Partial Use materiality thresholds (which gate permanent SA use of an IRB-eligible class) — see [Permanent Partial Use Materiality Thresholds (Art. 150(1A))](#permanent-partial-use-materiality-thresholds-art-1501a) below. A firm could in principle be subject to both ceilings simultaneously. |
| **Output floor (Art. 92(5))** | The Art. 143(6)(a) 7.5% cap is measured **before** the output floor. The Overseas Model Approach RWAs themselves still feed into the IRB-RWA leg of the output-floor comparison. |

### CRR vs Basel 3.1 Delta

| Aspect | CRR Art. 143 (pre-1 Jan 2027) | PS1/26 Art. 143(6)–(8) |
|--------|-------------------------------|-------------------------|
| Concept of "Overseas Model Approach" | Not a defined / structured concept in the Article. Use of overseas-regulator-approved rating systems was negotiated case-by-case as part of a CRR Art. 143(2) IRB permission. | New, defined Glossary term; structured permission framework. |
| Eligible scope | Not codified | Retail + SME corporate only (Art. 143(6)(c)) |
| Aggregate cap | Not codified | 7.5% of group RWA *and* 7.5% of group exposure value, pre-output-floor (Art. 143(6)(a)) |
| Equivalent-jurisdiction subsidiary | Not codified | Required (Art. 143(6)(b)) |
| Substantive conditions | None codified | Eleven conditions (a)–(k) |
| Grandfathering | n/a | Art. 143(7) deems pre-existing CRR Art. 143 permissions across to Art. 143(6) automatically |
| Ongoing compliance test | Implicit via general Art. 144 / Art. 146 | Explicit at Art. 143(8) |

> **Implementation note.** The calculator does **not** currently model the
> Overseas Model Approach as a distinct approach type. Exposures of UK firms'
> overseas subsidiaries that are in scope of an Art. 143(6) / 143(7) permission
> are expected to be loaded through the standard `model_permissions` data
> source with the underlying retail / SME-corporate IRB approach
> (typically A-IRB for retail, A-IRB or F-IRB for SME corporate). The
> aggregate 7.5% cap in Art. 143(6)(a) and the Art. 143(8) ongoing-compliance
> test are **not** validated by the engine — they are firm-level governance
> obligations outside the per-exposure RWA pipeline. See [Permission
> Configuration](#permission-configuration).

## Permanent Partial Use Materiality Thresholds (Art. 150(1A))

Art. 150(1A) permits firms to use the Standardised Approach permanently for certain exposure
classes or types, subject to materiality thresholds:

| Threshold | Condition | Reference |
|-----------|-----------|-----------|
| Significantly lower capital | SA RWA < 95% of IRB RWA for the roll-out class | Art. 150(1A)(a) |
| Immaterial | SA RWA <= 5% of total group credit risk RWA | Art. 150(1A)(b) |
| Type-level immateriality | All SA types within the class <= 5% of IRB-eligible total group RWA | Art. 150(1A)(c) |
| Majority | SA must not exceed 50% of RWA within a roll-out class | Art. 150(1A)(d) |

!!! warning "Not Yet Implemented"
    Art. 150(1A) materiality thresholds are not enforced in the calculator. The calculator
    routes exposures based on Art. 147A approach restrictions and model permissions, but does
    not validate that the aggregate SA usage is within the above thresholds. This is a
    firm-level portfolio constraint, not an exposure-level calculation.

---

## Fallback Behaviour

When no model permission matches an exposure:

- The exposure is routed to the **Standardised Approach** (SA)
- No error is raised (this is expected for exposures not covered by IRB approval)
- The fallback is logged as a data quality note, not an error

---

## Key Scenarios

| Scenario ID | Description | Expected Routing |
|-------------|-------------|------------------|
| B31-M1 | Corporate with AIRB permission, revenue < £440m | A-IRB |
| B31-M2 | Corporate with AIRB permission, revenue > £440m (large corporate) | F-IRB (Art. 147A(1)(e)) |
| B31-M3 | Large FSE with total assets ≥ GBP 79bn (PS1/26 Glossary) | F-IRB (Art. 147A(1)(e)) |
| B31-M3a | Small FSE with total assets < GBP 79bn | F-IRB (Art. 147A(1)(e) — all FSEs, not just large) |
| B31-M4 | Institution with AIRB permission | F-IRB (Art. 147A(1)(b)) |
| B31-M5 | Equity exposure | SA (Art. 147A(1)(h)) |
| B31-M6 | Sovereign exposure (central government or central bank) | SA (Art. 147A(1)(a)) |
| B31-M7 | Quasi-sovereign exposure — PSE / RGLA / MDB (Art. 117) / Int'l Org (Art. 118) | SA (Art. 147A(1)(a)) |
| B31-M8 | IPRE with no A-IRB permission | Slotting (Art. 147A(1)(c)) |
| B31-M9 | HVCRE with no A-IRB permission | Slotting (Art. 147A(1)(c)) |
| B31-M10 | PF with A-IRB permission | A-IRB (no restriction) |
| B31-M11 | Corporate at £440m boundary (exact threshold) | F-IRB (≥ £440m triggers Art. 147A(1)(e)) |
| B31-M12 | Exposure with no model permission | SA (fallback) |

## Acceptance Tests

| Group | Scenarios | Tests | Pass Rate |
|-------|-----------|-------|-----------|
| B31-M: Model Permissions | M1–M12 | 16 | 100% (16/16) |
