# SA Risk Weights Specification

Standardised Approach risk weights by exposure class and credit quality step.

**Regulatory Reference:** CRR Articles 112-134

**Test Group:** CRR-A

---

## Requirements Status

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-1.1 | SA risk weight calculation for all 9 exposure classes (CRR Art. 112–134) | P0 | Done |
| FR-1.2 | SA risk weight calculation for Basel 3.1 (CRE20–22), including LTV-based RE weights | P0 | Done |

---

## Due Diligence Obligation — No CRR Equivalent

CRR has no SA-specific due diligence obligation. The Basel 3.1 equivalent is Art. 110A — a framework-wide obligation introduced by PRA PS1/26 with no CRR predecessor. Under CRR the SA calculator does not emit the `SA004` warning and ignores the `due_diligence_override_rw` column.

!!! info "Basel 3.1 addition — Art. 110A"
    See [Basel 3.1 SA Risk Weights § Due Diligence Obligation (Art. 110A)](../basel31/sa-risk-weights.md#due-diligence-obligation-art-110a) for the obligation's regulatory text, exempt obligor classes, and calculator integration (input fields `due_diligence_performed` / `due_diligence_override_rw`, sequencing, audit column).

## Sovereign Exposures (CRR Art. 114)

| CQS | Rating Equivalent | Risk Weight |
|-----|-------------------|-------------|
| 1 | AAA to AA- | 0% |
| 2 | A+ to A- | 20% |
| 3 | BBB+ to BBB- | 50% |
| 4 | BB+ to BB- | 100% |
| 5 | B+ to B- | 100% |
| 6 | CCC+ and below | 150% |
| Unrated | — | 100% |

**Domestic currency**: UK central government and Bank of England exposures denominated and funded in **sterling** receive **0%** risk weight (Art. 114(4)). Third-country sovereign exposures in their domestic currency may also receive 0% where the jurisdiction's supervisory regime is deemed equivalent (Art. 114(7) — applies to EU member states). The ECB receives 0% unconditionally (Art. 114(3)).

## RGLA Exposures (CRR Art. 115)

Regional governments and local authorities. Two possible treatments:

### Sovereign-Derived Treatment — Table 1A (Art. 115(1)(a))

Where RGLA exposures lack their own ECAI rating, use the **sovereign's CQS** with Table 1A:

| Sovereign CQS | RGLA Risk Weight |
|---------------|-----------------|
| 1 | 20% |
| 2 | 50% |
| 3 | 100% |
| 4 | 100% |
| 5 | 100% |
| 6 | 150% |
| Unrated | 100% |

Under PRA rules, UK devolved administrations (Scotland, Wales, Northern Ireland) receive **0%** risk weight.

### Own-Rating Treatment — Table 1B (Art. 115(1)(b))

Where RGLA exposures have their own ECAI rating, use Table 1B:

| CQS | Risk Weight |
|-----|-------------|
| 1 | 20% |
| 2 | 50% |
| 3 | 50% |
| 4 | 100% |
| 5 | 100% |
| 6 | 150% |
| Unrated | 100% |

**UK local authorities**: All UK local authorities receive **20%** risk weight per PRA designation.

**Religious communities treated as RGLAs (Art. 115(3))**: Exposures to **churches or religious communities constituted in the form of a legal person under public law** shall, **in so far as they raise taxes in accordance with legislation conferring on them the right to do so**, be treated as exposures to **regional governments and local authorities** (CRR Art. 115(3), crr.pdf p.114). Both eligibility limbs must be satisfied — the entity must be a public-law legal person *and* must hold statutory tax-raising powers. Where eligible, the exposure is routed into the Art. 115(1) RGLA tables above (sovereign-derived Table 1A or own-rating Table 1B as applicable); CRR Art. 115(3) further provides that the central-government treatment in Art. 115(2) does **not** apply, and that the IRB permanent-partial-use exclusion in Art. 150(1)(a) is **not** engaged for these exposures. This is an edge-case provision aimed at jurisdictions (notably Germany under the *Körperschaftsteuergesetz*) where established churches retain a constitutional right to levy church tax; UK-resident religious bodies generally do **not** satisfy the tax-raising limb.

!!! info "Basel 3.1 — Art. 115(3) Retained"
    PRA PS1/26 Art. 115(3) re-enacts the religious community RGLA route in materially the same terms (ps126app1.pdf p.37): "Exposures to churches or religious communities constituted in the form of a legal person under public law shall, in so far as they raise taxes in accordance with legislation conferring on them the right to do so, be treated as exposures to regional governments or local authorities." The PS1/26 text drops the CRR Art. 150(1)(a) IRB-permission carve-out (consistent with the wider B31 restructuring of permanent-partial-use eligibility), but the substantive RGLA-derived treatment continues unchanged from 1 January 2027.

**Sterling-funded UK RGLAs (Art. 115(5))**: Exposures to regional governments or local authorities of the United Kingdom that are not treated as central government under Art. 115(2)–(4) and are **denominated and funded in pounds sterling** shall be assigned a risk weight of **20%**. This treatment is **maturity-independent** — it applies regardless of the original or residual maturity of the exposure and regardless of the counterparty's CQS.

!!! warning "Previous Spec Error Corrected"
    An earlier version of this section described Art. 115(5) as applying only to short-term
    sterling RGLA exposures. Art. 115(5) has **no maturity condition** — the 20% weight
    applies to all sterling-denominated, sterling-funded UK RGLA exposures. The short-term
    preferential treatments in Art. 119(2) and Art. 120(2) are separately excluded from
    RGLAs by Art. 115(1) (for non-central-government-treated RGLAs routed through the
    institution table), which is distinct from the Art. 115(5) sterling carve-out.

## PSE Exposures (CRR Art. 116)

Public sector entities have three sub-treatments:

### Sub-treatment 1 — Sovereign-Derived — Table 2 (Art. 116(1))

UK PSEs without own ECAI rating use the **sovereign's CQS** with Table 2:

| Sovereign CQS | PSE Risk Weight |
|---------------|----------------|
| 1 | 20% |
| 2 | 50% |
| 3 | 100% |
| 4 | 100% |
| 5 | 100% |
| 6 | 150% |
| Unrated | 100% |

### Sub-treatment 2 — Own-Rating — Table 2A (Art. 116(2))

UK PSEs with own ECAI rating use Table 2A:

| CQS | Risk Weight |
|-----|-------------|
| 1 | 20% |
| 2 | 50% |
| 3 | 50% |
| 4 | 100% |
| 5 | 100% |
| 6 | 150% |
| Unrated | 100% |

### Sub-treatment 3 — Competent-Authority Equivalence (Art. 116(4))

In **exceptional circumstances**, UK PSE exposures **may** be treated as exposures to the central government, regional government or local authority of the United Kingdom where all of the following apply (CRR Art. 116(4), crr.pdf p.115):

1. An **appropriate guarantee** exists from that central government, regional government or local authority; and
2. The competent authorities of the United Kingdom are of the opinion that there is **no difference in risk** between the guaranteed PSE exposure and a direct exposure to the guaranteeing government or authority.

The effect is to substitute the guarantor's sovereign or RGLA risk weight for the Art. 116(1)/(2) PSE treatment. This is a competent-authority discretion — not a routine election — and the substitute tier (central / regional / local) must match the tier providing the guarantee.

!!! info "Basel 3.1 — Art. 116(4) Not Retained"
    PRA PS1/26 Art. 116(4) is marked `[Note: Provision left blank]` (ps126app1.pdf p.38); the accompanying note states the PS1/26 rule corresponds to CRR Art. 116(1)–(3) only. The competent-authority equivalence route has **no PS1/26 successor** — from 1 January 2027, any guarantee-based RGLA/sovereign override for a PSE must be routed through the general CRM guarantee substitution regime (Art. 235, Chapter 4), not an Art. 116-specific carve-out.

### Sub-treatment 4 — Third-Country PSE Equivalence (Art. 116(5))

Where a third-country competent authority applies supervisory and regulatory arrangements at least equivalent to those applied in the UK and treats exposures to its own PSEs under paragraph 1 or 2, UK institutions **may** risk weight exposures to those third-country PSEs in the same manner. Otherwise, a risk weight of **100%** applies (CRR Art. 116(5), crr.pdf p.115). Equivalence is determined by the Treasury by regulations.

!!! info "Basel 3.1 — Art. 116(5) Retained by Cross-Reference"
    PRA PS1/26 Art. 116(5) itself is marked `[Note: Provision not in PRA Rulebook]`, but Art. 116(3A) explicitly cross-refers to "Article 116(5) of CRR" — redirecting "UK PSEs" in paragraphs 1 and 2 to mean third-country PSEs when Art. 116(5) of CRR applies (ps126app1.pdf p.38). CRR Art. 116(5) therefore remains operative as the third-country equivalence gate under Basel 3.1.

**Short-term exposures (≤ 3 months)**: UK PSE exposures with original effective maturity ≤ 3 months receive **20%** risk weight (Art. 116(3)). No domestic currency condition required for PSEs.

!!! warning "Art. 116(4)/(5) Not Implemented"
    Neither Art. 116(4) competent-authority equivalence nor Art. 116(5) third-country equivalence is implemented in the SA calculator. PSE exposures are routed solely through Art. 116(1)/(2) Tables 2/2A plus the Art. 116(3) short-term preferential. Firms relying on Art. 116(4) guarantee-backed equivalence must apply the substitution outside the engine.

## MDB Exposures (CRR Art. 117)

### Named MDBs at 0% (Art. 117(2))

The following 16 MDBs receive a **0%** risk weight:

1. International Bank for Reconstruction and Development (IBRD / World Bank)
2. International Finance Corporation (IFC)
3. Inter-American Development Bank (IDB)
4. Asian Development Bank (ADB)
5. African Development Bank (AfDB)
6. Council of Europe Development Bank (CEB)
7. Nordic Investment Bank (NIB)
8. Caribbean Development Bank (CDB)
9. European Bank for Reconstruction and Development (EBRD)
10. European Investment Bank (EIB)
11. European Investment Fund (EIF)
12. Multilateral Investment Guarantee Agency (MIGA)
13. International Finance Facility for Immunisation (IFFIm)
14. Islamic Development Bank (IsDB)
15. Asian Infrastructure Investment Bank (AIIB)
16. International Development Association (IDA)

### Non-Named MDBs — Institution Treatment (Art. 117(1))

MDBs not on the 0% list are treated **"in the same manner as exposures to institutions"** per
Art. 117(1). They use the institution risk weight tables — Art. 120 Table 3 for ECAI-rated
institutions, Art. 121 Table 5 for sovereign-derived. No separate CRR risk weight table
exists for MDBs.

Art. 117(1) **excludes** short-term preferential treatment (Art. 119(2), 120(2), 121(3))
for MDB exposures — MDBs cannot receive reduced short-term risk weights available to
institutions.

Art. 117(1) also names four non-0% MDBs: Inter-American Investment Corporation, Black Sea
Trade and Development Bank, Central American Bank for Economic Integration, and CAF —
Development Bank of Latin America.

!!! warning "Code Divergence (D3.39)"
    The code defines a separate `MDB_RISK_WEIGHTS_TABLE_2B` in `crr_risk_weights.py` with
    CQS 2 = 30% and unrated = 50%. This is incorrect for CRR — these are the **Basel 3.1
    Table 2B** values (PRA PS1/26 Art. 117(1)(a)). Under CRR, non-named MDBs should use the
    institution tables (Art. 120 Table 3: CQS 2 = **50%**, matching other institutions). The
    30% value reflects the same misattribution identified in D1.30.

!!! info "Basel 3.1 Change"
    PRA PS1/26 Art. 117(1) introduces a **dedicated MDB risk weight table (Table 2B)**,
    replacing the CRR "treated as institution" approach. Table 2B gives MDBs their own CQS
    mapping (notably CQS 2 = 30%, more favourable than institution ECRA CQS 2 = 30% or CRR
    institution CQS 2 = 50%). See
    [Basel 3.1 SA Risk Weights — MDB](../basel31/sa-risk-weights.md#mdb-exposures-art-117).

## International Organisations (CRR Art. 118)

The following international organisations receive a **0%** risk weight:

- European Union (EU)
- International Monetary Fund (IMF)
- Bank for International Settlements (BIS)
- European Financial Stability Facility (EFSF)
- European Stability Mechanism (ESM)

!!! warning "Art. 118(f) Omitted on UK Exit (SI 2018/1401)"
    Art. 118(f) was **omitted from UK onshored CRR** by
    *The Capital Requirements (Amendment) (EU Exit) Regulations 2018*
    ([SI 2018/1401](https://www.legislation.gov.uk/uksi/2018/1401/contents)),
    reg. 116, with effect from 31 December 2020 (IP completion day). The
    original EU CRR text read:

    > "(f) an international financial institution established by two or more
    > Member States, which has the purpose to mobilise funding and provide
    > financial assistance to the benefit of its members that are experiencing
    > or threatened by severe financing problems."

    *Source: CRR Art. 118 footnote F266; legislation.gov.uk "as adopted by EU"
    text dated 28 June 2013.*

    **Practical effect:** The Art. 118 0% list is **closed** under UK CRR — only
    items (a) to (e) qualify. There is no residual catch-all for "international
    financial institutions established by two or more Member States" any longer,
    so any such body that is not separately named in Art. 117(2) (MDB list) or
    Art. 118(a)–(e) must be risk-weighted as a corporate/institution under the
    standard exposure-class waterfall. A separate UK-exit edit (SI 2019/1232,
    reg. 35) also struck words from Art. 118(a) — leaving "the European Union"
    as the sole referent.

!!! note "Plan-item misattribution (D4.56)"
    The audit item that prompted this subsection described Art. 118 as
    "exposures to recognised exchanges" and the SI 2018/1401 deletion as
    targeting "EU-regulated exchanges". Both are incorrect: Art. 118 has
    always been the **international-organisations 0%** list, and SI 2018/1401
    reg. 116 deleted **Art. 118(f)** — the residual "two-or-more-Member-States
    international financial institution" catch-all quoted above. Recognised
    exchanges are governed by **CRR Art. 107** (definition of "recognised
    exchange") and Art. 197/198 (eligible collateral via main-index equities),
    not Art. 118.

## Institution Exposures (CRR Art. 120-121)

| CQS | Risk Weight |
|-----|-------------|
| 1 | 20% |
| 2 | 50% |
| 3 | 50% |
| 4 | 100% |
| 5 | 100% |
| 6 | 150% |
| Unrated | 100% (Art. 120(2)) |

### Short-Term Institution Exposures (CRR Art. 120(2), Art. 121(3))

Rated institutions with residual maturity ≤ 3 months receive preferential risk weights
under Art. 120(2). Unrated institutions with maturity ≤ 3 months receive 20% under
Art. 121(3).

**Table 4 — Short-Term Preferential (CRR Art. 120(2))**

| Institution CQS | Short-Term RW |
|-----------------|---------------|
| 1 | 20% |
| 2 | 20% |
| 3 | 20% |
| 4 | 50% |
| 5 | 50% |
| 6 | 150% |
| Unrated | 20% (Art. 121(3)) |

### Unrated Institutions — Sovereign-Derived (CRR Art. 121, Table 5)

Where an institution lacks its own ECAI rating, risk weights are derived from its
sovereign's CQS:

**Table 5 — Unrated Institution Sovereign-Derived (CRR Art. 121(1))**

| Sovereign CQS | Institution RW |
|---------------|----------------|
| 1 | 20% |
| 2 | 50% |
| 3 | 100% |
| 4 | 100% |
| 5 | 100% |
| 6 | 150% |
| Unrated | 100% |

Unrated institutions with residual maturity ≤ 3 months receive **20%** regardless of
sovereign CQS (Art. 121(3)).

### Trade Finance Preferential Treatment for Unrated Institutions (CRR Art. 121(4))

CRR Art. 121(4) carves out a dedicated preferential channel for **trade-finance**
exposures to **unrated institutions**, overriding both the sovereign-derived Table 5
weights for unrated-sovereign jurisdictions (Art. 121(2), 100%) and the general
short-term unrated 20% (Art. 121(3)).

!!! quote "Art. 121(4) — verbatim (CRR p. 120)"
    "Notwithstanding paragraphs 2 and 3, for trade finance exposures referred to in
    point (b) of the second subparagraph of Article 162(3) to unrated institutions,
    the risk weight shall be 50 % and where the residual maturity of these trade
    finance exposures to unrated institutions is three months or less, the risk
    weight shall be 20 %."

**Risk weights.** Two cases only — Art. 121(4) does **not** take a CQS input; the
preferential weight is fixed at the article level:

| Eligible trade-finance exposure | Risk Weight |
|---|---|
| Trade finance to unrated institution, residual maturity > 3 months but ≤ 1 year | **50%** |
| Trade finance to unrated institution, residual maturity ≤ 3 months | **20%** |

The 50% / 20% values **replace** what the exposure would otherwise receive under
Art. 121(1) Table 5 (sovereign-derived 20%–150%), Art. 121(2) (unrated sovereign
jurisdiction → 100%), and Art. 121(3) (unrated short-term flat 20%). The
"notwithstanding paragraphs 2 and 3" head-clause ensures the Art. 121(4) result
binds in priority over those subordinate paragraphs.

**Eligibility — what counts as "trade finance" under Art. 121(4).**

Art. 121(4) routes through Art. 162(3) second subparagraph point (b) — the AIRB
maturity-floor list of *qualifying short-term exposures* — which describes:

!!! quote "Art. 162(3) second subparagraph point (b) — verbatim (CRR p. 160)"
    "self-liquidating short-term trade finance transactions connected to the
    exchange of goods or services with a residual maturity of up to one year as
    referred to in point (80) of Article 4(1);"

That cross-reference further pulls in the Art. 4(1)(80) defined term:

!!! quote "Art. 4(1)(80) — verbatim (CRR p. 39)"
    "'trade finance' means financing, including guarantees, connected to the
    exchange of goods and services through financial products of fixed
    short-term maturity, generally of less than one year, without automatic
    rollover."

Cumulative eligibility — all five conditions must hold for the Art. 121(4)
preferential to apply:

1. **Counterparty type** — exposure is to an **unrated institution** (i.e. an
   institution falling within Art. 121 because no nominated ECAI assessment is
   available — Art. 119(1)). Rated institutions route through Art. 120 / Table 4
   (general short-term) or Table 4A (Basel 3.1 short-term ECRA), not Art. 121(4).
2. **Trade finance product** — financing or guarantees connected to the exchange
   of goods and services (Art. 4(1)(80)).
3. **Self-liquidating** — repayment funded by the underlying trade flow, not by
   a refinancing facility (Art. 162(3) second subparagraph point (b)).
4. **Connected to goods or services exchange** — the financing is documented as
   trade-related, not a general working-capital facility branded as trade finance.
5. **Residual maturity** — ≤ 1 year (the Art. 4(1)(80) "generally less than one
   year" envelope, hard-edged in Art. 162(3) point (b) at "up to one year"). The
   20% reduction below the 50% base further requires residual maturity **≤ 3
   months**.

**Sovereign linkage — none.** Despite sitting inside Art. 121 ("sovereign-derived
approach for unrated institutions"), Art. 121(4) is **not** keyed on the
sovereign's CQS. The 50%/20% weights apply uniformly regardless of whether the
institution is incorporated in a CQS 1 (UK / equivalent) or CQS 6 jurisdiction.
This contrasts with Art. 121(1) Table 5, which steps the unrated institution
weight from 20% (sovereign CQS 1) up to 150% (sovereign CQS 6).

**Distinction from Art. 122 / 121(3) short-term channels.** Three short-term
windows can apply to an unrated institution exposure; the most favourable
applicable weight wins:

| Article | Eligibility key | Maturity test | Currency / sovereign condition | RW outcome |
|---|---|---|---|---|
| Art. 121(1) Table 5 | Unrated institution, all maturities | None (general path) | Uses sovereign CQS of jurisdiction of incorporation | 20%/50%/100%/100%/100%/150% |
| Art. 121(3) | Unrated institution, **original** effective maturity ≤ 3 months | Original ≤ 3m | None | Flat **20%** |
| Art. 121(4) (this section) | Unrated institution + self-liquidating trade finance per Art. 162(3)(b) | **Residual** ≤ 1y (50%) or **residual** ≤ 3m (20%) | None — uniform fixed weight | **50%** or **20%** |
| Art. 119(2)/(3) | Any institution + national-currency denom & funding + residual ≤ 3m | Residual ≤ 3m | National-currency denom **and** funded | One step less favourable than Art. 114(4)–(7) sovereign preferential, floored at 20% |

Note the maturity-test difference: Art. 121(3) uses **original** effective
maturity (≤ 3 months); Art. 121(4) uses **residual** maturity (≤ 1 year for the
50% weight, ≤ 3 months for the further-reduced 20% weight). A trade-finance
exposure with original maturity 6 months but residual maturity 2 months at
reporting date qualifies for the Art. 121(4) 20% under the residual test even
though it fails the Art. 121(3) original-maturity test.

**Worked example — UK trade finance to unrated foreign institution.**

A 9-month £10m self-liquidating trade-finance facility (a confirmed letter of
credit financing a goods import) extended to a Vietnam-incorporated bank without
a nominated ECAI rating, residual maturity at reporting date 7 months. Vietnam
sovereign sits at CQS 4 (Art. 114(2) Table 1 → 100% sovereign).

1. Eligibility checks: counterparty = unrated institution (yes); product =
   self-liquidating trade-related letter-of-credit financing (yes — Art. 162(3)
   second subparagraph point (b)); residual maturity ≤ 1 year (yes, 7m); residual
   maturity ≤ 3 months (no).
2. Apply Art. 121(4): residual maturity > 3 months but ≤ 1 year → **50%**.
3. Compare against alternative paths:
    - Art. 121(1) Table 5 with sovereign CQS 4 → 100%. Worse, displaced by
      Art. 121(4) "notwithstanding paragraph 2".
    - Art. 121(3) requires *original* effective maturity ≤ 3 months — original
      is 9 months, fails. Path closed.
    - Art. 119(2)/(3) requires sterling denom **and** funding (the borrower's
      national currency would be VND); a £-denominated facility fails the
      "denominated and funded in the *national currency of the borrower*" test.
      Path closed.
4. Final risk weight: **50%**. RWA = £10m × 50% = £5m.

Had residual maturity been 2 months at reporting date, Art. 121(4) would yield
**20%** directly — RWA = £10m × 20% = £2m — beating the Art. 121(1) Table 5
result (100%) by a factor of five.

!!! warning "Removed under Basel 3.1 (PS1/26 Art. 121 restructured to SCRA grades)"
    PRA PS1/26 Art. 121 (ps126app1.pdf pp. 41–44) replaces the entire CRR
    sovereign-derived Table 5 framework with a **Standardised Credit Risk
    Assessment (SCRA)** approach: unrated institutions are classified into
    **Grade A / Grade B / Grade C** based on capital, leverage, and going-concern
    criteria, and risk-weighted via Table 5 (40% / 75% / 150%) for general
    maturities or Table 5A (20% / 50% / 150%) for short-term / movement-of-goods
    exposures. There is **no direct successor** to CRR Art. 121(4)'s flat 50%
    trade-finance weight. The economically closest provision is PS1/26
    Art. 121(4): exposures to unrated institutions where the **original maturity
    was six months or less and the exposure arose from the movement of goods**
    receive Table 5A treatment (Grade A 20% / Grade B 50% / Grade C 150%) —
    similar in spirit to the CRR carve-out but now SCRA-graded (not flat) and
    keyed on *original* maturity ≤ 6 months (not residual ≤ 1 year). Additionally,
    PS1/26 Art. 121(6)(b) excludes self-liquidating trade-related contingent
    items with original maturity < 1 year from the foreign-currency sovereign
    floor that otherwise applies under Art. 121(6).
    See [Basel 3.1 SA Risk Weights — Institution Risk Weights (SCRA, Art. 121)](../basel31/sa-risk-weights.md#institution-risk-weights-ecra-art-120).

!!! bug "Implementation Status — Not implemented in CRR calculator"
    The CRR SA calculator branch (`engine/sa/calculator.py`) does **not**
    evaluate Art. 121(4) trade finance preferential. The calculator routes all
    unrated institution exposures through Art. 121(1) Table 5 with the
    Art. 121(3) 20% short-term override only. There is no `is_trade_finance`
    schema field, no Art. 162(3)(b) self-liquidating gate, and no flat 50%/20%
    trade-finance constant in `data/tables/crr_risk_weights.py`. Firms with
    material trade-finance books to unrated institutions in CQS 2–6 jurisdictions
    must apply the Art. 121(4) override outside the engine — the gap overstates
    RW versus the regulation in those cells. The CRR-only nature of the rule
    means this gap will not affect Basel 3.1 calculations from 1 January 2027
    (SCRA-based PS1/26 Art. 121 replaces the framework entirely; see warning
    callout above).

### National-Currency Short-Term Preferential Treatment (CRR Art. 119(2), 119(3))

CRR provides a **separate** sovereign-derived preferential path for institution exposures
in the borrower's national currency with residual maturity ≤ 3 months. This is distinct
from Art. 120(2) Table 4 (ECAI-rated short-term) and Art. 121(3) (unrated short-term 20%)
— those two articles carry the general ≤ 3-month preferential windows irrespective of
currency, while Art. 119(2)/(3) layers an additional sovereign-derived channel on top
for the national-currency subset.

!!! quote "Art. 119(2) — verbatim (CRR p. 118)"
    "Exposures to institutions of a residual maturity of three months or less denominated
    and funded in the national currency of the borrower shall be assigned a risk weight
    that is one category less favourable than the preferential risk weight, as described
    in Article 114(4) to (7), assigned to exposures to the central government in which
    the institution is incorporated."

!!! quote "Art. 119(3) — verbatim (CRR p. 118)"
    "No exposures with a residual maturity of three months or less denominated and funded
    in the national currency of the borrower shall be assigned a risk weight less than
    20 %."

**Eligibility (cumulative).** All four conditions must hold:

1. **Counterparty type** — exposure is to an *institution* (Art. 119 scope; the
   preferential is excluded for RGLAs by Art. 115(1) and for MDBs by Art. 117(1)).
2. **Residual maturity** — three months or less. Note this is *residual* maturity
   (cf. Art. 120(2) which uses the same residual-maturity test but Art. 121(3)
   which references the same residual ≤ 3m window).
3. **Currency** — exposure is denominated in the borrower's *national currency*
   (the currency of the jurisdiction in which the institution is incorporated).
4. **Funding** — exposure is also *funded* in that same national currency (i.e.
   the institution's funding leg matches the asset currency, ruling out
   off-shore-funded foreign-currency lending wrapped as domestic-currency claims).

**Mechanism (RW derivation).** Where the institution's central government benefits
from preferential sovereign treatment under Art. 114(4) (UK central government and
the Bank, sterling-denominated/funded → 0%), Art. 114(6) (Member-State central
government domestic-currency exposure — onshored CRR text retains the Member-State
gateway), or Art. 114(7) (third-country sovereign domestic-currency exposure where
the Treasury determines equivalent supervision), a national-currency short-term
exposure to an institution incorporated in that jurisdiction is assigned a risk
weight **one CQS category less favourable** than the preferential sovereign RW, and
is then floored at **20%** by Art. 119(3).

The "one category less favourable" step uses the sovereign Art. 114(2) Table 1
ladder (0% / 20% / 50% / 100% / 100% / 150%):

| Sovereign preferential RW (Art. 114(4)–(7)) | One CQS step less favourable | After Art. 119(3) 20% floor |
|---|---|---|
| 0% (CQS 1, UK sterling, third-country equivalent) | 20% (CQS 2) | **20%** |
| 20% (CQS 2) | 50% (CQS 3) | **50%** |
| 50% (CQS 3) | 100% (CQS 4) | **100%** |
| 100% (CQS 4–5) | 150% (CQS 6) | **150%** |
| 150% (CQS 6) | 150% (capped at the bottom of the ladder) | **150%** |

**UK worked example — sterling short-term claim on a UK institution.**

Consider a 2-month £25m interbank placement with a UK-incorporated bank,
sterling-denominated and sterling-funded:

1. Art. 119(2) eligibility check — counterparty = institution (yes); residual
   maturity = 2 months ≤ 3 months (yes); denomination = sterling (yes); funding =
   sterling (yes). All four conditions met.
2. Identify the sovereign preferential RW. UK central government / Bank of England,
   sterling-denominated and sterling-funded → 0% under Art. 114(4) (CRR p. 112).
3. Step one category less favourable on the Art. 114(2) Table 1 sovereign ladder:
   0% (CQS 1) → 20% (CQS 2).
4. Apply the Art. 119(3) floor: 20% is exactly at the floor, so the floor binds
   without effect.
5. Final risk weight: **20%**. RWA = £25m × 20% = £5m.

For the same exposure routed through Art. 120(2) Table 4 (rated CQS 2 institution,
≤ 3 months) the result is also 20%; routed through Art. 121(3) (if unrated, ≤ 3
months) it is again 20%. In the UK-domestic sterling-funded case the three paths
converge — the Art. 119(2)/(3) channel becomes operationally meaningful only where
the institution is incorporated in a third-country jurisdiction whose sovereign
benefits from Art. 114(6)/(7) preferential treatment but whose own ECAI grade
(Art. 120) or sovereign-derived grade (Art. 121) would otherwise produce a higher
weight.

**Scope.** Applies to both rated and unrated institutions — unlike Art. 120(2) (ECAI
required) and Art. 121(3) (unrated only), Art. 119(2)/(3) is an ECAI-agnostic path
keyed on currency, funding, and residual maturity. Where both Art. 119(2) and
Art. 120(2) could apply to the same rated exposure (e.g. a 2-month sterling-funded
CQS 2 UK-bank exposure), the **more favourable** path prevails — in practice
usually Art. 120(2) Table 4 (20% at CQS 1–3) matches or beats the Art. 119(3)
floor (20%), so no operational difference for UK-domestic short-term claims.

**Distinction from Art. 120(2) Table 4 and Art. 121(3).** The three short-term
preferential channels operate on different keys and must not be conflated:

| Article | Eligibility key | Currency condition | Sovereign linkage | Floor / cap |
|---------|----------------|---------------------|-------------------|-------------|
| Art. 120(2) Table 4 | Rated institution + residual ≤ 3 months | None | None — uses institution's own ECAI CQS | Table 4 grid (20%/20%/20%/50%/50%/150%) |
| Art. 121(3) | Unrated institution + residual ≤ 3 months | None | None | Flat 20% |
| Art. 119(2)/(3) | Any institution + residual ≤ 3 months + national-currency denom & funding | Required (denom AND funded in borrower's national currency) | One step less favourable than Art. 114(4)–(7) sovereign preferential | 20% floor (Art. 119(3)) |

Art. 120(2) and Art. 121(3) are general short-term windows; Art. 119(2)/(3) is a
**parallel, currency-conditioned, sovereign-derived** path — the borrower picks the
most favourable applicable grade across the three.

!!! warning "Removed under Basel 3.1 (PS1/26 Art. 119(2)/(3)/(4) blanked)"
    PS1/26 Appendix 1 p. 40 marks Art. 119(2), (3), and (4) all as
    `[Note: Provision left blank]`, removing the national-currency short-term preferential
    path from Basel 3.1 entirely. Under Basel 3.1 all short-term institution exposures
    must route through **Art. 120(2) Table 4** (rated) or **Art. 121(3)** (unrated 20%)
    — there is no parallel sovereign-derived national-currency channel. See
    [B31 SA Risk Weights — Institution Risk Weights](../basel31/sa-risk-weights.md#institution-risk-weights-ecra-art-120)
    and
    [Key Differences — Removal of Art. 119(2)/(3) National-Currency Preferential](../../framework-comparison/key-differences.md#removal-of-art-11923-national-currency-preferential-basel-31).

!!! info "Practical impact of the Basel 3.1 removal"
    **UK-domestic exposures**: neutral. Art. 120(2) Table 4 (20% at CQS 1–3, 50% at
    CQS 4–5) for rated and Art. 121(3) 20% for unrated already match the Art. 119(3)
    20% floor for the typical UK-bank domestic short-term case.

    **Cross-border exposures**: materially tighter where the counterparty institution is
    incorporated in a jurisdiction whose sovereign receives preferential Art. 114(6)/(7)
    treatment in the borrower's national currency. Under CRR, those exposures could pick
    up the Art. 119(2)/(3) path's 20% sovereign-derived weight regardless of the
    institution's own rating; under Basel 3.1 they fall through to Art. 120(2) Table 4
    (potentially 50% at CQS 4–5 or 150% at CQS 6) or Art. 121 SCRA grading (40%–150%),
    with no national-currency override.

!!! bug "Implementation Status — Not implemented in CRR calculator (D3.28)"
    The CRR SA calculator branch (`engine/sa/calculator.py`) does **not** evaluate
    Art. 119(2)/(3). The calculator routes all short-term institution exposures through
    Art. 120(2) Table 4 (rated) or Art. 121(3) (unrated 20%), with no national-currency
    sovereign-derived channel. There is no `art_119_2` branch and no domestic-currency
    short-term institution risk-weight constant in `data/tables/crr_risk_weights.py`.

    **Materiality.** For UK-domestic sterling-funded short-term claims the gap is
    immaterial — Art. 120(2) and Art. 121(3) already converge on 20%, matching the
    Art. 119(3) floor. The gap **is** material for cross-border short-term exposures
    where the counterparty institution is incorporated in a third country whose
    sovereign benefits from Art. 114(6)/(7) preferential domestic-currency treatment:
    in those cases the calculator overstates RW by skipping the Art. 119(2)
    one-CQS-step-down channel.

    **Operational note.** Firms with material exposures in this corner case must
    apply the Art. 119(2)/(3) override outside the engine until the branch is
    implemented. The CRR-only nature of the path means this gap will not affect
    Basel 3.1 calculations from 1 January 2027 — PS1/26 blanks Art. 119(2)/(3)/(4)
    entirely (see the "Removed under Basel 3.1" callout above).

!!! info "User-guide cross-reference"
    See [User Guide — Institution Exposures § Short-Term Exposures](../../user-guide/exposure-classes/institution.md#short-term-exposures)
    for the user-facing summary of this CRR-only path and its Basel 3.1 removal
    (the "CRR Art. 119(2)/(3) National-Currency Preferential — Removed under
    Basel 3.1" warning admonition closing that section). The "Regulatory References"
    table at the foot of that page distinguishes the three short-term rows:
    Art. 120(2) Table 4 (general rated), Art. 121(3) (unrated), and Art. 119(2)/(3)
    (national-currency, CRR only — blanked in PS1/26).

!!! warning "Correction: CRR has no Table 4A"
    CRR Tables 3 and 4 both use the **institution's own ECAI rating** — Table 3 for
    general maturities (Art. 120(1)), Table 4 for short-term (Art. 120(2)). The
    sovereign-derived approach for **unrated** institutions is Art. 121 (Table 5).
    Earlier versions of this spec incorrectly labelled Table 4 as "Sovereign-Derived"
    and included a non-existent "Table 4A".

!!! info "Basel 3.1 — Table 4A: Short-Term ECAI Assessments (Art. 120(2B))"
    Basel 3.1 introduces Table 4A for institutions with a specific **short-term ECAI
    assessment** (as opposed to a long-term rating applied to a short-term exposure).
    Table 4A uses the short-term CQS scale:

    | Short-Term CQS | 1 | 2 | 3 | 4 | 5 |
    |----------------|---|---|---|---|---|
    | Risk Weight | 20% | 50% | 100% | 150% | 150% |

    Art. 120(3) governs the interaction: where no short-term rating exists, Table 4
    applies; where a short-term rating yields a lower or equal RW, Table 4A applies;
    where it yields a worse RW, unrated short-term claims against that obligor also
    receive the higher weight.

## Corporate Exposures (CRR Art. 122)

| CQS | Risk Weight |
|-----|-------------|
| 1 | 20% |
| 2 | 50% |
| 3 | 100% |
| 4 | 100% |
| 5 | 150% |
| 6 | 150% |
| Unrated | 100% |

## Short-Term Assessments (CRR Art. 131, Table 7)

Where an exposure has a specific short-term ECAI assessment, Art. 131 provides a dedicated
CQS mapping. This applies to short-term assessments on institutions and corporates.

**Table 7 — Short-Term ECAI Assessment Risk Weights (Art. 131)**

| Short-Term CQS | Risk Weight |
|----------------|-------------|
| 1 | 20% |
| 2 | 50% |
| 3 | 100% |
| 4 | 150% |
| 5 | 150% |
| 6 | 150% |

!!! note "Implementation Status"
    Short-term ECAI assessment mapping (Art. 131) is not yet implemented. The calculator
    currently uses long-term CQS tables for all exposures. A `has_short_term_ecai` schema
    field would be needed to route to this table.

## CIU Exposures (CRR Art. 132)

!!! warning "Art. 132 Omitted from UK CRR"
    Art. 132 was **omitted from UK onshored CRR** and CIU treatment is instead governed by
    the **PRA Rulebook** via Art. 132a–132c. Under PRA rules, the fallback risk weight for
    CIUs that cannot be looked through is **1,250%** (Art. 132(2) as modified). Institutions
    may use a look-through approach (Art. 132a), a mandate-based approach (Art. 132b), or
    apply the 1,250% fallback (Art. 132c).

## Retail Exposures (CRR Art. 123)

All qualifying retail exposures receive a flat **75%** risk weight.

### Payroll / Pension Loans (CRR Art. 123, CRR2)

Introduced by CRR2 (Regulation (EU) 2019/876, amendment F68), CRR Art. 123 second subparagraph
assigns a **35%** risk weight to loans granted to pensioners or employees with permanent contracts
against unconditional transfer of salary or pension, subject to four conditions:

- **(a)** unconditional payroll/pension deduction authorisation to the credit institution;
- **(b)** insurance covering death, inability to work, unemployment, or salary/pension reduction;
- **(c)** aggregate loan payments ≤ 20% of net monthly salary/pension;
- **(d)** original maturity ≤ 10 years.

!!! warning "Code Divergence — CRR Path"
    The CRR code path (`sa/calculator.py`) does not implement the 35% payroll/pension treatment.
    All CRR retail exposures receive the flat 75% weight regardless of the `is_payroll_loan` flag.
    The `B31_RETAIL_PAYROLL_LOAN_RW` constant and `is_payroll_loan` check exist only in the Basel 3.1
    branch. This is a known code gap — the 35% treatment should also apply under CRR (since CRR2).

### Basel 3.1 Retail Sub-Treatments (Art. 123)

Basel 3.1 restructures Art. 123 into numbered paragraphs and introduces new sub-categories.
The payroll/pension 35% treatment is **carried forward unchanged** from CRR2 into Art. 123(4).

| Sub-Treatment | Risk Weight | Condition | Reference |
|---------------|-------------|-----------|-----------|
| Regulatory retail (non-transactor) | 75% | Meets Art. 123A qualifying criteria, non-transactor | Art. 123(3)(b) |
| QRRE transactors | 45% | Qualifying revolving where balance repaid in full at each scheduled repayment date for the previous 12 months, or overdraft undrawn for the previous 12 months (PRA Glossary) | Art. 123(3)(a) |
| QRRE non-transactors | 75% | Qualifying revolving (Art. 123(2)), non-transactor | Art. 123(3)(b) |
| Payroll / pension loans | 35% | Carried forward from CRR2 — same 4 conditions (a)–(d) | Art. 123(4) |
| Non-regulatory retail | 100% | Retail exposure that fails Art. 123A qualifying criteria | Art. 123(3)(c) |

## Covered Bond Exposures (CRR Art. 129)

Covered bonds backed by eligible collateral pools receive preferential risk weights:

### CRR Covered Bond Risk Weights — Rated (Art. 129(4), Table 6A)

| CQS of Issuing Institution | Risk Weight |
|-----------------------------|-------------|
| 1 | 10% |
| 2 | 20% |
| 3 | 20% |
| 4 | 50% |
| 5 | 50% |
| 6 | 100% |

!!! info "No Unrated Row in Table 6A"
    Table 6A contains CQS 1–6 only. Unrated covered bonds are handled separately by
    Art. 129(5) — see derivation table below.

### CRR Covered Bond Risk Weights — Unrated (Art. 129(5))

Unrated eligible covered bonds are assigned a risk weight derived from the issuing
institution's senior unsecured risk weight:

| Institution Senior Unsecured RW | Covered Bond RW | Art. 129(5) Sub-Para |
|---------------------------------|-----------------|----------------------|
| 20% | 10% | (a) |
| 50% | 20% | (b) |
| 100% | 50% | (c) |
| 150% | 100% | (d) |

The institution RW is determined per Art. 120 (ECRA rated) or Art. 121 (sovereign-derived).
If the issuing institution itself is unrated under CRR, the sovereign-derived approach
(Art. 121, Table 5) provides the institution RW, which then maps through the table above.

### Eligibility Conditions (Art. 129(1)–(3), (7))

Covered bonds must meet the following to qualify for preferential treatment:

- Issued by a credit institution with registered office in the UK or EEA
- Subject to special public supervision protecting bond holders (Art. 129(7))
- Backed by one of: (a) residential mortgage loans ≤ 80% LTV, (b) commercial mortgage loans ≤ 60% LTV, (c) exposures to central/regional governments ≤ CQS 1–2, (d) exposures to credit institutions ≤ CQS 1–2
- Bond holders have priority claim in the event of issuer default
- Collateral meets Art. 208 valuation requirements and Art. 229(1) valuation rules (Art. 129(3))

### Pre-2007 Grandfathering (Art. 129(6))

CRR Art. 129(6) grandfathers covered bonds issued before 31 December 2007: they
retain access to the preferential rated and unrated risk weights in Art. 129(4)/(5)
**without** having to meet the eligible-collateral requirements of Art. 129(1)
or the Art. 208 / Art. 229(1) valuation requirements of Art. 129(3). The
grandfathering runs **until the bond's contractual maturity** — there is no sunset
date and no re-eligibility test on amendment.

This is an **eligibility carve-out only**: the risk weights themselves come from
the same Art. 129(4) Table 6A (rated) and Art. 129(5) derivation table (unrated)
that apply to post-2007 bonds. A grandfathered CRR covered bond at CQS 2 still
attracts 20%; a grandfathered unrated bond issued by a 50%-RW institution still
attracts 20%.

!!! quote "CRR Art. 129(6) — verbatim"
    "[CRR covered bonds] issued before 31 December 2007 are not subject to the
    requirements of paragraphs 1 and 3. They are eligible for the preferential
    treatment under paragraphs 4 and 5 until their maturity."

    *Source: CRR Art. 129(6), as onshored — see `docs/assets/crr.pdf` p.129.*

**Operational implication.** Pre-2007 bonds in run-off are common in legacy UK
covered bond programmes. Where the bond cannot be re-evidenced against modern
Art. 129(1)(a)–(g) cover-pool eligibility — for example, because the cover pool
includes asset types that pre-date the current eligible-asset list, or because
LTV / valuation evidence to Art. 208 standards is unavailable — the firm should
flag the issue date and rely on Art. 129(6) rather than re-classifying the bond
out of the covered bond class. The Art. 129(7) portfolio-information /
semi-annual disclosure conditions are **not** disapplied by para (6) and remain
required for ongoing preferential treatment.

!!! info "Basel 3.1 delta — grandfathering retained, scope tightened"
    PRA PS1/26 Art. 129(6) **retains** the pre-2007 grandfathering on the same
    "until maturity" basis, but narrows it: the grandfathered bond must still
    meet the Art. 129(7) portfolio-information requirements, and the carve-out
    is now drafted as disapplying paragraphs 1 and 3 only (eligible assets and
    valuation), not paragraph 7. PS1/26 wording: *"CRR covered bonds issued
    before 31 December 2007 which meet the requirements of paragraph 7 shall be
    eligible covered bonds until their maturity and shall not be subject to the
    requirements of paragraphs 1 and 3."* (PRA PS1/26 Art. 129(6),
    `docs/assets/ps126app1.pdf` p.62.)

    Net effect: a pre-2007 bond that was already meeting Art. 129(7) under CRR
    transitions into the Basel 3.1 regime without re-papering. A pre-2007 bond
    that has *not* been meeting Art. 129(7) loses preferential treatment from
    1 January 2027 — even though it would have remained eligible under CRR
    Art. 129(6) (which made no explicit reference to para 7).

### Basel 3.1 Covered Bond Changes (Art. 129)

PRA PS1/26 modifies Art. 129 in-place — there is no separate "Art. 129A".

!!! warning "PRA Deviation from BCBS — Rated Risk Weights Unchanged"
    BCBS CRE20.28–29 reduced rated covered bond risk weights (CQS 2: 20%→15%,
    CQS 4–6: collapsed to 50%). **PRA did not adopt these reductions.** PRA PS1/26
    Art. 129(4) Table 7 is identical to CRR Table 6A — all six CQS values are unchanged.

**Rated (Art. 129(4), Table 7):** Identical to CRR Table 6A above — no changes.

**New due diligence requirement (Art. 129(4A)):** Institutions must conduct due diligence
on external credit assessments. If the analysis reflects higher risk than the CQS implies,
the institution must assign at least one CQS step higher than the external assessment.

**Unrated (Art. 129(5)):** The derivation table is expanded from 4 to 7 entries to
accommodate the new institution risk weights introduced by ECRA and SCRA:

| Institution Senior Unsecured RW | Covered Bond RW | Art. 129(5) Sub-Para | Change |
|---------------------------------|-----------------|----------------------|--------|
| 20% | 10% | (a) | Unchanged |
| 30% | 15% | (aa) | **New** |
| 40% | 20% | (ab) | **New** |
| 50% | 25% | (b) | ↓ from 20% |
| 75% | 35% | (ba) | **New** |
| 100% | 50% | (c) | Unchanged |
| 150% | 100% | (d) | Unchanged |

The new entries (aa), (ab), (ba) correspond to B31 institution risk weights that did not
exist under CRR: 30% (ECRA CQS 2), 40% (SCRA Grade A), 75% (SCRA Grade B).

!!! success "P1.113 Fixed — B31 Rated Covered Bond Risk Weights"
    `B31_COVERED_BOND_RISK_WEIGHTS` in `b31_risk_weights.py` now uses the correct PRA
    Table 7 values (identical to CRR). Previously used BCBS CRE20 values which
    understated capital for CQS 2 (15%→20%) and CQS 6 (50%→100%).

!!! note "Implementation Status"
    Covered bonds are implemented as a separate exposure class under Art. 112(m).
    Rated risk weights use CQS join tables; unrated uses the Art. 129(5) derivation chain.
    CRR: institution CQS → institution RW → CB RW via `COVERED_BOND_UNRATED_DERIVATION`.
    B31: SCRA grade → CB RW via `B31_COVERED_BOND_UNRATED_FROM_SCRA`.

## High-Risk Exposures (Art. 128)

Exposures associated with particularly high risk receive **150%** risk weight. Assessment
criteria per Art. 128(3): (a) high risk of loss from obligor default; (b) impossible to
adequately assess whether (a) applies.

Examples of high-risk items include speculative immovable property financing and other
exposures designated by the PRA. Under the Art. 112 Table A2 exposure class waterfall,
equity (priority 3) takes precedence over high-risk items (priority 4) — venture capital
and private equity exposures are classified as equity under Art. 133, not as high-risk
items under Art. 128.

!!! warning "Art. 128 Omitted from UK CRR (SI 2021/1078)"
    Art. 128 was **omitted from UK onshored CRR** by The Capital Requirements Regulation
    (Amendment) Regulations 2021 (SI 2021/1078), reg. 6(3)(a), effective 1 January 2022.
    The high-risk exposure class is a **dead letter under current UK CRR** (pre-2027).
    Exposures that would otherwise be classified as high-risk should fall through to
    their counterparty's standard exposure class (e.g., equity at 100% per Art. 133(2),
    or corporate at the applicable CQS weight).

    Under **PRA PS1/26** (Basel 3.1, effective 1 January 2027), Art. 128 is **re-introduced**
    with paragraphs 1 and 3 retained (paragraph 2 left blank — the original EU CRR
    Art. 128(2) list of specific categories such as venture capital and speculative RE
    is not carried forward). The 150% risk weight applies from 2027.

!!! bug "Code Note (D3.12)"
    The calculator's CRR engine path currently applies Art. 128 (150%) to HIGH_RISK
    exposures despite the UK CRR omission. Under strict UK CRR treatment, these
    exposures should fall through to their standard exposure class. The Basel 3.1
    engine path correctly applies Art. 128.

## Residential Mortgage Exposures (CRR Art. 125)

Art. 125(2)(d) applies a **proportion-based split** — the 35% risk weight is
assigned only to the **part of the loan that does not exceed 80% of the market
value** (or 80% of the mortgage lending value, where rigorous MLV criteria
apply in the United Kingdom). The remainder of the loan falls back to the
counterparty's **unsecured exposure risk weight** under Art. 124(1) (e.g. 75%
for a retail counterparty under Art. 123, or the applicable corporate /
institution / SME weight where the borrower is non-retail).

!!! quote "Art. 125(2)(d) — verbatim (CRR p. 124)"
    "unless otherwise determined under Article 124(2), the part of the loan to
    which the 35 % risk weight is assigned does not exceed 80 % of the market
    value of the property in question or 80 % of the mortgage lending value of
    the property in question if rigorous criteria are in force at the time in
    the United Kingdom for the assessment of the mortgage lending value."

!!! quote "Art. 124(1) residual — verbatim (CRR p. 122)"
    "The part of the exposure that exceeds the mortgage value of the immovable
    property shall be assigned the risk weight applicable to the unsecured
    exposures of the counterparty involved."

**Mechanism — proportion-based split (mirrors Art. 126 CRE).** This is **not**
an LTV-band table lookup: the regulation does not assign a single risk weight
to the whole exposure based on which LTV band it falls into. Instead, the loan
is partitioned into a *secured portion* (capped at 80% of property value) which
receives 35%, and a *residual portion* which receives the counterparty's
unsecured RW. Where the entire loan is within the secured portion (LTV ≤ 80%)
the residual is zero and 35% applies to the whole exposure. The two cases below
are therefore the same proportion-based mechanism — not two distinct bands.

| Loan position vs property value | Treatment |
|---------------------------------|-----------|
| Entire loan ≤ 80% of property value (LTV ≤ 80%) | 35% on whole exposure (residual = 0) |
| Loan exceeds 80% of property value (LTV > 80%) | 35% on the portion up to 80% of property value; counterparty unsecured RW on the excess |

**Blended formula (general form):**

```
secured_share = min(1.0, 0.80 / LTV)
avg_RW = 0.35 × secured_share + counterparty_unsecured_RW × (1.0 - secured_share)
```

For a retail mortgage borrower (counterparty unsecured RW = 75% per Art. 123),
the formula reduces to:

```
avg_RW = 0.35 × (0.80 / LTV) + 0.75 × ((LTV - 0.80) / LTV)    (LTV > 0.80, retail counterparty)
```

**Worked example — retail residential mortgage at 90% LTV.** £200k loan
secured on a property valued at £222.2k (LTV = 0.90). Apply the proportion-
based split:

- Secured portion = 80% × £222.2k = £177.8k → 35% RW.
- Residual portion = £200k − £177.8k = £22.2k → 75% RW (Art. 123 retail
  unsecured).
- `secured_share = 0.80 / 0.90 = 0.889`.
- `avg_RW = 0.35 × 0.889 + 0.75 × 0.111 = 0.311 + 0.0833 = 0.3944` → **39.4%**.
- RWA = £200k × 39.4% = **£78,889**.

A naïve LTV-band reading ("90% LTV → 75%") would assign 75% to the whole
£200k loan and produce £150k of RWA — almost twice the regulatory result.

**Art. 125(2) qualifying conditions** for the 35% secured portion:

- (a) Property value does not materially depend on borrower credit quality
- (b) Borrower risk does not materially depend on property/project performance —
  repayment capacity from other sources (i.e. not income-dependent)
- (c) Art. 208 requirements and Art. 229(1) valuation rules are met
- (d) The 35% risk weight applies only to the part of the loan not exceeding
  80% of market value (or 80% of MLV where the UK rigorous-MLV criteria apply).
  The exposure must be fully and completely secured by mortgages on residential
  property which is or shall be occupied or let by the owner (Art. 125(1)(a))

!!! info "Counterparty scope (Art. 125 vs `RETAIL_MORTGAGE`)"
    Art. 125 is **not** restricted to retail individuals — any exposure secured
    by qualifying residential property may receive the 35% / residual-RW split,
    regardless of whether the borrower is an individual, SME, corporate, or
    institution. In the calculator the eligibility routes are:

    - **`RETAIL_MORTGAGE`** — assigned by `engine/classifier.py` when the
      exposure is `is_mortgage=True` and the counterparty is an individual
      (or already classified as `RETAIL_OTHER`). This bucket consumes the
      Art. 125 split directly in the SA calculator.
    - **`RESIDENTIAL_MORTGAGE`** — assigned by the SA real-estate
      loan-splitter (`engine/re_splitter.py`) for residential-property-
      collateralised SA exposures whose `exposure_class` is **not** already
      RE-typed (e.g. `CORPORATE`, `INSTITUTION`). The split applies the
      same 35% secured / counterparty-RW residual decomposition — see
      [Real Estate Loan-Splitter](#real-estate-loan-splitter-crr-art-125126-pra-ps126-art-124f124h).

    The qualifying-condition gate (Art. 125(2)(a)–(d)) is presently inferred
    from the input `is_mortgage` flag and the residential-collateral inputs;
    the calculator does not independently verify (a)–(c). Institutions remain
    responsible for evidencing the Art. 125(2) conditions for any exposure
    routed to either bucket.

## Commercial Real Estate (CRR Art. 126)

Exposures secured by mortgages on commercial immovable property. Art. 126(2)(d) applies a
**proportion-based split** analogous to Art. 125 for residential — the 50% risk weight applies
only to the part of the loan that does not exceed 50% of market value (or 60% of mortgage
lending value). The remainder falls to the counterparty's standard exposure class weight.

**Art. 126(2) qualifying conditions** for the 50% secured portion:

- (a) Property value does not materially depend on borrower credit quality
- (b) Borrower risk does not materially depend on property/project performance — repayment
  capacity from other sources (i.e. not income-dependent)
- (c) Art. 208 requirements and Art. 229(1) valuation rules are met
- (d) 50% RW assigned to the part of the loan not exceeding 50% of market value or 60% of MLV

| LTV | Treatment |
|-----|-----------|
| LTV ≤ 50% | 50% on whole exposure (entire loan within secured portion) |
| LTV > 50% | Split: 50% on portion up to 50% MV, counterparty RW on excess |

**Blended formula for LTV > 50%:**

```
secured_share = min(1.0, 0.50 / LTV)
avg_RW = 0.50 × secured_share + counterparty_RW × (1.0 - secured_share)
```

!!! note "Income Cover and Loss Rate Derogation"
    Art. 126(2)(b) requires that repayment does not materially depend on cash flows from
    the property. Art. 126(3)–(4) provides a derogation: where the PRA has determined that
    loss rates for CRE-secured loans do not exceed 0.3% on the secured portion and 0.5%
    overall, condition (b) may be waived (allowing income-dependent CRE to qualify).

!!! bug "Code Divergence (D3.36)"
    The calculator implements Art. 126 as a **binary whole-loan** treatment (50% if
    LTV ≤ 50% with income cover, 100% otherwise) rather than the proportion-based split
    required by Art. 126(2)(d). For exposures with LTV > 50% that meet all qualifying
    conditions, the code assigns 100% to the entire exposure instead of splitting: 50% on
    the portion up to 50% MV and counterparty RW on the excess.

## LTV Definition for Basel 3.1 Real Estate (Art. 124C)

Basel 3.1 introduces a formal regulatory LTV definition in Art. 124C. The numerator
includes outstanding balance + undrawn committed amounts + **all prior/pari passu
charges** (Art. 124C(3)). CRM is excluded except pledged deposit accounts meeting
on-balance-sheet netting requirements.

!!! info "Full specification"
    See [Basel 3.1 SA Risk Weights — Art. 124C](../basel31/sa-risk-weights.md#real-estate-ltv-definition-art-124c)
    for the complete LTV definition, prior charges stacking rules, and implementation
    field mapping.

**CRR comparison:** CRR Art. 124(1)/125(1)/126(1) reference "the value of the property"
and "the part of the loan" but do not have an explicit Art. 124C-style LTV definition
with prior charge stacking requirements. The obligation to include senior charges in
the LTV numerator is a Basel 3.1 addition.

---

## Basel 3.1 Residential Real Estate (PRA PS1/26 Art. 124F-124G)

!!! info "Material Dependency Classification (Art. 124E) — New in Basel 3.1"
    Basel 3.1 introduces Art. 124E, a structured classification test that replaces the
    CRR's informal income-dependency distinction. Under CRR, Art. 125 (general) vs
    Art. 126 (income-producing) had no formal classification gate. Art. 124E defines
    residential RE as materially dependent by default, with five exceptions (primary
    residence, three-property limit, SPE guarantor, social housing, cooperative).
    Art. 124E(5)/(7) additionally impose reassessment obligations (new-loan-to-obligor
    trigger for residential, annual trigger for commercial) that have no CRR analogue —
    CRR had no codified reassessment cadence for the Art. 125/126 income-dependency
    distinction. See [Art. 124E specification](../basel31/sa-risk-weights.md#real-estate-material-dependency-classification-art-124e).

### General Residential — Loan-Splitting (Art. 124F)

Not materially dependent on cash flows from the property (per [Art. 124E](../basel31/sa-risk-weights.md#real-estate-material-dependency-classification-art-124e) exceptions). PRA adopted the **loan-splitting approach** (not the BCBS CRE20.73 whole-loan table):

- **Secured portion** (up to 55% of property value): **20%** risk weight
- **Residual portion** (above 55% of property value): **counterparty risk weight** (Art. 124L)

```
secured_share = min(1.0, 0.55 / LTV)
RW = 0.20 × secured_share + counterparty_RW × (1.0 - secured_share)
```

**Counterparty risk weight** (Art. 124L):

| Counterparty Type | RW |
|-------------------|----|
| Natural person (non-SME) | 75% |
| Retail-qualifying SME | 75% |
| Other SME (unrated) | 85% |
| Social housing | max(75%, unsecured RW) |
| Other | Unsecured counterparty RW |

**Junior charges** (Art. 124F(2)): If a prior or pari passu charge exists, the 55% threshold is reduced by the amount of the prior charge. The effective secured portion decreases, increasing the blended risk weight.

### Income-Producing Residential — Whole-Loan (Art. 124G, Table 6B)

Materially dependent on cash flows from the property (e.g., buy-to-let). Whole-loan approach — single risk weight on entire exposure:

| LTV Band | Risk Weight |
|----------|-------------|
| ≤ 50% | 30% |
| 50-60% | 35% |
| 60-70% | 40% |
| 70-80% | 50% |
| 80-90% | 60% |
| 90-100% | 75% |
| > 100% | 105% |

**Junior charge multiplier** (Art. 124G(2)): **1.25x** applied to the whole-loan risk weight when LTV > 50% and prior/pari passu charges exist.

### Commercial RE — General, Loan-Splitting (Art. 124H)

Not materially dependent on cash flows:

**Natural person / SME**: Split approach — **60%** on portion up to 55% of property value, counterparty RW on remainder.

```
secured_share = min(1.0, 0.55 / LTV)
RW = 0.60 × secured_share + counterparty_RW × (1.0 - secured_share)
```

**Other counterparties** (Art. 124H(3)):

```
RW = max(60%, min(counterparty_RW, income_producing_RW))
```

Where `income_producing_RW` is the Art. 124I whole-loan weight for the same LTV band. This formula ensures the RW is at least 60% (the secured portion floor) but no more than the lower of the counterparty's unsecured RW or the income-producing table rate.

### Commercial RE — Income-Producing (Art. 124I)

Materially dependent on cash flows:

| LTV Band | Risk Weight |
|----------|-------------|
| ≤ 80% | 100% |
| > 80% | 110% |

**Junior charge absolute override** (Art. 124I(3)) — replaces Art. 124I(1)/(2) base, not a multiplier:

| LTV Band | Absolute RW |
|----------|-------------|
| ≤ 60% | 100% |
| 60-80% | 125% |
| > 80% | **137.5%** |

### Other Real Estate (Art. 124J)

Non-regulatory real estate (doesn't meet [Art. 124A qualifying criteria](../basel31/sa-risk-weights.md#real-estate-qualifying-criteria-art-124a)):

| Type | Risk Weight |
|------|-------------|
| Income-dependent | 150% |
| RESI non-dependent | Counterparty RW |
| CRE non-dependent | max(60%, counterparty RW) |

### ADC Exposures (Art. 124K)

| Condition | Risk Weight |
|-----------|-------------|
| Default | 150% |
| Residential with pre-sales/equity at risk | 100% |

## Basel 3.1 Corporate Exposures (PRA PS1/26 Art. 122(2) Table 6)

| CQS | Rating Equivalent | CRR Risk Weight | Basel 3.1 Risk Weight (PRA) |
|-----|-------------------|-----------------|---------------------------|
| 1 | AAA to AA- | 20% | 20% |
| 2 | A+ to A- | 50% | 50% |
| 3 | BBB+ to BBB- | **100%** | **75%** |
| 4 | BB+ to BB- | 100% | 100% |
| 5 | B+ to B- | **150%** | **150%** |
| 6 | CCC+ and below | 150% | 150% |
| Unrated | — | 100% | 100% |

!!! warning "PRA vs BCBS Deviation for CQS 5"
    BCBS CRE20.42 sets CQS 5 = **100%** (reduced from CRR 150%). However, PRA PS1/26 Art. 122(2) Table 6 retains CQS 5 = **150%** (same as CQS 6). The PRA did not adopt the BCBS reduction for this credit quality step. The calculator must use the PRA value (150%), not the BCBS value (100%).

### Additional Basel 3.1 Corporate Treatments

| Treatment | Risk Weight | Condition |
|-----------|-------------|-----------|
| Investment-grade corporate (Art. 122(6)(a)) | 65% | Unrated, institution IG assessment, requires PRA permission |
| Non-investment-grade corporate (Art. 122(6)(b)) | **135%** | Unrated, assessed as non-IG, requires PRA permission |
| SME corporate (Art. 122(11)) | 85% | SME qualifying corporate (replaces CRR 100% + 0.7619 SF) |
| Subordinated debt (CRE20.49) | 150% | Overrides all other treatments |

!!! note "PRA Permission Required for Investment Grade Assessment (Art. 122(6)–(10))"
    The 65%/135% split requires **prior PRA permission** and demonstration of sound credit
    risk management practices (Art. 122(6)). Without permission, all unrated non-SME corporates
    receive **100%** (Art. 122(5)). The investment grade definition (Art. 122(9)) requires
    adequate capacity to meet financial commitments, robust against adverse economic cycles —
    this is the institution's own internal assessment (Art. 122(10)), not an external rating.
    SME corporates (Art. 122(11)) receive **85%** regardless of IG status. For IRB output
    floor S-TREA (Art. 122(8)), firms may elect the 65%/135% split instead of flat 100%.

## Basel 3.1 Institution Exposures (CRE20.16-21)

Rated institutions use ECRA (PRA PS1/26 Art. 120 Table 3). CQS 2 is reduced from CRR 50% to **30%** under Basel 3.1 ECRA. Unrated institutions use SCRA:

| SCRA Grade | Risk Weight (>3m) | Risk Weight (≤3m) | Criteria |
|------------|--------------------|--------------------|----------|
| A | 40% | 20% | Meets all minimum requirements + buffers |
| A (enhanced) | 30% | 20% | CET1 ≥ 14% AND leverage ratio ≥ 5% |
| B | 75% | 50% | Meets minimum requirements |
| C | 150% | 150% | Below minimum requirements |

ECRA (rated) takes precedence over SCRA (unrated). SCRA does not apply under CRR.

## Equity Exposures (CRR Art. 133 / PRA PS1/26 Art. 133)

### CRR Equity Risk Weights

Art. 133(2) assigns a **flat 100%** to all equity. Art. 133 has only 3 paragraphs — references to "Art. 133(3)" or "Art. 133(4)" with differentiated weights are erroneous (those values belong to Art. 155 IRB Simple).

| Equity Type | Risk Weight | Reference |
|-------------|-------------|-----------|
| Central bank / sovereign equity | 0% | Sovereign treatment |
| All other equity (listed, unlisted, PE, etc.) | 100% | Art. 133(2) flat |
| CIU (fallback) | 1,250% | Art. 132c (PRA Rulebook) |

!!! note "Art. 132 Omitted from UK CRR"
    Original Art. 132 was omitted from UK onshored CRR. CIU treatment is governed by
    PRA Rulebook Art. 132a (look-through), Art. 132b (mandate-based), and Art. 132c
    (fallback at 1,250%). Cross-references from Art. 133 to Art. 128 (high-risk items)
    are dead letters under UK CRR since Art. 128 was also omitted by SI 2021/1078.

!!! warning "Previous Spec Error Corrected"
    This table previously showed Unlisted=150% (Art. 133(3)) and PE/VC=190% (Art. 133(4)). These paragraph numbers and values were fabricated. The 150%/190% values are from **Art. 155** (IRB Simple Method), not Art. 133. PE/VC that qualifies as high-risk is treated under Art. 128 (150%), not Art. 133. See [Equity Approach Specification](equity-approach.md) for full details.

### Basel 3.1 Equity Risk Weights (PRA PS1/26 Art. 133)

| Equity Type | Risk Weight | Reference |
|-------------|-------------|-----------|
| Subordinated debt / non-equity own funds | 150% | Art. 133(1) |
| Standard equity (listed) | 250% | Art. 133(3) |
| Higher risk (unlisted + business < 5 years) | 400% | Art. 133(4) |
| Legislative equity (carve-out for govt-mandated holdings) | 100% | Art. 133(6) |

!!! warning "PRA Deviation from BCBS"
    PRA Art. 133 does **not** include the BCBS "CQS 1-2 speculative unlisted = 100%" or "CQS 3-6/unrated speculative = 150%" tiers. PRA uses a simpler structure: listed = 250%, higher-risk (unlisted + business < 5 years, per Glossary p.5) = 400%. PE/VC is only higher-risk if it meets both criteria.

**Note:** Basel 3.1 removes IRB equity approaches (Art. 147A). All equity uses SA risk weights. See [Equity Approach](equity-approach.md) for full details including CIU treatment and transitional schedule.

## Defaulted Exposures (CRR Art. 127 / PRA PS1/26 Art. 127)

### CRR Default Risk Weights

| Condition | Risk Weight |
|-----------|-------------|
| Specific provisions ≥ 20% of the unsecured exposure value before provisions | 100% |
| Specific provisions < 20% of the unsecured exposure value before provisions | 150% |

!!! info "CRR Art. 127(1) Denominator"
    The CRR denominator is: "the unsecured part of the exposure value if those specific
    credit risk adjustments and deductions were not applied" — i.e., the pre-provision
    unsecured exposure value. The code reconstructs this as `(ead + provision_deducted) ×
    unsecured_pct`. The numerator includes both specific credit risk adjustments and
    amounts deducted per Art. 36(1)(m).

!!! note "CRR Art. 127(3)–(4)"
    CRR also provides flat 100% for defaulted exposures fully and completely secured by
    mortgages on residential property (Art. 127(3)) or commercial immovable property
    (Art. 127(4)), regardless of provision level.

### Basel 3.1 Default Risk Weights (PRA PS1/26 Art. 127)

| Condition | Risk Weight |
|-----------|-------------|
| Specific provisions ≥ **20%** of the outstanding amount of the item or facility | 100% |
| Specific provisions < **20%** of the outstanding amount of the item or facility | 150% |
| RESI RE non-dependent (Art. 127(1A)) in default | **100% (always)** — regardless of provision level |

!!! warning "Denominator Difference from CRR"
    Both CRR and Basel 3.1 use a **20%** provision threshold, but the **denominator differs**:

    - **CRR Art. 127(1):** "the unsecured part of the exposure value if those specific
      credit risk adjustments and deductions were not applied" — the **pre-provision
      unsecured** exposure value
    - **PRA PS1/26 Art. 127(1):** "the outstanding amount of the item or facility" — the
      **gross outstanding** amount (not limited to the unsecured portion)

    The PRA denominator is typically larger (includes the secured portion), making it
    easier to reach the 20% threshold for a given level of provisioning.

!!! warning "Code Divergence — B31 Path (D3.19)"
    The Basel 3.1 code path uses `unsecured_ead` (post-provision unsecured exposure value)
    as the denominator, not the "outstanding amount of the item or facility" specified by
    PRA PS1/26 Art. 127(1). This underestimates the denominator for partially collateralised
    exposures, making it harder to reach the 20% threshold than the regulation intends.

## Basel 3.1 SA Specialised Lending (Art. 122A-122B)

New Basel 3.1 SA exposure class with risk weights distinct from general corporates:

| SL Type | Phase | Risk Weight |
|---------|-------|-------------|
| Object finance | — | 100% |
| Commodities finance | — | 100% |
| Project finance | Pre-operational | 130% |
| Project finance | Operational | 100% |
| Project finance | High-quality operational | 80% |

Rated specialised lending exposures use the corporate CQS table (Art. 122A(3)).

## Other Items (CRR Art. 134 / PRA PS1/26 Art. 134)

| Item | Risk Weight | Reference |
|------|-------------|-----------|
| Cash and equivalent (notes, coins) | 0% | Art. 134(1) |
| Gold bullion (held in own vaults or allocated) | 0% | Art. 134(4) |
| Items in course of collection | 20% | Art. 134(3) |
| Repo-style transactions — RW of underlying asset | Asset RW | Art. 134(5) |
| Nth-to-default basket credit derivatives | Per Art. 266-270 | Art. 134(5) |
| Tangible assets (premises, equipment) | 100% | Art. 134(2) |
| Prepaid expenses, accrued income | 100% | Art. 134(2) |
| Residual value of leased assets | 1/t × 100% (t = remaining lease years, min 1) | Art. 134(6) |
| All other | 100% | Art. 134(2) |

## Export Credit Agency Assessments (CRR Art. 137 / Table 9)

Where an Export Credit Agency (ECA) credit assessment is nominated under Art. 137(1) — either an OECD consensus risk score or a published assessment associated with one of the eight **minimum export insurance premiums (MEIPs)** — the exposure is assigned a risk weight directly from Art. 137(2) Table 9. Each MEIP score (0–7) maps **directly** to a risk weight; there is **no intermediate CQS step**.

**Table 9 — MEIP risk weights (verbatim, Art. 137(2)):**

| MEIP score | Risk weight |
|------------|-------------|
| 0 | 0% |
| 1 | 0% |
| 2 | 20% |
| 3 | 50% |
| 4 | 100% |
| 5 | 100% |
| 6 | 100% |
| 7 | 150% |

This mapping is used for sovereign exposures (Art. 114) where an ECA assessment is recognised, and — via the institution-from-sovereign rules — for deriving institution risk weights where the sovereign itself is rated only by an ECA.

!!! note "Implementation Status"
    MEIP score lookup is not yet implemented. The calculator currently requires ECAI CQS for rated exposures. Direct MEIP-to-risk-weight mapping per Art. 137(2) Table 9 is a future enhancement.

## Basel 3.1 Changes Summary

- **Due diligence obligation** (Art. 110A): New prerequisite for all SA risk weight assignments — Done
- **Residential RE loan-splitting** (Art. 124F): 20% on ≤55% LTV, counterparty RW on residual — Done
- **Residential RE income-producing** (Art. 124G): Whole-loan LTV table (30%-105%) — Done
- **Commercial RE loan-splitting** (Art. 124H): 60% on ≤55% LTV, counterparty RW on residual — Done
- **Commercial RE other counterparties** (Art. 124H(3)): max/min formula — Done
- **Commercial RE income-producing** (Art. 124I): 100%/110% at ≤80%/>80% — Done
- **Junior charge treatment** (Art. 124F/G/I): RRE/RRE-income multipliers (125%/1.25×); CRE-income **absolute 100%/125%/137.5%** override (Art. 124I(3)) — Done
- **Other Real Estate** (Art. 124J): 150% income-dependent, counterparty RW otherwise — Done
- **Revised corporate CQS mapping** (Art. 122(2) Table 6): CQS 3 from 100% to 75% — Done. **Note:** PRA retains CQS 5 = 150% (BCBS CRE20.42 reduced to 100%, but PRA did not adopt this reduction)
- **SCRA for unrated institutions** (CRE20.18): Grade A/B/C risk weights replace flat 40% — Done
- **SCRA enhanced Grade A** (CRE20.19): 30% for CET1 ≥ 14% and leverage ratio ≥ 5% — Done
- **SCRA short-term maturity** (CRE20.20): Grade A/A_ENHANCED 20%, Grade B 50% for ≤3m exposures — Done
- **Investment-grade corporates** (Art. 122(6)(a)): 65% for unrated investment-grade (PRA permission required) — Done
- **Non-investment-grade corporates** (Art. 122(6)(b)): 135% for unrated non-IG (PRA permission required) — Done
- **SME corporate** (Art. 122(11)): 85% flat weight, replaces CRR 100% + supporting factor — Done
- **Subordinated debt** (CRE20.49): 150% flat, overrides all other treatments — Done
- **Equity** (Art. 133): 250% standard, 400% higher risk, 150% subordinated — Done
- **Retail transactor/non-transactor** (Art. 123): 45% QRRE transactors vs 75% non-transactors — Done
- **Payroll/pension loans** (CRR Art. 123, CRR2 / PRA PS1/26 Art. 123(4)): 35% — Done (Basel 3.1 only; CRR code gap)
- **Non-regulatory retail** (Art. 123(3)(c)): 100% — Done
- **SA Specialised Lending** (Art. 122A-122B): OF/CF=100%, PF pre-op=130%, PF op=100%, high-quality PF=80% — Done
- **Default exposures** (Art. 127): Provision-based 100%/150% with RESI RE always-100% exception — Done
- **Other items** (Art. 134): Cash=0%, gold=0%, collection=20%, tangible=100% — Done
- **Covered bonds** (Art. 129): CQS-based risk weights, eligibility criteria, unrated derivation, PRA deviation — Added
- **Pre-2007 covered bond grandfathering** (Art. 129(6)): CRR carve-out from Art. 129(1)/(3) eligibility tests retained until maturity; PRA PS1/26 Art. 129(6) retains the carve-out but additionally requires Art. 129(7) disclosure conditions — Added
- **RGLA/PSE/MDB/Int'l Org tables** (Art. 115-118): Missing from original spec — Added
- **ECA / MEIP scores** (Art. 137 Table 9): direct MEIP-score-to-risk-weight mapping (0–7 → 0%/0%/20%/50%/100%/100%/100%/150%) for sovereigns rated by an Export Credit Agency — Added
- **Short-term assessments** (Art. 131 Table 7): Short-term ECAI CQS mapping — Added
- **CIU treatment** (Art. 132/132a-132c): UK CRR omission noted, PRA Rulebook governs CIU — Added
- **Unrated institution sovereign-derived** (Art. 121 Table 5): Full sovereign-derived table — Added
- **Removal of SME supporting factor**: No longer applicable under Basel 3.1
- **Removal of 1.06 scaling factor**: Scaling factor set to 1.0 under Basel 3.1

## Key Scenarios

| Scenario ID | Description | Expected RW |
|-------------|-------------|-------------|
| CRR-A1 | UK Sovereign CQS 1 | 0% |
| CRR-A4 | Institution CQS 2 (Art. 120 Table 3) | 50% |
| CRR-A | Corporate unrated | 100% |
| CRR-A | Retail exposure | 75% |
| CRR-A | Residential mortgage LTV 60% | 35% |
| CRR-A | CRE with income cover, LTV 45% | 50% |
| B31-A2 | Corporate CQS 2 (Basel 3.1) | 50% |
| B31-A3 | Institution CQS 2 (Basel 3.1 ECRA, Art. 120 Table 3) | 30% |
| B31-A8 | SME corporate (Basel 3.1) | 85% |

## Acceptance Tests

| Group | Scenarios | Tests | Pass Rate |
|-------|-----------|-------|-----------|
| CRR-A: Standardised Approach | A1–A12 | 14 | 100% (14/14) |
| B31-A: Basel 3.1 SA | A1–A10 | 14 | 100% (14/14) |

## Real Estate Loan-Splitter (CRR Art. 125/126, PRA PS1/26 Art. 124F/H)

A new pipeline stage (`engine/re_splitter.py`, between `CRMProcessor` and the
SA calculator) physically partitions property-collateralised SA-bound
exposures whose `exposure_class` is **not** already RE-typed. The secured row
is reclassified to `RESIDENTIAL_MORTGAGE` / `COMMERCIAL_MORTGAGE` and capped
at the regulatory secured-LTV cap; the residual row keeps the original
counterparty class so the standard corporate / retail risk weight applies on
the remainder.

| Regime / class | Secured LTV cap | Secured RW | Residual RW |
|----------------|-----------------|------------|-------------|
| CRR Art. 125 (RRE) | 80% LTV | 35% | counterparty CQS RW |
| CRR Art. 126 (CRE, rental ≥ 1.5×) | 50% LTV | 50% | counterparty CQS RW |
| B3.1 Art. 124F (RRE) | 55% × property value (less prior charges) | 20% | Art. 124L counterparty type |
| B3.1 Art. 124H(1)-(2) (CRE NP/SME) | 55% × property value | 60% | counterparty CQS RW |
| B3.1 Art. 124H(3) (CRE other) | whole-loan, no split | n/a | `max(60%, min(cp_rw, Art. 124I RW))` |

**Eligibility & exclusions:** Income-producing RE continues to use the
existing whole-loan path (Art. 124G / Art. 124I bands). Defaulted, securitised,
covered-bond, equity, CIU, subordinated and high-risk exposures are excluded
from the split, as are exposures already classified as `RESIDENTIAL_MORTGAGE`
/ `RETAIL_MORTGAGE` / `COMMERCIAL_MORTGAGE` via the existing retail-mortgage
branch.

**CRR rental coverage (Art. 126(2)(d)):** Optional collateral input
`rental_to_interest_ratio`. When ≥ 1.5× the CRE split applies; when below
(or absent) the exposure stays in its original class and an `RE004`
informational warning is emitted.

**Audit & lineage:** Both child rows share a `split_parent_id` equal to the
parent `exposure_reference`; the child references are suffixed with `_sec`
and `_res` (or kept unchanged for the Art. 124H(3) whole-loan path).
`CRMAdjustedBundle.re_split_audit` captures one row per parent (parent EAD,
secured / residual EAD, effective cap, target class, regime). The sum of
child EADs reconciles exactly to the parent EAD.
