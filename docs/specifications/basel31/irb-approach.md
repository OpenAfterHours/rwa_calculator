# IRB Approach Specification (Basel 3.1)

Basel 3.1 IRB Approach scope, roll-out classes, and approach-routing rules introduced
by PRA PS1/26.

This page is the canonical home for the **Art. 147B roll-out class enumeration** that
governs IRB scope-of-use reporting (COREP **OF 08.07**) and disclosure (Pillar 3
**UKB CR6-A**). Other reporting/disclosure pages cross-reference this enumeration; do
not duplicate the class list elsewhere.

**Regulatory Reference:** PRA PS1/26 Art. 147, 147A, 147B, 147C, 148, 150 (Annex E,
Credit Risk: Internal Ratings Based Approach (CRR) Part).
**Source PDF:** `docs/assets/ps126app1.pdf`, pp. 88–94.

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

## Source Citations

| Reference | Page (ps126app1.pdf) | Topic |
|-----------|----------------------|-------|
| Art. 147(2) | p. 88 | Eight Art. 147(2) exposure classes / subclasses |
| Art. 147(4B) | p. 89–90 | Specialised lending sub-categories (OF, PF, CF, IPRE, HVCRE) |
| Art. 147A(1)(a)–(k) | p. 92–93 | Approach treatment by exposure class |
| **Art. 147B(1)** | **p. 93** | **Eight roll-out classes (a)–(h)** |
| **Art. 147B(2)** | **p. 93** | **Non-Retail AIRB Modelling roll-out category** |
| Art. 147C(1)–(2) | p. 93 | Roll-out methodology and obligation |
| Art. 148(1), (1A) | p. 94 | Sequenced roll-out permissions |
| Roll-out class definition | p. 79 | Cross-reference to Art. 147B(1) |
| Non-Retail AIRB Modelling roll-out category definition | p. 78 | Cross-reference to Art. 147B(2) |

---

## Related Specifications

- [Foundation IRB Specification](firb-calculation.md) — F-IRB calculation for institutions, FSEs, large corporates, and other general corporates.
- [Advanced IRB Specification](airb-calculation.md) — A-IRB calculation for retail and other-general-corporate populations.
- [Slotting Approach Specification](slotting-approach.md) — Slotting risk weights for specialised lending (IPRE, HVCRE, OF, PF, CF).
- [Model Permissions Specification](model-permissions.md) — Art. 147A approach restriction matrix, Art. 150 permanent partial use, fallback routing.
- [Equity Approach Specification](equity-approach.md) — Why equity is excluded from IRB roll-out (Art. 147A(1)(h), Art. 155 blank).
