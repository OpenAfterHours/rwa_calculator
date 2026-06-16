# IRB Approach Specification (Basel 3.1)

Basel 3.1 IRB Approach scope, entry conditions, roll-out classes, and approach-routing
rules introduced by PRA PS1/26.

This page is the canonical home for three distinct topics:

1. **Art. 144 entry conditions** — the high-level minimum requirements an institution
   must meet to obtain and retain IRB permission, including rating system coverage,
   ongoing validation, documentation, and the third-party-vendor obligation under
   Art. 144(1A).
2. **Art. 147B roll-out class enumeration** — the eight roll-out classes plus the
   non-Retail AIRB Modelling category that govern IRB scope-of-use reporting (COREP
   **OF 08.07**) and disclosure (Pillar 3 **UKB CR6-A**).
3. **Art. 179–184 risk parameter estimation standards** — the Section 6 Sub-Section 2
   minimum requirements that govern how an institution must estimate the PD, LGD and
   conversion factor / EAD inputs that the calculator engine then consumes. These are
   model-governance requirements: the calculator does not perform estimation, but
   applies regulatory floors and multipliers to the resulting model outputs.

Other reporting/disclosure pages cross-reference these enumerations; do not duplicate
the class list elsewhere.

**Regulatory Reference:** PRA PS1/26 Art. 143–143E, 144, 145, 147, 147A, 147B, 147C,
148, 150, 179, 180, 181, 181A–C, 182, 183, 184 (Annex E, Credit Risk: Internal
Ratings Based Approach (CRR) Part).
**Source PDF:** `docs/assets/ps126app1.pdf`, pp. 84–94 (entry conditions / roll-out)
and pp. 131–141 (risk parameter estimation).

---

## Overview

PRA PS1/26 splits the legacy CRR Art. 147 framework into four articles that separate
**classification**, **approach treatment**, **roll-out scope** and **roll-out
methodology**:

| Article | Topic | What it does |
|---------|-------|--------------|
| Art. 147 | Methodology to assign exposures to exposure classes and subclasses | Defines the exposure classes (a)–(g) plus (ea), with corporates split into 3 subclasses ((c)(i)/(ii)/(iii)) and retail split into 3 subclasses ((d)(i)/(ii)/(iii)). |
| Art. 147A | Treatment by exposure class and exposure subclass | Maps each exposure class / subclass to a permitted approach (SA, F-IRB, A-IRB, Slotting). See [Model Permissions](model-permissions.md). |
| Art. 147B | **Roll-out classes and categories** | Defines the **8 roll-out classes** and the **non-Retail AIRB Modelling roll-out category** that drive IRB scope-of-use reporting. |
| Art. 147C | Methodology for roll-out of the IRB Approach | Requires firms to implement IRB across all roll-out classes (subject to Art. 148 sequencing and Art. 150 permanent partial use). |

The roll-out class structure (Art. 147B) is **separate** from the exposure-class
structure (Art. 147(2)). Roll-out classes group exposures along the same boundaries
that drive approach permissions, but the regulatory basis is different — they exist
specifically to support sequenced IRB roll-out and permanent partial use under
Arts. 148–150.

---

## Art. 144 — High-Level Requirements for Using the IRB Approach (Entry Conditions)

PRA PS1/26 Art. 144 (ps126app1.pdf p. 86–87) sets out the **minimum requirements** an
institution must meet **before** the PRA grants IRB permission and **on an ongoing
basis** for as long as the permission is exercised. Failure on any limb of Art. 144(1)
calls into question the validity of the IRB permission and may force fallback to the
Standardised Approach under the Art. 147A routing waterfall — see
[Model Permissions](model-permissions.md).

The CRR equivalent is Art. 144(1) of the pre-revocation CRR; the substantive content is
preserved with PRA-specific drafting changes (notably the addition of (1A) for
third-party vendor rating systems and the relocation of the change-notification regime
to Arts. 143A–143E).

### Art. 144(1)(a)–(h) — Rating System Coverage Requirements

> An institution shall meet the following requirements when using the IRB Approach:

The following table reproduces each sub-paragraph verbatim from PS1/26 p. 87 and
identifies the operational obligation it imposes on the institution.

| Point | Verbatim wording (PS1/26 Art. 144(1)) | Operational obligation |
|-------|---------------------------------------|------------------------|
| **(a)** | "each of the institution's rating systems shall provide for a meaningful assessment of obligor and transaction characteristics, a meaningful differentiation of risk and accurate and consistent quantitative estimates of risk" | Each rating system must produce risk-meaningful, differentiated, accurate quantitative output. |
| **(b)** | "internal ratings and default and loss estimates used in the calculation of own funds requirements and associated systems and processes shall play an essential role in the risk management and decision-making process, and in the credit approval, internal capital allocation and corporate governance functions of the institution" | "Use test" — IRB ratings must drive credit approval, capital allocation and governance, not just regulatory reporting. |
| **(c)** | "the institution has a credit risk control unit responsible for each rating system that is appropriately independent and free from undue influence" | Independent credit risk control unit per rating system. |
| **(d)** | "the institution collects and stores all relevant data to provide effective support to its credit risk measurement and management process" | Data collection / retention sufficient to support the rating system. |
| **(e)** | "the institution documents each rating system and the rationale for their design, and validates each rating system" | **Documentation standards** — each rating system documented, design rationale recorded, validated. |
| **(f)** | "the institution has validated each rating system during an appropriate time period prior to the permission to use each rating system, has assessed during this time period whether each rating system is suited to the range of application of each rating system, and has made necessary changes to each rating system following its assessment" | **Pre-permission validation** — validation during a pre-permission window plus suitability assessment for the range of application, with corrective changes implemented. Reads alongside Art. 145 prior-experience (3 years). |
| **(g)** | "the institution has calculated under the IRB Approach the own funds requirements resulting from its risk parameters estimates and is able to submit the reporting as required by Chapter 4 of Reporting (CRR) Part Article 430" | IRB own-funds calculation produced and reportable under Art. 430. |
| **(h)** | "the institution has assigned and continues to assign each exposure in the range of application of a rating system to a rating grade or pool of each rating system" | Continuous, complete grade/pool assignment of every exposure within the range of application. |

!!! info "Ongoing validation lives in Section 6, not Art. 144(1)(f)"
    Art. 144(1)(f) addresses **pre-permission** validation (the time period prior to
    grant). The **on-going validation** obligation — annual back-testing, benchmarking,
    PD/LGD/CCF performance monitoring — sits in PS1/26 Section 6 (Arts. 174–191) and is
    the regulatory hook for the COREP back-testing template **C 08.05 / OF 08.05**.
    See [COREP Reporting — C 08.05 / OF 08.05](../../features/corep-reporting.md#c-0805-of-0805-cr-irb-pd-back-testing).

!!! info "Documentation standards in Art. 144(1)(e)"
    "Documents each rating system and the rationale for their design" is the
    **single-rating-system** documentation hook. Documentation of **changes** to a
    rating system is a separate regime under Art. 143E (see below). Documentation of
    the institution's **overall risk management** sits in Art. 189.

### Art. 144(1A) — Third-Party Vendor Rating Systems

PS1/26 introduces an explicit obligation (no direct CRR equivalent) covering rating
systems or models purchased from a third-party vendor:

> Where the institution has implemented a rating system, or model used within a rating
> system, that it has purchased from a third-party vendor, the institution shall
> ensure that the rating system or model, as the case may be, and their use by the
> institution, complies with this Part.

This means **the institution remains responsible** for compliance of any vendor
rating system or sub-model with the entire IRB Part — including all of Art. 144(1)(a)
through (h), Section 6 estimation requirements, and the change-management regime in
Arts. 143A–143E.

### Art. 144(2) — Provision Left Blank

> [Note: Provision left blank]

PS1/26 has deliberately left Art. 144(2) blank. The pre-revocation CRR Art. 144(2)
provided for the EBA/PRA to issue regulatory technical standards on the assessment
methodology — that mandate has been replaced by the PRA's direct rule-making in
Arts. 143A–143E (model change classification and notification) and Arts. 174–191
(rating system minimum requirements in detail).

### Art. 144(2)-style Notification on Significant Model Changes — Now in Arts. 143A–143E

The **notification obligation on significant model changes** that historically sat
under the Art. 144 RTS framework is, under PS1/26, distributed across the following
articles (ps126app1.pdf pp. 84–86):

| Article | Topic | Trigger |
|---------|-------|---------|
| **Art. 143A** | Categories of changes | Each change is classified as (a) **material** (PRA permission required) or (b) **other** (notification required). The other-change category further splits into "before implementation" and "after implementation". |
| **Art. 143B** | Principles of classification | Most-recent data; representative sampling acceptable; no splitting one material change into smaller parts; assign to the highest potential materiality in case of doubt. |
| **Art. 143C** | Material changes | A change is **material** (PRA permission required) if it (i) falls within Appendix 2, Part 1 Section 1 or Part 2 Section 1, or (ii) decreases consolidated/own RWA by **≥ 1.5%**, or (iii) decreases the rating system's range-of-application RWA by **≥ 15%**. |
| **Art. 143D** | Non-material changes — notification | Changes within Appendix 2, Part 1 Section 2 / Part 2 Section 2, **or** changes that decrease range-of-application RWA by **≥ 5%**, must be notified at least **two months before implementation**. All other non-material changes must be notified **after implementation, at least annually**. |
| **Art. 143E** | Documentation of changes | Permission applications and notifications must include (a) description / rationale, (b) implementation date, (c) scope, (d) technical/process documentation, (e) independent review or validation reports, (f) management body / Art. 189(1) committee approval evidence, (g) quantitative impact where applicable. |

!!! warning "Materiality thresholds are mechanical"
    The 1.5% (consolidated RWA), 15% (rating-system RWA) and 5% (range-of-application
    RWA) thresholds in Arts. 143C/143D are **mechanical decreases** computed at the
    same point in time on a constant exposure set (Art. 143C(2), 143D(2)). They are
    **not** subject to materiality judgement — a change that breaches the threshold
    requires the corresponding permission or notification regardless of the
    institution's own view.

### Relationship to Other Entry-Condition Articles

Art. 144 is the high-level entry test. It interacts with the following adjacent
articles (PS1/26 Art. 145, 146, 147A) — all of which must be satisfied for a valid
IRB permission:

| Article | Topic | Entry-condition role |
|---------|-------|----------------------|
| **Art. 145** | Prior experience | At least **three years** of broadly-IRB-compliant rating system use prior to qualification (and three years of own LGD / CCF / EAD estimation prior to AIRB qualification for non-retail). |
| **Art. 146** | Measures to be taken when requirements are no longer met | If Art. 144 (or Sections 2–6) requirements are breached, the institution must present a remediation plan, accelerate it where appropriate, or accept SA fallback. |
| **Art. 147A** | Approach restrictions | Even where Art. 144 is satisfied, IRB cannot be applied to populations excluded by Art. 147A — see [Model Permissions](model-permissions.md). |

### Cross-References

- **Roll-out scope (downstream of valid Art. 144 permission):** see the
  **Art. 147B — IRB Roll-Out Classes and Categories** section below on this page.
- **Approach restrictions (which exposures can use IRB at all):** see
  [Model Permissions](model-permissions.md).
- **Risk parameter estimation standards (Art. 179–184):** see the
  **Risk Parameter Estimation Standards (Art. 179–184)** section below on this page.
- **Detailed rating system minimum requirements (Art. 174–178, Art. 185–191):**
  the remainder of Section 6 of the IRB Part — partially covered (Arts. 179–184
  expanded below; Arts. 174–178 and Arts. 185–191 currently forward references).
- **COREP back-testing of rating systems:** see
  [C 08.05 / OF 08.05](../../features/corep-reporting.md#c-0805-of-0805-cr-irb-pd-back-testing).

---

## Art. 147(2) Exposure Classes (Reference)

Art. 147(2) requires an institution to assign each exposure to one of the following
classes / subclasses (PRA PS1/26 ps126app1.pdf p. 88):

| Point | Exposure class / subclass |
|-------|---------------------------|
| (a) | Exposures to central governments, central banks or quasi-sovereigns |
| (b) | Exposures to institutions |
| (c)(i) | Corporates — specialised lending exposures |
| (c)(ii) | Corporates — financial corporates and large corporates |
| (c)(iii) | Corporates — other general corporates |
| (d)(i) | Retail — qualifying revolving retail exposures (QRRE) |
| (d)(ii) | Retail — retail exposures secured by residential immovable property |
| (d)(iii) | Retail — other retail |
| (e) | Equity exposures |
| (ea) | Exposures in the form of units or shares in a CIU |
| (f) | Items representing securitisation positions |
| (g) | Other non-credit obligation assets |

Specialised lending under (c)(i) is further sub-divided into **object finance (OF)**,
**project finance (PF)**, **commodities finance (CF)**, **IPRE** and **HVCRE**
exposures (Art. 147(4B), p. 90). HVCRE takes priority over IPRE where an exposure
meets both definitions.

---

## Art. 147B — IRB Roll-Out Classes and Categories

PRA PS1/26 Art. 147B (ps126app1.pdf p. 93) defines the population of exposures that
an institution with IRB permission must implement IRB for, organised into **eight
roll-out classes** (Art. 147B(1)) and one **non-Retail AIRB Modelling roll-out
category** (Art. 147B(2)).

### Art. 147B(1) — Roll-Out Classes (Eight Classes)

Each of the following is a roll-out class applicable for the IRB Approach:

| Roll-out class | Definition (verbatim) | Maps to Art. 147(2) point | Permitted approaches under Art. 147A |
|----------------|-----------------------|---------------------------|--------------------------------------|
| **(a)** Institutions | Exposures to institutions as set out in point (b) of Art. 147(2). | (b) | F-IRB (default); SA only with Art. 148/150 permission. |
| **(b)** Specialised lending | Specialised lending exposures as set out in point (c)(i) of Art. 147(2). | (c)(i) | IPRE/HVCRE: SA or Slotting only; OF/PF/CF: SA, F-IRB, A-IRB or Slotting (subject to Art. 143(2A)/(2B) permission). |
| **(c)** Corporate purchased receivables | Exposures to purchased receivables within the corporate exposure class as set out in point (c) of Art. 147(2). | (c) | Approach inherited from the underlying corporate sub-class (FSE/large vs. other general). |
| **(d)** Financial corporates, large corporates and other general corporates | Exposures to financial corporates and large corporates and to other general corporates as set out in points (c)(ii) and (c)(iii) of Art. 147(2). | (c)(ii) and (c)(iii) | (c)(ii): F-IRB only (or SA with permission). (c)(iii): F-IRB default; A-IRB only with Art. 143(2A)/(2B) permission. |
| **(e)** Qualifying revolving retail exposures (QRRE) | Qualifying revolving retail exposures as set out in point (d)(i) of Art. 147(2). | (d)(i) | A-IRB (or SA with permission). |
| **(f)** Retail RRE | Retail exposures secured by residential property as set out in point (d)(ii) of Art. 147(2). | (d)(ii) | A-IRB (or SA with permission). |
| **(g)** Retail purchased receivables | Exposures to purchased receivables within the retail exposures exposure class as set out in point (d) of Art. 147(2). | (d) | A-IRB (or SA with permission). |
| **(h)** Other retail | Exposures to other retail as set out in point (d)(iii) of Art. 147(2). | (d)(iii) | A-IRB (or SA with permission). |

!!! info "Eight roll-out classes — count is exact"
    Art. 147B(1) enumerates exactly **eight** roll-out classes, lettered (a) through (h).
    Reporting/disclosure templates that pivot rows on roll-out class (OF 08.07,
    UKB CR6-A) should therefore expose **eight** roll-out-class rows. Earlier CRR
    templates that bucketed by Art. 147(2) exposure class produced different row
    counts because the underlying classification was different.

!!! note "Exposure classes outside the IRB roll-out scope"
    Several Art. 147(2) classes are **not** roll-out classes because they cannot use
    IRB at all under PS1/26 Art. 147A:

    - Art. 147(2)(a) — central governments / central banks / quasi-sovereigns:
      mandatorily SA (Art. 147A(1)(a)).
    - Art. 147(2)(e) — equity: mandatorily SA, IRB equity removed
      (Art. 147A(1)(h); Art. 155 left blank). See [Equity Approach](equity-approach.md).
    - Art. 147(2)(ea) — CIU units/shares: handled under Art. 152 / 158(4)
      (Art. 147A(1)(i)).
    - Art. 147(2)(f) — securitisation positions: handled under the securitisation
      framework (Art. 147A(1)(j)).
    - Art. 147(2)(g) — other non-credit obligation assets: handled under
      Art. 156 / 158(3) / 168 (Art. 147A(1)(k)).

    These five classes therefore do not appear as roll-out classes in OF 08.07 /
    UKB CR6-A, and do not contribute to Art. 148 sequencing or Art. 150(1A)
    materiality testing.

### Art. 147B(2) — Non-Retail AIRB Modelling Roll-Out Category

Art. 147B(2) defines a **single** category that governs A-IRB modelling roll-out
within the non-retail population (ps126app1.pdf p. 93):

> The non-Retail AIRB Modelling roll-out category applicable for the IRB Approach is:
>
> (a) with the exception of IPRE exposures and HVCRE exposures, exposures to
>     specialised lending as set out in point (c)(i) of Article 147(2);
>
> (b) exposures to other general corporates, as set out in point (c)(iii) of
>     Article 147(2).

| Component | Population | Maps to Art. 147(2) point |
|-----------|------------|---------------------------|
| (a) | Specialised lending **excluding** IPRE and HVCRE — i.e. object finance, project finance, commodities finance only. | (c)(i), restricted |
| (b) | Other general corporates (revenue ≤ £440m, non-FSE). | (c)(iii) |

This single category is the **only** non-retail population for which A-IRB modelling
is permitted under PS1/26 (subject to Art. 143(2A)/(2B) permission). Under
Art. 147C(2), an institution holding A-IRB permission for any type of exposure
within this category must implement, for all exposures in the category, one of:

1. the Advanced IRB Approach;
2. the Slotting Approach (only for the specialised lending population in
   Art. 147B(2)(a)); or
3. the Standardised Approach,

unless it has been granted permission under Art. 150(4) to permanently use F-IRB.

!!! warning "IPRE and HVCRE are excluded from the non-Retail AIRB Modelling category"
    Art. 147B(2)(a) explicitly carves out IPRE and HVCRE exposures. Under
    Art. 147A(1)(c), IPRE and HVCRE exposures are routed to **SA or Slotting only**
    — A-IRB is not available for these populations even where the institution holds
    a general A-IRB permission. See [Slotting Approach](slotting-approach.md).

---

## Roll-Out Class to Exposure Class Mapping (Summary)

The eight roll-out classes (Art. 147B(1)) cover the IRB-eligible portion of the
Art. 147(2) population. The mapping is exact — each roll-out class corresponds to
one or more Art. 147(2) points:

| Art. 147B(1) roll-out class | Art. 147(2) source | Approach treatment (Art. 147A) |
|------------------------------|--------------------|-----------------------------|
| (a) Institutions | (b) | F-IRB only (or SA with permission) |
| (b) Specialised lending | (c)(i) | IPRE/HVCRE → Slotting/SA; OF/PF/CF → A-IRB / F-IRB / Slotting / SA |
| (c) Corporate purchased receivables | (c) | Inherits sub-class treatment |
| (d) Fin. corporates, large corporates and other general corporates | (c)(ii) + (c)(iii) | (c)(ii) F-IRB only; (c)(iii) F-IRB default, A-IRB by permission |
| (e) QRRE | (d)(i) | A-IRB (or SA with permission) |
| (f) Retail RRE | (d)(ii) | A-IRB (or SA with permission) |
| (g) Retail purchased receivables | (d) | A-IRB (or SA with permission) |
| (h) Other retail | (d)(iii) | A-IRB (or SA with permission) |

For the full Art. 147A approach restriction matrix (including LFSE thresholds and
the FSE / large-corporate F-IRB-only rule), see
[Model Permissions](model-permissions.md#art-147a-approach-restrictions).

---

## Where Roll-Out Classes Are Consumed

The Art. 147B(1) eight-class enumeration is the row structure for the following
templates. Those template specs cross-reference this page rather than redefining
the classes:

| Template | Type | What roll-out classes drive |
|----------|------|-----------------------------|
| **OF 08.07** | COREP — IRB scope of use | Rows 0180–0250 are bucketed by roll-out class (Basel 3.1 restructure from CRR exposure-class rows). Materiality threshold (col 0160) is assessed per roll-out class under Art. 150(1A)(c). See [COREP Reporting](../../features/corep-reporting.md) and [Reporting Differences — C 08.07 / OF 08.07](../../framework-comparison/reporting-differences.md). |
| **UKB CR6-A** | Pillar 3 — Scope of IRB/SA use | All five disclosure columns (a–e) are computed per roll-out class. See [Disclosure Differences — CR6-A](../../framework-comparison/disclosure-differences.md). |

The corresponding Art. 150(1A) **permanent partial use** materiality thresholds —
which trigger SA-permission permission under Art. 150(1)(e) — are evaluated per
roll-out class:

| Threshold | Definition | Reference |
|-----------|------------|-----------|
| Significantly lower capital | SA RWA must not be < 95% of IRB RWA for the roll-out class | Art. 150(1A)(a) |
| Cannot reasonably model | SA permission only where IRB modelling is not feasible for the roll-out class | Art. 150(1A)(b) |
| Immaterial | Roll-out class falls below materiality threshold | Art. 150(1A)(c) |
| Majority | SA must not exceed 50% of RWA within a roll-out class | Art. 150(1A)(d) |

See [Model Permissions — Permanent Partial Use Materiality Thresholds](model-permissions.md#permanent-partial-use-materiality-thresholds-art-1501a).

---

## Art. 147C — Roll-Out Methodology (Cross-Reference)

Art. 147C ties Art. 147B to the actual IRB implementation obligation (ps126app1.pdf
p. 93):

- **Art. 147C(1)**: An institution with IRB permission under Art. 143 must implement
  the IRB Approach for **all** exposures in the eight Art. 147B(1) roll-out classes,
  except where it has received permanent SA permission under
  Art. 150(1)(e), (k) or (l).
- **Art. 147C(2)**: An institution with A-IRB permission for any exposure type in
  the Art. 147B(2) non-Retail AIRB Modelling roll-out category must implement, for
  **all** exposures in that category, one of A-IRB / Slotting / SA — unless granted
  Art. 150(4) permanent-partial-use permission for F-IRB.

Sequenced roll-out across roll-out classes (Art. 147B(1)) or types-of-exposures
within a roll-out class is permitted under Art. 148(1), subject to PRA prior
permission. Sequenced A-IRB roll-out within the Art. 147B(2) category is permitted
under Art. 148(1A).

---

## Risk Parameter Estimation Standards (Art. 179–184)

PRA PS1/26 Section 6 Sub-Section 2 (ps126app1.pdf pp. 131–141) sets out the minimum
requirements an institution must satisfy when **estimating** the PD, LGD, conversion
factor and EAD inputs that drive the IRB risk-weight formulas. These are
**model-governance** requirements imposed on the institution; they are not
calculation steps performed by the engine. The calculator consumes the resulting
model outputs and then applies regulatory floors, multipliers and downturn /
conservatism overlays at the relevant pipeline stage.

!!! info "Estimation lives in the institution's model framework, not the calculator"
    Articles 179–184 govern how an institution must derive its own estimates of PD,
    LGD, conversion factor and EAD: data length, long-run averaging, conservatism
    margins, downturn treatment, dilution adjustments for purchased receivables.
    The calculator is downstream of this — `loan.pd`, `loan.lgd` and
    `facility.ccf` arrive on the input bundle as already-estimated values produced
    by the firm's rating systems. The calculator's job is then to apply the
    regulatory floors and multipliers in
    `engine/irb/adjustments.py` and `engine/irb/formulas.py` (PD floors per
    Art. 163(1), LGD floors per Art. 161(5)/164(4), FI correlation multiplier per
    Art. 153(2), CCF floor per CRE32.27).

### Article 179 — Overall Requirements for Estimates

> Quantification of risk parameters PD, LGD, conversion factor / EAD and EL —
> general standards applicable to all rating systems and all exposure classes.

| Limb | Requirement | Operational obligation |
|------|-------------|------------------------|
| 1(a) | Estimates shall incorporate all relevant data, information and methods, derived using both historical experience and empirical evidence — not based purely on judgement. | Estimates must be plausible, intuitive, driven by material risk parameters; **the less data, the more conservative** the estimation. |
| 1(aa) | LGD estimates **shall not** take account of recoveries from guarantees, credit derivatives or other support arrangements **except** where recognised under the LGD Adjustment Method (Art. 183). | Guarantee/CD recoveries are routed through the LGD Adjustment Method (LGD-AM) only — see Art. 183 below. |
| 1(ab) | Existence of collateral shall not be taken into account except where recognised when applying the **LGD Modelling Collateral Method** (LGD-MCM). | Collateral effect on LGD requires LGD-MCM permission (Art. 169B). |
| 1(b) | Institution shall be able to provide a breakdown of loss experience by drivers; estimates shall be **representative of long-run experience**. | Long-run representativeness of all estimates (PD, LGD, CF/EAD). |
| 1(c) | Changes in lending practice or recovery process over the observation period shall be reflected; estimates shall reflect technical advances and new data; **annual review minimum**. | Annual estimate review obligation. |
| 1(d) | Population, lending standards and economic / market conditions in the data shall be **comparable** with the institution's exposures and standards. Sample size and data period shall be sufficient for accuracy. | Representativeness of the data set against the institution's current portfolio. |
| 1(e) | For purchased receivables, estimates shall reflect **all relevant information** available to the purchasing institution, including data from the seller, the institution itself, or external sources. | Purchaser must independently evaluate seller-provided data — see Art. 184. |
| 1(f) | Institution shall add a **margin of conservatism** related to the expected range of estimation errors. The larger the expected error or the less satisfactory the data/methods, the larger the margin. | Margin of Conservatism (MoC) — sized to data quality and methodological uncertainty. |
| 1A | Pre-2007 data: with PRA permission and demonstrated equivalence to the Art. 178 default definition, the data-standards requirements may be disapplied for the legacy data only. | Specific permission under FSMA s. 144G / 192XC. |
| 2(a)–(e) | Pooled-data requirements: similar rating systems and criteria across the pool; pool representative of the portfolio; consistent use over time; institution remains responsible for system integrity; sufficient in-house understanding to monitor and audit. | Governance overlay when external pooled data is used. |

**Calculator handover:** the calculator does not enforce Art. 179 directly. Pipeline
inputs (`loan.pd`, `loan.lgd`, `facility.ccf`) are produced by the institution's
rating systems and arrive already-MoC-loaded. The calculator applies regulatory
floors at the IRB stage — see `engine/irb/adjustments.py`.

**PDF citation:** ps126app1.pdf p. 131–132.

### Article 180 — Requirements Specific to PD Estimates

> PD-specific estimation requirements, split between **corporate and institution**
> exposures (Art. 180(1)(a)–(h)) and **retail** exposures (Art. 180(2)(a)–(f)).

#### Art. 180(1) — Corporate / Institution PD

| Limb | Requirement |
|------|-------------|
| 1(a) | Estimate PDs by obligor grade from **long-run averages of one-year default rates** over a representative mix of good and bad economic periods. Highly-leveraged or traded-asset-heavy obligor PDs shall reflect **stressed-volatility** asset performance. |
| 1(b) | For **purchased corporate receivables**, EL by obligor grade may be estimated from long-run averages of realised default rates. |
| 1(c) | Where long-run PD/LGD for purchased corporate receivables is derived from EL plus a separate PD or LGD estimate, the total-loss process shall meet PD/LGD overall standards and be consistent with the LGD concept in Art. 181(1)(a). |
| 1(d) | PD techniques may only be used **with supporting analysis**; judgement is required when combining techniques and adjusting for limitations. |
| 1(e) | Internal-default-experience-based PDs shall reflect underwriting standards and rating-system differences vs. the data; **changes in underwriting or the rating system trigger an additional MoC**. |
| 1(f) | Mapping internal grades to ECAI scales requires a comparison of internal vs. external rating criteria and common-obligor ratings. Biases or inconsistencies shall be avoided. The external scale shall be oriented to **default risk only** (not transaction characteristics). The mapping basis shall be documented. |
| 1(g) | Statistical default-prediction PDs may be estimated as the **count-weighted average** of default-probability estimates within a grade; the model shall meet Art. 174 standards. |
| **1(h)** | **Minimum 5-year historical observation period** for at least one source. Longer periods shall be used if available and relevant. The data shall include **a representative mix of good and bad years** from the relevant economic cycle. |

#### Art. 180(2) — Retail PD

| Limb | Requirement |
|------|-------------|
| 2(a) | Estimate PDs by obligor grade, facility grade or pool from **long-run averages of one-year default rates** over a representative mix of good and bad economic periods. |
| 2(b) | PD estimates may also be derived from a total-loss estimate and an appropriate LGD estimate. |
| 2(c) | Internal data shall be the **primary source**. External / pooled data or statistical models may be used only if there are strong links between (i) the institution's grade-assignment process and the external source's process, **and** (ii) the institution's internal risk profile and the external data composition. |
| 2(d) | If long-run PD/LGD is derived from total losses + an appropriate PD or LGD, the total-loss process shall meet PD/LGD standards and be consistent with the LGD concept in Art. 181(1)(a). |
| **2(e)** | **Minimum 5-year historical observation period** for at least one source. Longer periods shall be used if available and relevant. The data shall include a representative mix of good and bad years. |
| 2(f) | Institution shall identify and analyse **seasoning effects** — expected changes in risk parameters over the life of the credit exposure. |
| 2 (final) | For **purchased retail receivables**, external and internal reference data may be used; the institution shall use all relevant data sources as points of comparison. |

!!! info "Five-year minimum is the floor, not the target"
    Art. 180(1)(h) and 180(2)(e) require a **minimum** of 5 years of data for at
    least one source. If a longer relevant data period is available, it **must** be
    used — there is no permission to truncate. This contrasts with Art. 181(1)(j)
    and Art. 182(2) for non-retail LGD/CF/EAD, which start at 5 years and **ramp
    to 7 years** post-implementation.

**Calculator handover:** PDs supplied to the calculator are downstream of Art. 180.
The calculator then applies the **differentiated PD floors** introduced by Basel
3.1 — Art. 163(1) (corporate 0.05%, retail mortgage 0.10%, retail other 0.05%, QRRE
revolvers 0.10%, QRRE transactors 0.05%) — implemented in
`engine/irb/adjustments.py`.

**PDF citation:** ps126app1.pdf p. 132–134.

### Article 181 — Requirements Specific to LGD Estimates

> LGD-specific estimation requirements, including **downturn LGD** (Art. 181(1)(b))
> and the LGD-in-default treatment for already-defaulted exposures (Art. 181(1)(h)).

#### Art. 181(1) — General LGD Requirements

| Limb | Requirement |
|------|-------------|
| 1(a) | Estimate LGDs by facility grade or pool on the basis of the **default-weighted average of realised LGDs** by facility grade or pool, using all observed defaults within the data sources. |
| **1(b)(i)** | Institution shall use LGD estimates **appropriate for an economic downturn** if those are more conservative than the long-run average. |
| 1(b)(ii) | If a rating system uses risk drivers sensitive to the economic cycle, the institution shall (1) analyse the difference in exposure distribution over facility grades / pools / continuous-scale intervals between the current portfolio before and during the downturn period, and (2) where a substantial difference is identified, apply **non-negative adjustments** to its downturn LGD estimates to limit the cycle impact on RWA. |
| 1(c) | The institution shall consider **interdependence between obligor risk and collateral / collateral-provider risk**; significant dependence is treated conservatively. |
| 1(d) | **Currency mismatches** between the underlying obligation and the collateral shall be treated conservatively in the LGD assessment. |
| 1(e) | Where LGD estimates take account of collateral under the **LGD-MCM** (and the institution is not applying Art. 169B), estimates shall not rely solely on collateral market value. They shall reflect the institution's potential **inability to expeditiously gain control and liquidate** the collateral. |
| 1(h)(i) | For exposures **already in default**, the LGD-in-default shall reflect downturn conditions where downturn LGD-in-default estimates are more conservative than the long-run average defaulted LGD. |
| 1(h)(ii) | LGD-in-default shall be **further increased** above the level in 1(h)(i) where necessary to ensure that, for each exposure, the difference between the LGD estimate and Best-Estimate Expected Loss (BEEL) covers the institution's estimate of additional unexpected losses during the **recovery period** (default date to final liquidation). |
| 1(i) | Capitalised unpaid late fees shall be added to both the exposure measure and the loss measure. |
| **1(j)** | **Corporate LGD** estimates shall be based on **a minimum of 5 years**, **increasing by one year each year after implementation until a minimum of 7 years is reached**, for at least one source. Longer relevant periods shall be used. |
| 1 (final) | Institution may reflect **additional drawings post-default** in its LGD estimates. |

#### Art. 181(2) — Retail LGD

| Limb | Requirement |
|------|-------------|
| 2(a) | Retail LGDs may be derived from realised losses and appropriate PD estimates. |
| 2(c) | For **purchased retail receivables**, external and internal reference data may be used to estimate LGDs. |
| **2 (final)** | **Retail LGD** estimates shall be based on **a minimum of 5 years** of data. (No ramp to 7 years.) |

#### Art. 181A–C — Economic Downturn Specification

Art. 181A–C (ps126app1.pdf pp. 135–138) operationalises the "economic downturn"
concept used in Art. 181(1)(b) and Art. 182(1)(b):

| Article | Topic | Key requirement |
|---------|-------|-----------------|
| **Art. 181A** | Nature, severity and duration of an economic downturn | Identify a downturn for **each type of exposures**, characterised by a **relevant indicator set** (per 181B). Severity = **most severe 12-month value** observed within the **applicable time-span** (per 181C(1)). Duration = peaks/troughs covering that severity (per 181C(2)). |
| **Art. 181B** | Relevant indicator set | Mandatory base set: **GDP**, **unemployment rate**, externally-provided aggregate default rates and credit losses (where available). Additional sector-specific indicators by exposure type (corporates, SME retail, RRE/CRE-secured, retail other, specialised lending sub-types, institutions). |
| **Art. 181C** | Applicable time-span and downturn duration | Historical time-span shall be sufficient to be representative of likely future variability and **at any rate at least 20 years**. Duration determined by peak/trough coverage rules in 181C(2)(a)–(d). |

!!! warning "20-year time-span is a hard minimum for downturn analysis"
    Art. 181C(1) requires the historical time-span used to identify the **most
    severe 12-month value** of each economic indicator to be **at least 20 years**,
    independent of the 5-year / 7-year LGD data-history requirement in
    Art. 181(1)(j). The two horizons serve different purposes: the 5/7-year
    horizon governs the loss data underpinning the LGD estimate itself; the
    20-year horizon governs the macroeconomic indicator series used to identify
    when a downturn occurred.

**Calculator handover:** downturn LGD outputs from the institution's model framework
arrive on the input bundle as `loan.lgd`. The calculator then applies the Basel 3.1
**A-IRB LGD floors** at the relevant pipeline stage — Art. 161(5) / 164(4),
implemented in `engine/irb/adjustments.py`.

**PDF citation:** ps126app1.pdf p. 134–138.

### Article 182 — Requirements Specific to Conversion Factor and EAD Estimates

> CCF / EAD estimation requirements, structured similarly to Art. 181 with a
> downturn overlay and asymmetric data-history requirements (corporate vs. retail).

| Limb | Requirement |
|------|-------------|
| 1(a) | Estimate conversion factors / EADs by facility grade or pool on the basis of the **default-weighted average of realised CFs/EADs at default**, using all observed defaults within the data sources. |
| 1(b)(i) | Use CF/EAD estimates **appropriate for an economic downturn** where they are more conservative than the long-run average. |
| 1(b)(ii) | If a rating system uses cycle-sensitive risk drivers, the institution shall analyse pre-downturn vs. downturn distribution shifts and apply **non-negative adjustments** to downturn CF/EAD estimates to limit the cycle impact. |
| 1(c) | A **larger MoC** shall be incorporated where stronger positive correlation can reasonably be expected between default frequency and the magnitude of the CF/EAD. |
| 1(ca) | CF/EAD estimates shall reflect the **possibility of additional drawings**: (i) up to default-event trigger and (ii) post-default where not already reflected in LGD estimates. |
| 1(d) | The institution shall consider its policies on **account monitoring and payment processing**, and its ability/willingness to prevent further drawings on covenant violations or technical default. |
| 1(e) | Adequate systems and procedures shall monitor facility amounts, current outstandings vs. committed lines and changes in outstandings per obligor and per grade. **Daily** monitoring of outstanding balances. |
| 1(f) | Different CF/EAD estimates for risk-weight calculation vs. internal purposes shall be documented and reasonable. |
| 1(g) | Where the institution estimates **CFs**, these shall reflect realised CFs **measured 12 months prior to the month of default**; estimates shall use observed obligor and facility characteristics available 12 months pre-default. |
| **2** | **Corporate / institution CF/EAD**: minimum **5 years**, **increasing by one year each year after implementation until a minimum of 7 years is reached**, for at least one source. |
| **3** | **Retail CF/EAD**: minimum **5 years**. (No ramp.) |

**Calculator handover:** own-estimate CCFs supplied to the calculator are subject to
the **CCF floor of 50% of the SA CCF** (CRE32.27 / Basel 3.1 A-IRB floor),
implemented in `engine/irb/adjustments.py`. Own-estimate CCFs are permitted only
for **revolving facilities** under Basel 3.1; all other items use SA CCFs (see
[Credit Conversion Factors](../../framework-comparison/key-differences.md#credit-conversion-factors)
for the cross-reference).

**PDF citation:** ps126app1.pdf p. 138–139.

### Article 183 — Requirements for Applying the LGD Adjustment Method (LGD-AM) for Unfunded Credit Protection

> Standards for using guarantees and single-name credit derivatives as eligible
> unfunded credit protection under the LGD-AM (the alternative to A-IRB own-LGD-
> through-modelling under the LGD-MCM).

| Paragraph | Requirement |
|-----------|-------------|
| 1 | LGD-AM may take account of unfunded credit protection only where 1A is met **and** for guarantees / single-name credit derivatives the following requirements are satisfied: (a) clearly specified guarantor-eligibility criteria; (b) **non-retail guarantors assigned to obligor grades** under Arts. 171–173; (c) **retail guarantors assigned to grades / pools** as part of credit approval under Arts. 171–173. |
| 1A | Eligibility of guarantees / credit derivatives (including first-to-default CDs): (a) credit protection evidenced **in writing**; (b) no clause permitting the protection provider to **unilaterally cancel or modify** the protection adversely to the lender; (c) protection is not a **second-to-default or higher nth-to-default** credit derivative. |
| 2 | LGD-AM users shall have clearly specified criteria for adjusting facility grades or LGD estimates. Criteria shall be plausible and intuitive and shall address: protection provider's **ability and willingness to perform**, **likely timing** of payments, the **degree of correlation** between provider performance and obligor repayment ability, and the **residual risk** to the obligor. |
| 2A | Where an exposure is covered by unfunded credit protection that is itself collateralised, and the institution uses both LGD-AM and LGD-MCM under CRR Art. 191A(2), the adjustments under paragraph 2 may also reflect the collateral effect under Art. 169A(3). |
| 3 | **Asset mismatch** between underlying obligation and the credit derivative reference / credit-event obligation: usable as eligible unfunded credit protection only if CRR Art. 216(2) requirements are met. CDs require LGD-adjustment criteria addressing **payout structure**, conservative timing/level-of-recovery assessment and residual-risk consideration. |

!!! info "LGD-AM vs. LGD-MCM — two distinct A-IRB methods"
    Art. 183 (LGD-AM) is the **adjustment** method — guarantees and credit
    derivatives are recognised by adjusting LGD estimates or facility grades.
    Art. 169B (LGD-MCM) is the **modelling** method — collateral and (where
    permitted under Art. 191A) unfunded credit protection are recognised through
    the LGD model itself. Art. 191A is the single decision tree governing which
    method applies for each exposure / protection combination.

**Calculator handover:** guarantee recognition under LGD-AM is implemented in
`engine/irb/guarantee.py`. The calculator does not validate Art. 183(1A)(a)–(c)
contractual eligibility — that is an upstream model-governance / CRM-validation
responsibility.

**PDF citation:** ps126app1.pdf p. 139–140.

### Article 184 — Requirements for Purchased Receivables

> Estimation standards specific to purchased receivables — applies to both corporate
> (Art. 154(5)) and retail purchased receivables, layered on top of the general
> requirements in Arts. 179–182.

| Paragraph | Requirement |
|-----------|-------------|
| 1 | Quantify risk parameters by rating grade or pool subject to all of paragraphs 2–6. |
| 2 | **Effective ownership and control of cash remittances** under all foreseeable circumstances. Where the obligor pays seller / servicer directly, **regular verification** that payments are forwarded completely and on time. Procedures protecting ownership and cash receipts against bankruptcy stays / legal challenges that could delay liquidation or assignment. |
| 3 | **Monitor both the receivables quality and the financial condition of the seller and servicer**: (a) assess correlation between receivables quality and seller/servicer condition; **assign internal risk rating to each seller and servicer**; (b) clear seller/servicer-eligibility policies; **periodic reviews** of sellers/servicers to verify accuracy of reports, detect fraud, verify credit and collection policies; (c) assess characteristics of receivables pools (over-advances, arrears history, bad debts and allowances, payment terms, contra accounts); (d) policies and procedures monitoring **single-obligor concentrations** within and across pools; (e) timely and detailed servicer reports of **receivables ageings and dilutions**. |
| 4 | Systems and procedures for **early detection** of seller-condition deterioration and receivables-quality deterioration, with proactive remediation; covenant-violation monitoring; clear policies for legal action and problem-receivables management. |
| 5 | Written internal policies covering all material elements of the receivables-purchase programme: **advancing rates, eligible collateral, documentation, concentration limits, cash-receipts handling**. Funds advanced only against specified supporting collateral and documentation. |
| 6 | Effective internal compliance process including **regular audits** of all critical phases of the programme, verification of **separation of duties** (seller/servicer assessment vs. obligor assessment vs. field audit), and back-office evaluation focused on qualifications, experience, staffing and supporting automation. |

**Calculator handover:** purchased receivables flow through the same IRB engine as
direct corporate / retail exposures; their treatment is governed by
[Roll-Out Class (c) — Corporate Purchased Receivables](#art-147b1--roll-out-classes-eight-classes)
and Roll-Out Class (g) — Retail Purchased Receivables. The Art. 184 controls are
not engine logic; they are an upstream model-governance precondition for using
the purchased-receivables population under IRB.

**PDF citation:** ps126app1.pdf p. 140–141.

### Cross-Reference: Estimation vs. Calculator Application

The boundary between **what the institution estimates** (Arts. 179–184) and
**what the calculator applies** (regulatory floors, multipliers and downturn
overlays) is summarised below:

| Risk parameter | Estimated by institution under | Floor / multiplier applied by calculator |
|----------------|-------------------------------|------------------------------------------|
| **PD** (corporate / institution) | Art. 180(1) — long-run average, ≥ 5y data, MoC under 179(1)(f) | **Art. 163(1)** PD floor: corporate 0.05% (Basel 3.1) — `engine/irb/adjustments.py` |
| **PD** (retail) | Art. 180(2) — long-run average, ≥ 5y data, seasoning under 180(2)(f) | **Art. 163(1)** PD floor: retail mortgage 0.10%, retail other / QRRE transactor 0.05%, QRRE revolver 0.10% — `engine/irb/adjustments.py` |
| **LGD** (A-IRB corporate / institution) | Art. 181(1) — default-weighted, downturn under 181(1)(b), ≥ 5y ramping to 7y under 181(1)(j) | **Art. 161(5)** A-IRB LGD floors: unsecured 25%, financial collateral 0%, RE/receivables 10%, other physical 15% — `engine/irb/adjustments.py` |
| **LGD** (A-IRB retail) | Art. 181(2) — ≥ 5y, downturn under 181(1)(b) (cross-applies) | **Art. 164(4)** retail LGD floors: secured RRE 5%, QRRE unsecured 50%, other unsecured retail 30%, secured LGDU 30% — `engine/irb/adjustments.py` |
| **LGD-AM** unfunded credit protection | Art. 183 — guarantor grading (181/171–173), eligibility (1A), payout-structure analysis (3) | LGD adjustment via guarantor PD/LGD substitution — `engine/irb/guarantee.py` |
| **CF / EAD** (A-IRB own-estimate) | Art. 182 — default-weighted, downturn under 182(1)(b), 12-month look-back under 182(1)(g), ≥ 5y ramping to 7y for non-retail | **CRE32.27** CCF floor: own CCF ≥ 50% of SA CCF; own CCFs only for revolving facilities — `engine/irb/adjustments.py` |
| **Downturn period** | Art. 181A–C — relevant indicator set (181B), ≥ 20-year time-span (181C(1)) | None — downturn application is upstream of the calculator. |
| **F-IRB LGD / CCF** | Not estimated by the institution — supervisory values apply | Art. 161 supervisory LGD; Art. 166C/D supervisory CCFs — the supervisory-LGD entries in the rulepack packs (`src/rwa_calc/rulebook/packs/{crr,b31}.py`), resolved via `rwa_calc.rulebook.resolve` |

!!! info "Why the calculator does not implement Arts. 179–184 directly"
    The estimation requirements in Arts. 179–184 are model-governance obligations
    that the institution discharges within its rating-system development and
    validation framework. The calculator engine consumes the resulting model
    outputs (PD, LGD, CCF) on the input bundle and applies regulatory downstream
    controls — floors, multipliers, downturn overlays where mandated by formula
    rather than by estimation. Validation of Arts. 179–184 compliance is the
    subject of Art. 185 (validation of internal estimates, ps126app1.pdf p. 141)
    and is verified through the rating-system back-testing reflected in COREP
    template **C 08.05 / OF 08.05** — see
    [COREP Reporting — C 08.05 / OF 08.05](../../features/corep-reporting.md#c-0805-of-0805-cr-irb-pd-back-testing).

---

## Source Citations

| Reference | Page (ps126app1.pdf) | Topic |
|-----------|----------------------|-------|
| Art. 143A | p. 84 | Rating systems: categories of changes (material vs notification) |
| Art. 143B | p. 84–85 | Rating systems: principles of classification of changes |
| Art. 143C | p. 85 | Rating systems: material changes (1.5% / 15% thresholds) |
| Art. 143D | p. 86 | Rating systems: non-material changes (5% threshold, notification timing) |
| Art. 143E | p. 86 | Rating systems: documentation of changes |
| **Art. 144(1)(a)–(h)** | **p. 86–87** | **High-level requirements for using the IRB Approach (entry conditions)** |
| **Art. 144(1A)** | **p. 87** | **Third-party vendor rating systems compliance obligation** |
| **Art. 144(2)** | **p. 87** | **Provision left blank** |
| Art. 145 | p. 87 | Prior experience requirement (3 years) |
| Art. 147(2) | p. 88 | Eight Art. 147(2) exposure classes / subclasses |
| Art. 147(4B) | p. 89–90 | Specialised lending sub-categories (OF, PF, CF, IPRE, HVCRE) |
| Art. 147A(1)(a)–(k) | p. 92–93 | Approach treatment by exposure class |
| **Art. 147B(1)** | **p. 93** | **Eight roll-out classes (a)–(h)** |
| **Art. 147B(2)** | **p. 93** | **Non-Retail AIRB Modelling roll-out category** |
| Art. 147C(1)–(2) | p. 93 | Roll-out methodology and obligation |
| Art. 148(1), (1A) | p. 94 | Sequenced roll-out permissions |
| Roll-out class definition | p. 79 | Cross-reference to Art. 147B(1) |
| Non-Retail AIRB Modelling roll-out category definition | p. 78 | Cross-reference to Art. 147B(2) |
| **Art. 179(1)–(2), (1A)** | **p. 131–132** | **Overall requirements for risk-parameter estimates (data, MoC, pooled data)** |
| **Art. 180(1)(a)–(h)** | **p. 132–133** | **PD estimation — corporate / institution (5-year minimum data, long-run average)** |
| **Art. 180(2)(a)–(f)** | **p. 133–134** | **PD estimation — retail (5-year minimum data, seasoning)** |
| **Art. 181(1)(a)–(j)** | **p. 134–135** | **LGD estimation — default-weighted, downturn LGD, LGD-in-default, 5y -> 7y ramp for corporates** |
| **Art. 181(2)** | **p. 135** | **LGD estimation — retail (5-year minimum)** |
| **Art. 181A** | **p. 135–136** | **Economic downturn — nature, severity, duration** |
| **Art. 181B** | **p. 136–137** | **Economic downturn — relevant indicator set (GDP, unemployment, sector indices)** |
| **Art. 181C** | **p. 137–138** | **Economic downturn — applicable time-span (≥ 20 years) and downturn duration** |
| **Art. 182(1)–(3)** | **p. 138–139** | **CCF / EAD estimation — downturn, 12-month look-back, 5y -> 7y ramp for corporates / institutions, 5y for retail** |
| **Art. 183(1)–(3)** | **p. 139–140** | **LGD-AM — eligibility of guarantees and credit derivatives, guarantor grading, payout-structure assessment** |
| **Art. 184(1)–(6)** | **p. 140–141** | **Purchased receivables — cash control, seller/servicer monitoring, single-obligor concentration, internal audit** |
| Art. 185 | p. 141 | Validation of internal estimates (cross-reference for Sub-Section 3) |

---

## Related Specifications

- [Foundation IRB Specification](firb-calculation.md) — F-IRB calculation for institutions, FSEs, large corporates, and other general corporates.
- [Advanced IRB Specification](airb-calculation.md) — A-IRB calculation for retail and other-general-corporate populations.
- [Slotting Approach Specification](slotting-approach.md) — Slotting risk weights for specialised lending (IPRE, HVCRE, OF, PF, CF).
- [Model Permissions Specification](model-permissions.md) — Art. 147A approach restriction matrix, Art. 150 permanent partial use, fallback routing.
- [Equity Approach Specification](equity-approach.md) — Why equity is excluded from IRB roll-out (Art. 147A(1)(h), Art. 155 blank).
