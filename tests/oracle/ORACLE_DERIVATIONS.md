# Oracle Derivations

This document is the **independent source of truth** for the oracle test suite.
Every expected RWA value in `expected_values.json` corresponds to one section
below, derived directly from the regulation with full intermediate arithmetic.

The companion package `derivations/` re-computes these values using only Python
stdlib (`math`, `statistics`). It does not import any `rwa_calc` code, and a
contract test parses it to prove that. The test suite asserts the engine's
output matches these independently-derived numbers within a tight tolerance
(relative error ≤ 1e-6).

**Sources.** CRR figures were read out of `docs/assets/crr.pdf` (Regulation (EU)
No 575/2013 as onshored and amended for the UK, generated 2026-03-02). Basel 3.1
figures were read out of `docs/assets/ps126app1.pdf` (PRA2026/1, effective
1 January 2027). Where PS1/26 renumbers, the article carries a
`[Note: This rule corresponds to Article NNN of CRR …]` line; the PS1/26 number
is quoted here because it is the operative one from 2027.

**Update protocol** — see `README.md`. The short version: this document and
`expected_values.json` are locked together by a SHA-256 hash. They may only
change in lockstep, with both the doc and the derivation modules updated and
re-derived.

**Conventions used throughout.**

- `RWA = EAD × RW` unless a supporting factor or a regulatory floor intervenes,
  in which case the section says so explicitly.
- Money is sterling. Where an article states a threshold in euro, the section
  says how the euro/sterling conversion was kept from affecting the answer.
- "Foreign" inputs (country `US`, currency `USD`) appear on sovereign, corporate
  and institution oracles purely to keep the UK-domestic 0% overrides
  (CRR Art. 114(4), PS1/26 Art. 114(4)) out of the way.

---

# Phase O1 — Standardised Approach

## O1(a) — UK CRR

### Central governments and central banks (Art. 114)

Art. 114(2) Table 1, read verbatim from the PDF:

| CQS | 1 | 2 | 3 | 4 | 5 | 6 |
|---|---|---|---|---|---|---|
| Risk weight | 0% | 20% | 50% | 100% | 100% | 150% |

Art. 114(1) assigns 100% where none of the paragraph 2–7 treatments apply, which
is the unrated case. Art. 114(4) assigns 0% to exposures to "the central
government of the United Kingdom and the Bank denominated and funded in
sterling".

## ORC-004 — SA sovereign, CQS 1 (CRR)

**Inputs:** EAD £1,000,000; class `central_govt_central_bank`; CQS 1; US/USD.
**Regulation:** Art. 114(2) Table 1, CQS 1 → 0%.
**Arithmetic:** `RW = 0.00`; `RWA = 1,000,000 × 0.00 = 0.00`.

## ORC-002 — SA sovereign, CQS 2 (CRR)

**Inputs:** EAD £5,000,000; class `central_govt_central_bank`; CQS 2; US/USD.
**Regulation:** Art. 114(2) Table 1, CQS 2 → 20%. Art. 114(4) is disapplied
because the country is not the UK and the currency is not sterling.
**Arithmetic:** `RW = 0.20`; `RWA = 5,000,000 × 0.20 = 1,000,000.00`.

## ORC-005 — SA sovereign, CQS 3 (CRR)

**Inputs:** EAD £1,000,000; CQS 3; US/USD.
**Regulation:** Art. 114(2) Table 1, CQS 3 → 50%.
**Arithmetic:** `RW = 0.50`; `RWA = 1,000,000 × 0.50 = 500,000.00`.

## ORC-006 — SA sovereign, CQS 4 (CRR)

**Inputs:** EAD £1,000,000; CQS 4; US/USD.
**Regulation:** Art. 114(2) Table 1, CQS 4 → 100%.
**Arithmetic:** `RW = 1.00`; `RWA = 1,000,000.00`.

## ORC-007 — SA sovereign, CQS 6 (CRR)

**Inputs:** EAD £1,000,000; CQS 6; US/USD.
**Regulation:** Art. 114(2) Table 1, CQS 6 → 150%.
**Arithmetic:** `RW = 1.50`; `RWA = 1,500,000.00`.

## ORC-008 — SA sovereign, unrated (CRR)

**Inputs:** EAD £1,000,000; no ECAI assessment; US/USD.
**Regulation:** Art. 114(1) — 100% unless a paragraph 2–7 treatment applies.
None does: there is no ECAI assessment for paragraph 2, and the counterparty is
neither the ECB (3) nor the UK central government (4).
**Arithmetic:** `RW = 1.00`; `RWA = 1,000,000.00`.

## ORC-009 — SA UK sovereign, sterling (CRR)

**Inputs:** EAD £1,000,000; CQS 3; country `GB`; currency `GBP`.
**Regulation:** Art. 114(4) — 0% regardless of the Table 1 weight the CQS would
otherwise give. The CQS of 3 is deliberately non-trivial so a failure to apply
Art. 114(4) surfaces as 50%, not as a coincidence.
**Arithmetic:** `RW = 0.00`; `RWA = 0.00`.

### Regional governments, PSEs, MDBs and international organisations (Art. 115–118)

Art. 116(1) Table 2 (unrated PSE, keyed on the central government's CQS):

| CQS of the central government | 1 | 2 | 3 | 4 | 5 | 6 |
|---|---|---|---|---|---|---|
| Risk weight | 20% | 50% | 100% | 100% | 100% | 150% |

Art. 116(5) makes that treatment available to a **third-country** PSE only where
the Treasury has determined the jurisdiction equivalent; absent that
determination the article directs a flat 100%. The PSE oracles therefore use a
UK PSE, so they test Table 2 rather than the equivalence gate.

## ORC-010 — SA UK regional government, sterling (CRR)

**Inputs:** EAD £1,000,000; class `rgla`; unrated; `GB`/`GBP`.
**Regulation:** Art. 115(5) — exposures to UK regional governments or local
authorities not covered by paragraphs 2–4, denominated and funded in sterling,
are assigned 20%.
**Arithmetic:** `RW = 0.20`; `RWA = 200,000.00`.

## ORC-011 — SA non-UK unrated regional government (CRR)

**Inputs:** EAD £1,000,000; class `rgla`; unrated; sovereign CQS 2; US/USD.
**Regulation:** Art. 115(1) — risk-weighted as exposures to institutions. For an
unrated counterparty that routes to Art. 121(1) Table 5, whose CQS-2 row is 50%.
**Arithmetic:** `RW = 0.50`; `RWA = 500,000.00`.

## ORC-012 — SA UK public sector entity, central government CQS 1 (CRR)

**Inputs:** EAD £1,000,000; class `pse`; unrated; central government CQS 1;
`GB`/`GBP`.
**Regulation:** Art. 116(1) Table 2, CQS 1 → 20%.
**Arithmetic:** `RW = 0.20`; `RWA = 200,000.00`.

## ORC-013 — SA UK public sector entity, central government CQS 3 (CRR)

**Inputs:** EAD £1,000,000; class `pse`; unrated; central government CQS 3;
`GB`/`GBP`.
**Regulation:** Art. 116(1) Table 2, CQS 3 → 100%.
**Arithmetic:** `RW = 1.00`; `RWA = 1,000,000.00`.

### Third-country PSEs and the Art. 116(5) equivalence determination

Art. 116(5), verbatim from `crr.pdf` p114:

> When competent authorities of a third country jurisdiction, which apply
> supervisory and regulatory arrangements at least equivalent to those applied
> in the [United Kingdom], treat exposures to public sector entities in
> accordance with paragraph 1 or 2, institutions **may** risk weight exposures
> to such public sector entities in the same manner. **Otherwise the
> institutions shall apply a risk weight of 100 %.**

Two lawful outcomes, selected by whether the determination has been made. The
six oracles below pin the whole input domain — the flag asserted, denied, and
simply not asserted, across both PSE entity types — on a third-country PSE whose
central government is CQS 1. All six agree with the engine.

They exist because this was first reported as a defect ("the equivalence flag is
inert"). That report was **wrong**: the flag had been passed to the driver under
a name that was not in its alias map, so it never reached
`cp_is_equivalent_jurisdiction` and the engine saw the default of null. The
driver now rejects any input that resolves to no engine column
(`drivers.reject_unknown_columns`), and these oracles keep the real behaviour
pinned.

## ORC-130 — SA third-country PSE, equivalence determined (CRR)

**Inputs:** EAD £1,000,000; class `pse`; entity type `pse_sovereign`; unrated;
central government CQS 1; US/USD; equivalence determination **made**.
**Regulation:** Art. 116(5) first limb with Art. 116(1) Table 2, CQS 1 → 20%.
**Arithmetic:** `RW = 0.20`; `RWA = 200,000.00`.

## ORC-131 — SA third-country PSE, equivalence denied (CRR)

**Inputs:** as ORC-130, determination **denied**.
**Regulation:** Art. 116(5) second limb — "otherwise … 100 %".
**Arithmetic:** `RW = 1.00`; `RWA = 1,000,000.00`.

## ORC-132 — SA third-country PSE, equivalence not asserted (CRR)

**Inputs:** as ORC-130, determination **not asserted** (null).
**Regulation:** Art. 116(5) second limb. Absence of a determination is not a
determination, so the 100% fallback applies.
**Arithmetic:** `RW = 1.00`; `RWA = 1,000,000.00`.

## ORC-133 — SA third-country PSE, institution-typed, equivalence determined (CRR)

**Inputs:** as ORC-130 but entity type `pse_institution`.
**Regulation:** Art. 116(5) first limb with Art. 116(1) Table 2 → 20%. The
entity type does not change the Art. 116(5) test.
**Arithmetic:** `RW = 0.20`; `RWA = 200,000.00`.

## ORC-134 — SA third-country PSE, institution-typed, equivalence denied (CRR)

**Inputs:** as ORC-133, determination denied.
**Regulation:** Art. 116(5) second limb.
**Arithmetic:** `RW = 1.00`; `RWA = 1,000,000.00`.

## ORC-135 — SA third-country PSE, institution-typed, equivalence not asserted (CRR)

**Inputs:** as ORC-133, determination not asserted.
**Regulation:** Art. 116(5) second limb.
**Arithmetic:** `RW = 1.00`; `RWA = 1,000,000.00`.

## ORC-014 — SA multilateral development bank, named (CRR)

**Inputs:** EAD £1,000,000; class `mdb`; entity type `mdb_named`.
**Regulation:** Art. 117(2) — the sixteen named MDBs (IBRD, IFC, IADB, ADB,
AfDB, CEB, NIB, CDB, EBRD, EIB, EIF, MIGA, IFFIm, IsDB, IDA, AIIB) are assigned
0%.
**Arithmetic:** `RW = 0.00`; `RWA = 0.00`.

## ORC-015 — SA international organisation (CRR)

**Inputs:** EAD £1,000,000; class `international_organisation`.
**Regulation:** Art. 118 — the EU, IMF, BIS, EFSF and ESM are assigned 0%.
**Arithmetic:** `RW = 0.00`; `RWA = 0.00`.

### Institutions (Art. 120 and 121)

Art. 120(1) Table 3 (rated, residual maturity over three months):

| CQS | 1 | 2 | 3 | 4 | 5 | 6 |
|---|---|---|---|---|---|---|
| Risk weight | 20% | 50% | 50% | 100% | 100% | 150% |

Art. 121(1) Table 5 (unrated, keyed on the CQS of the central government of the
jurisdiction in which the institution is incorporated):

| CQS of the central government | 1 | 2 | 3 | 4 | 5 | 6 |
|---|---|---|---|---|---|---|
| Risk weight | 20% | 50% | 100% | 100% | 100% | 150% |

Art. 121(2) assigns 100% where that central government is itself unrated.

The CQS-2 cell of Table 3 is 50% under CRR and 30% under PS1/26 Art. 120(1)
Table 3. That single cell is the archetype of the defect class this suite
exists for: a conservation, bound or monotonicity property is satisfied by
either value.

**Table 5 is pinned across its whole domain** — ORC-105, ORC-020, ORC-106,
ORC-107, ORC-108, ORC-109 for CQS 1 to 6, plus ORC-021 for the Art. 121(2)
unrated-sovereign case. The engine agreed at every step from 2026-08-09
(P1.316); before that it returned a flat 100% throughout, which was
conservative at CQS 1 and 2, correct **by coincidence** at CQS 3, 4 and 5, and
anti-conservative at CQS 6. Sampling only the low steps produced exactly the
wrong severity reading — the whole family is enumerated here for that reason,
and enumerating it is what made the CQS-6 shortfall visible at all.

Now that the ladder is live, the whole family is the regression guard, and the
two halves guard different failures. A fix that mis-keys the table moves CQS
3/4/5 off 100%; a fix that makes the branch unconditional moves ORC-021 off
100%. Keep all seven.

## ORC-016 — SA rated institution, CQS 1 (CRR)

**Inputs:** EAD £1,000,000; class `institution`; CQS 1; residual maturity 5y.
**Regulation:** Art. 120(1) Table 3, CQS 1 → 20%.
**Arithmetic:** `RW = 0.20`; `RWA = 200,000.00`.

## ORC-017 — SA rated institution, CQS 2 (CRR)

**Inputs:** EAD £1,000,000; CQS 2; residual maturity 5y.
**Regulation:** Art. 120(1) Table 3, CQS 2 → **50%** (not the 30% of PS1/26).
**Arithmetic:** `RW = 0.50`; `RWA = 500,000.00`.

## ORC-018 — SA rated institution, CQS 3 (CRR)

**Inputs:** EAD £1,000,000; CQS 3; residual maturity 5y.
**Regulation:** Art. 120(1) Table 3, CQS 3 → 50%.
**Arithmetic:** `RW = 0.50`; `RWA = 500,000.00`.

## ORC-019 — SA rated institution, CQS 6 (CRR)

**Inputs:** EAD £1,000,000; CQS 6; residual maturity 5y.
**Regulation:** Art. 120(1) Table 3, CQS 6 → 150%.
**Arithmetic:** `RW = 1.50`; `RWA = 1,500,000.00`.

All six Table 5 oracles below share the same inputs bar the sovereign CQS: EAD
£1,000,000; class `institution`; no ECAI assessment for the institution itself;
residual and original maturity 5 years, so the Art. 121(3) three-month
preferential treatment does not apply.

## ORC-105 — SA unrated institution, central government CQS 1 (CRR)

**Regulation:** Art. 121(1) Table 5, CQS 1 → 20%.
**Arithmetic:** `RW = 0.20`; `RWA = 200,000.00`.

This is the largest relative movement in the family — 100% → 20%, and in the
**reducing** direction. It was a known disagreement (engine 100%, overstated)
until P1.316.

## ORC-020 — SA unrated institution, central government CQS 2 (CRR)

**Regulation:** Art. 121(1) Table 5, CQS 2 → 50%.
**Arithmetic:** `RW = 0.50`; `RWA = 500,000.00`.

Also RWA-reducing (100% → 50%), and a known disagreement until P1.316.

## ORC-106 — SA unrated institution, central government CQS 3 (CRR)

**Regulation:** Art. 121(1) Table 5, CQS 3 → 100%.
**Arithmetic:** `RW = 1.00`; `RWA = 1,000,000.00`.

The engine agreed here even before P1.316, because the flat 100% fallback
coincided with the Table 5 value at this step. Post-fix the value comes from
Table 5 itself. Keeping the oracle is what distinguishes a correctly-keyed
table from a mis-keyed one — a fix that read the wrong row would move this cell.

## ORC-107 — SA unrated institution, central government CQS 4 (CRR)

**Regulation:** Art. 121(1) Table 5, CQS 4 → 100%.
**Arithmetic:** `RW = 1.00`; `RWA = 1,000,000.00`.

## ORC-108 — SA unrated institution, central government CQS 5 (CRR)

**Regulation:** Art. 121(1) Table 5, CQS 5 → 100%.
**Arithmetic:** `RW = 1.00`; `RWA = 1,000,000.00`.

## ORC-109 — SA unrated institution, central government CQS 6 (CRR)

**Regulation:** Art. 121(1) Table 5, CQS 6 → 150%.
**Arithmetic:** `RW = 1.50`; `RWA = 1,500,000.00`.

The capital-shortfall limb. Until P1.316 the engine returned 100% against a
required 150%, understating the risk-weighted exposure amount by a third — the
same flat fallback that was merely over-cautious at CQS 1 and 2 under-weighted
here. It is the only step of the six that the fix moves **upward**.

## ORC-021 — SA unrated institution, unrated central government (CRR)

**Inputs:** EAD £1,000,000; class `institution`; no ECAI assessment; no
sovereign CQS; residual and original maturity 5y.
**Regulation:** Art. 121(2) — 100% for an unrated institution incorporated in a
country whose central government is unrated.
**Arithmetic:** `RW = 1.00`; `RWA = 1,000,000.00`.

This is the discriminator for the Table 5 ladder: it must stay at 100%. A fix
that made the sovereign-derived branch unconditional rather than falling back
to the Art. 121(2) residual would move this cell, and nothing else in the
family would notice.

### Corporates (Art. 122)

Art. 122(1) Table 6:

| CQS | 1 | 2 | 3 | 4 | 5 | 6 |
|---|---|---|---|---|---|---|
| Risk weight | 20% | 50% | 100% | 100% | 150% | 150% |

Art. 122(2): an unrated corporate takes the higher of 100% and the risk weight
of its jurisdiction's central government.

## ORC-022 — SA corporate, CQS 1 (CRR)

**Inputs:** EAD £1,000,000; CQS 1.
**Regulation:** Art. 122(1) Table 6, CQS 1 → 20%.
**Arithmetic:** `RW = 0.20`; `RWA = 200,000.00`.

## ORC-023 — SA corporate, CQS 2 (CRR)

**Inputs:** EAD £1,000,000; CQS 2.
**Regulation:** Art. 122(1) Table 6, CQS 2 → 50%.
**Arithmetic:** `RW = 0.50`; `RWA = 500,000.00`.

## ORC-024 — SA corporate, CQS 3 (CRR)

**Inputs:** EAD £1,000,000; CQS 3.
**Regulation:** Art. 122(1) Table 6, CQS 3 → **100%** (PS1/26 Table 6 says 75%).
**Arithmetic:** `RW = 1.00`; `RWA = 1,000,000.00`.

## ORC-025 — SA corporate, CQS 5 (CRR)

**Inputs:** EAD £1,000,000; CQS 5.
**Regulation:** Art. 122(1) Table 6, CQS 5 → 150%.
**Arithmetic:** `RW = 1.50`; `RWA = 1,500,000.00`.

## ORC-001 — SA corporate, unrated (CRR)

**Inputs:** EAD £1,000,000; no ECAI assessment.
**Regulation:** Art. 122(2) — 100%.
**Arithmetic:** `RW = 1.00`; `RWA = 1,000,000.00`.

### Retail (Art. 123)

## ORC-026 — SA retail (CRR)

**Inputs:** EAD £1,000,000; class `retail_other`; natural person; the Art. 123
criteria are met.
**Regulation:** Art. 123 first subparagraph — 75%.
**Arithmetic:** `RW = 0.75`; `RWA = 750,000.00`.

## ORC-027 — SA payroll / pension assignment loan (CRR)

**Inputs:** EAD £1,000,000; class `retail_other`; natural person; original
maturity 8 years (within the ten-year limit in point (d)).
**Regulation:** Art. 123 final subparagraph (inserted by Reg. (EU) 2019/876) —
loans to pensioners or permanently-employed borrowers against the unconditional
transfer of part of the pension or salary, meeting points (a) to (d), are
assigned 35%.
**Arithmetic:** `RW = 0.35`; `RWA = 350,000.00`.

### Immovable property (Art. 124–126)

Art. 125(1)(a) assigns 35% to exposures fully and completely secured by
mortgages on residential property occupied or let by the owner, but
Art. 125(2)(d) confines that weight to "the part of the loan … [that] does not
exceed 80% of the market value of the property". Art. 124(1) sends the part
above the mortgage value to "the risk weight applicable to the unsecured
exposures of the counterparty involved" — here a natural person meeting
Art. 123, so 75%.

Art. 126(1)(a) with 126(2)(d) assigns 50% to the part of a commercial mortgage
up to 50% of market value, subject to the Art. 126(2) conditions (in particular
(b): repayment must not materially depend on the property's cash-flows).
Otherwise Art. 124(1) assigns 100%.

## ORC-028 — SA residential mortgage, LTV 60% (CRR)

**Inputs:** EAD £1,000,000; class `retail_mortgage`; LTV 60%; natural person.
**Regulation:** Art. 125(1)(a) with 125(2)(d). With LTV 60% the property value
is `1,000,000 / 0.60 = 1,666,666.67`, and 80% of that is `1,333,333.33`, which
exceeds the whole loan. Nothing falls outside the preferential slice.
**Arithmetic:** `RW = 0.35`; `RWA = 350,000.00`.

## ORC-029 — SA residential mortgage, LTV 100% (CRR)

**Inputs:** EAD £1,000,000; class `retail_mortgage`; LTV 100%; natural person.
**Regulation:** Art. 125(2)(d) for the preferential slice, Art. 124(1) plus
Art. 123 for the remainder.
**Arithmetic:**

```
property value      = 1,000,000 / 1.00 = 1,000,000
preferential slice  = 80% × 1,000,000  =   800,000  at 35%
residual slice      = 1,000,000 - 800,000 = 200,000 at 75%

RW  = (800,000 × 0.35 + 200,000 × 0.75) / 1,000,000
    = (280,000 + 150,000) / 1,000,000
    = 0.43
RWA = 1,000,000 × 0.43 = 430,000.00
```

## ORC-030 — SA commercial mortgage meeting Art. 126(2), LTV 40% (CRR)

**Inputs:** EAD £1,000,000; class `commercial_mortgage`; LTV 40%; the Art. 126(2)
conditions are met (repayment does not materially depend on the property).
**Regulation:** Art. 126(1)(a) — 50%. The whole loan sits inside the
Art. 126(2)(d) 50%-of-value limit: value is `1,000,000 / 0.40 = 2,500,000` and
50% of that is `1,250,000`.
**Arithmetic:** `RW = 0.50`; `RWA = 500,000.00`.

## ORC-031 — SA commercial mortgage failing Art. 126(2) (CRR)

**Inputs:** EAD £1,000,000; class `commercial_mortgage`; LTV 70%; the
Art. 126(2)(b) condition is not met.
**Regulation:** Art. 124(1) — an exposure fully secured by mortgage on immovable
property where the Art. 126 conditions are not met is assigned 100%.
**Arithmetic:** `RW = 1.00`; `RWA = 1,000,000.00`.

### Default, covered bonds, equity and other items

Art. 127(1) assigns 150% where specific credit risk adjustments are less than
20%, and 100% where they are at least 20%, of "the unsecured part of the
exposure value **if those specific credit risk adjustments … were not
applied**" — that is, of `exposure value + adjustments`.

Art. 129(4) Table 6A (rated covered bonds):

| CQS | 1 | 2 | 3 | 4 | 5 | 6 |
|---|---|---|---|---|---|---|
| Risk weight | 10% | 20% | 20% | 50% | 50% | 100% |

Art. 128 ("items associated with particular high risk") was **omitted** from the
UK CRR with effect from 1 January 2022 by S.I. 2021/1078 reg. 6(3)(a), so no CRR
high-risk oracle exists. PS1/26 Art. 128(1) reinstates the 150% weight, which
ORC-076 covers.

## ORC-032 — SA defaulted exposure, thin provisions (CRR)

**Inputs:** EAD £1,000,000; specific credit risk adjustments £100,000.
**Regulation:** Art. 127(1)(a).
**Arithmetic:**

```
pre-adjustment unsecured value = 1,000,000 + 100,000 = 1,100,000
coverage                       = 100,000 / 1,100,000 = 0.090909…  < 20%
RW  = 1.50
RWA = 1,000,000 × 1.50 = 1,500,000.00
```

## ORC-033 — SA defaulted exposure, thick provisions (CRR)

**Inputs:** EAD £1,000,000; specific credit risk adjustments £300,000.
**Regulation:** Art. 127(1)(b).
**Arithmetic:**

```
pre-adjustment unsecured value = 1,000,000 + 300,000 = 1,300,000
coverage                       = 300,000 / 1,300,000 = 0.230769…  >= 20%
RW  = 1.00
RWA = 1,000,000 × 1.00 = 1,000,000.00
```

## ORC-034 — SA covered bond, CQS 1 (CRR)

**Inputs:** EAD £1,000,000; class `covered_bond`; CQS 1.
**Regulation:** Art. 129(4) Table 6A, CQS 1 → 10%.
**Arithmetic:** `RW = 0.10`; `RWA = 100,000.00`.

## ORC-035 — SA covered bond, CQS 4 (CRR)

**Inputs:** EAD £1,000,000; class `covered_bond`; CQS 4.
**Regulation:** Art. 129(4) Table 6A, CQS 4 → 50%.
**Arithmetic:** `RW = 0.50`; `RWA = 500,000.00`.

## ORC-036 — SA equity (CRR)

**Inputs:** EAD £1,000,000; exchange-traded equity; standardised permission.
**Regulation:** Art. 133(2) — equity exposures are assigned 100% unless deducted
or caught by Art. 48(4), Art. 89(3) or Art. 128.
**Arithmetic:** `RW = 1.00`; `RWA = 1,000,000.00`.

## ORC-037 — SA other items (CRR)

**Inputs:** EAD £1,000,000; class `other`; tangible assets.
**Regulation:** Art. 134(1) — tangible assets are assigned 100%.
**Arithmetic:** `RW = 1.00`; `RWA = 1,000,000.00`.

### Supporting factors (Art. 501, 501a)

Art. 501(1):

```
RWEA* = RWEA × [ min(E*, EUR 2,500,000) × 0.7619
                 + max(E* − EUR 2,500,000, 0) × 0.85 ] / E*
```

Art. 501a(1): own funds requirements for a qualifying infrastructure exposure in
the corporate or specialised lending class are multiplied by 0.75, which is the
same as multiplying the RWEA by 0.75.

## ORC-038 — SA unrated SME corporate with the Art. 501 factor (CRR)

**Inputs:** EAD £1,000,000; class `corporate_sme`; unrated; SME.
**Regulation:** Art. 122(2) sets the risk weight; Art. 501(1) scales the RWEA.
E\* is £1,000,000, which converts to at most about €1.3m at any plausible rate —
comfortably below the €2.5m threshold — so only the first branch of the formula
contributes and the factor is exactly 0.7619 regardless of the run's FX rate.
**Arithmetic:**

```
RW  = 1.00                                   (Art. 122(2))
SF  = (1,000,000 × 0.7619) / 1,000,000 = 0.7619
RWA = 1,000,000 × 1.00 × 0.7619 = 761,900.00
```

## ORC-039 — SA infrastructure corporate with the Art. 501a factor (CRR)

**Inputs:** EAD £1,000,000; class `corporate`; unrated; qualifying
infrastructure exposure.
**Regulation:** Art. 122(2) sets the risk weight; Art. 501a(1) multiplies the
own funds requirement by 0.75.
**Arithmetic:** `RW = 1.00`; `RWA = 1,000,000 × 1.00 × 0.75 = 750,000.00`.

---

## O1(b) — PRA PS1/26 (Basel 3.1)

### Sovereign, RGLA, PSE, MDB, international organisations

| Table | Article | 1 | 2 | 3 | 4 | 5 | 6 |
|---|---|---|---|---|---|---|---|
| 1 sovereign, rated | 114(2) | 0% | 20% | 50% | 100% | 100% | 150% |
| 1A RGLA, unrated | 115(1)(a)(i) | 20% | 50% | 100% | 100% | 100% | 150% |
| 1B RGLA, rated | 115(1)(b) | 20% | 50% | 50% | 100% | 100% | 150% |
| 2 PSE, unrated | 116(1) | 20% | 50% | 100% | 100% | 100% | 150% |
| 2A PSE, rated | 116(2) | 20% | 50% | 50% | 100% | 100% | 150% |
| 2B MDB, rated | 117(1)(a) | 20% | 30% | 50% | 100% | 100% | 150% |

Art. 117(1)(b) assigns 50% to an MDB with no ECAI assessment; Art. 117(2) keeps
the named MDBs at 0%; Art. 118(1) keeps the named international organisations at
0%; Art. 115(5) keeps UK RGLA in sterling at 20%.

## ORC-040 — SA sovereign, CQS 2 (PS1/26)

**Inputs:** EAD £1,000,000; CQS 2; US/USD.
**Regulation:** Art. 114(2) Table 1, CQS 2 → 20%, unchanged from CRR.
**Arithmetic:** `RW = 0.20`; `RWA = 200,000.00`.

## ORC-041 — SA UK sovereign, sterling (PS1/26)

**Inputs:** EAD £1,000,000; CQS 3; `GB`/`GBP`.
**Regulation:** Art. 114(4) — 0%.
**Arithmetic:** `RW = 0.00`; `RWA = 0.00`.

## ORC-042 — SA unrated regional government, sovereign CQS 2 (PS1/26)

**Inputs:** EAD £1,000,000; class `rgla`; unrated; sovereign CQS 2.
**Regulation:** Art. 115(1)(a)(i) Table 1A, CQS 2 → 50%.
**Arithmetic:** `RW = 0.50`; `RWA = 500,000.00`.

## ORC-043 — SA rated regional government, CQS 3 (PS1/26)

**Inputs:** EAD £1,000,000; class `rgla`; CQS 3.
**Regulation:** Art. 115(1)(b) Table 1B, CQS 3 → 50%. Note Table 1A gives 100%
at CQS 3, so the rated/unrated split is load-bearing.
**Arithmetic:** `RW = 0.50`; `RWA = 500,000.00`.

## ORC-044 — SA UK regional government, sterling (PS1/26)

**Inputs:** EAD £1,000,000; class `rgla`; `GB`/`GBP`.
**Regulation:** Art. 115(5) — 20%.
**Arithmetic:** `RW = 0.20`; `RWA = 200,000.00`.

## ORC-045 — SA UK public sector entity, central government CQS 1 (PS1/26)

**Inputs:** EAD £1,000,000; class `pse`; unrated; UK central government CQS 1.
**Regulation:** Art. 116(1) Table 2, CQS 1 → 20%.
**Arithmetic:** `RW = 0.20`; `RWA = 200,000.00`.

## ORC-046 — SA rated UK public sector entity, CQS 3 (PS1/26)

**Inputs:** EAD £1,000,000; class `pse`; CQS 3.
**Regulation:** Art. 116(2) Table 2A, CQS 3 → 50%.
**Arithmetic:** `RW = 0.50`; `RWA = 500,000.00`.

## ORC-047 — SA rated MDB, CQS 2 (PS1/26)

**Inputs:** EAD £1,000,000; class `mdb`; CQS 2.
**Regulation:** Art. 117(1)(a) Table 2B, CQS 2 → **30%**. There is no equivalent
CRR table: CRR Art. 117(1) sends a non-named MDB to the institution ladder,
where CQS 2 is 50%.
**Arithmetic:** `RW = 0.30`; `RWA = 300,000.00`.

## ORC-048 — SA unrated MDB (PS1/26)

**Inputs:** EAD £1,000,000; class `mdb`; no ECAI assessment.
**Regulation:** Art. 117(1)(b) — 50%.
**Arithmetic:** `RW = 0.50`; `RWA = 500,000.00`.

## ORC-049 — SA international organisation (PS1/26)

**Inputs:** EAD £1,000,000; class `international_organisation`.
**Regulation:** Art. 118(1) — 0%.
**Arithmetic:** `RW = 0.00`; `RWA = 0.00`.

### Institutions — ECRA (Art. 120) and SCRA (Art. 121)

Art. 120(1) Table 3 (rated, original maturity over three months):

| CQS | 1 | 2 | 3 | 4 | 5 | 6 |
|---|---|---|---|---|---|---|
| Risk weight | 20% | 30% | 50% | 100% | 100% | 150% |

Art. 121(2) Table 5 (unrated, standardised credit risk assessment):

| Grade | A | B | C |
|---|---|---|---|
| Risk weight | 40% | 75% | 150% |

Art. 121(5) allows 30% for a Grade A institution with a CET1 ratio of at least
14% and a leverage ratio of at least 5%.

## ORC-050 — SA rated institution, CQS 2 (PS1/26)

**Inputs:** EAD £1,000,000; class `institution`; CQS 2; original maturity 5y.
**Regulation:** Art. 120(1) Table 3, CQS 2 → **30%** (CRR Table 3 says 50%).
**Arithmetic:** `RW = 0.30`; `RWA = 300,000.00`.

## ORC-051 — SA rated institution, CQS 3 (PS1/26)

**Inputs:** EAD £1,000,000; CQS 3; original maturity 5y.
**Regulation:** Art. 120(1) Table 3, CQS 3 → 50%.
**Arithmetic:** `RW = 0.50`; `RWA = 500,000.00`.

## ORC-052 — SA unrated institution, SCRA Grade A (PS1/26)

**Inputs:** EAD £1,000,000; unrated; SCRA grade A; original maturity 5y.
**Regulation:** Art. 121(2) Table 5, Grade A → 40%.
**Arithmetic:** `RW = 0.40`; `RWA = 400,000.00`.

## ORC-053 — SA unrated institution, SCRA Grade B (PS1/26)

**Inputs:** EAD £1,000,000; unrated; SCRA grade B; original maturity 5y.
**Regulation:** Art. 121(2) Table 5, Grade B → 75%.
**Arithmetic:** `RW = 0.75`; `RWA = 750,000.00`.

## ORC-054 — SA unrated institution, SCRA Grade C (PS1/26)

**Inputs:** EAD £1,000,000; unrated; SCRA grade C; original maturity 5y.
**Regulation:** Art. 121(2) Table 5, Grade C → 150%.
**Arithmetic:** `RW = 1.50`; `RWA = 1,500,000.00`.

## ORC-055 — SA unrated institution, Grade A with strong ratios (PS1/26)

**Inputs:** EAD £1,000,000; unrated; SCRA grade A with CET1 ≥ 14% and leverage
ratio ≥ 5%; original maturity 5y.
**Regulation:** Art. 121(5) — 30%.
**Arithmetic:** `RW = 0.30`; `RWA = 300,000.00`.

### Corporates (Art. 122)

Art. 122(2) Table 6:

| CQS | 1 | 2 | 3 | 4 | 5 | 6 |
|---|---|---|---|---|---|---|
| Risk weight | 20% | 50% | 75% | 100% | 150% | 150% |

Art. 122(5) assigns 100% to an unrated corporate absent the Art. 122(6)
permission. With that permission, Art. 122(6)(a) assigns 65% to an exposure the
institution has assessed as investment grade and (b) 135% to one it has not.
Art. 122(11) assigns 85% to an unrated non-retail SME.

## ORC-056 — SA corporate, CQS 3 (PS1/26)

**Inputs:** EAD £1,000,000; CQS 3.
**Regulation:** Art. 122(2) Table 6, CQS 3 → **75%** (CRR Table 6 says 100%).
**Arithmetic:** `RW = 0.75`; `RWA = 750,000.00`.

## ORC-057 — SA corporate, CQS 5 (PS1/26)

**Inputs:** EAD £1,000,000; CQS 5.
**Regulation:** Art. 122(2) Table 6, CQS 5 → 150%.
**Arithmetic:** `RW = 1.50`; `RWA = 1,500,000.00`.

## ORC-058 — SA corporate, unrated, no Art. 122(6) permission (PS1/26)

**Inputs:** EAD £1,000,000; unrated; the investment-grade election is off.
**Regulation:** Art. 122(5) — 100%.
**Arithmetic:** `RW = 1.00`; `RWA = 1,000,000.00`.

## ORC-059 — SA corporate, unrated, assessed investment grade (PS1/26)

**Inputs:** EAD £1,000,000; unrated; the Art. 122(6) permission is held and the
exposure is assessed investment grade.
**Regulation:** Art. 122(6)(a) — 65%. The permission is an input, not an
assumption: without it Art. 122(5) would give 100%, which ORC-058 pins.
**Arithmetic:** `RW = 0.65`; `RWA = 650,000.00`.

## ORC-060 — SA unrated non-retail SME (PS1/26)

**Inputs:** EAD £1,000,000; class `corporate_sme`; unrated; does not qualify as
a retail exposure.
**Regulation:** Art. 122(11) — 85%.
**Arithmetic:** `RW = 0.85`.

> **Not asserted:** the RWEA. It would also depend on whether the CRR Art. 501
> SME supporting factor survives Basel 3.1. Art. 501 sits in Part Ten, which is
> in neither `ps126app1.pdf` nor the comparison document, so that could not be
> sourced. The published figure of £850,000 assumes no supporting factor.

### Retail (Art. 123)

Art. 123(3): 45% for a regulatory retail transactor exposure, 75% for a
regulatory retail exposure that is not a transactor exposure, 100% for retail
that does not qualify as regulatory retail. Art. 123(4) keeps the 35% payroll /
pension assignment weight.

## ORC-061 — SA regulatory retail, non-transactor (PS1/26)

**Inputs:** EAD £1,000,000; natural person; regulatory retail; not a transactor.
**Regulation:** Art. 123(3)(b) — 75%.
**Arithmetic:** `RW = 0.75`; `RWA = 750,000.00`.

## ORC-062 — SA regulatory retail, transactor (PS1/26)

**Inputs:** EAD £1,000,000; natural person; regulatory retail; transactor.
**Regulation:** Art. 123(3)(a) — 45%.
**Arithmetic:** `RW = 0.45`; `RWA = 450,000.00`.

## ORC-063 — SA retail that is not regulatory retail (PS1/26)

**Inputs:** EAD £1,000,000; natural person; the Art. 123A conditions are not met.
**Regulation:** Art. 123(3)(c) — 100%.
**Arithmetic:** `RW = 1.00`; `RWA = 1,000,000.00`.

## ORC-064 — SA payroll / pension assignment loan (PS1/26)

**Inputs:** EAD £1,000,000; natural person; original maturity 8 years.
**Regulation:** Art. 123(4) — 35%.
**Arithmetic:** `RW = 0.35`; `RWA = 350,000.00`.

## ORC-283 — SA transactor that is NOT regulatory retail (PS1/26)

**Inputs:** EAD £1,000,000; natural person; `is_qrre_transactor = True`; the
Art. 123A conditions are **not** met.
**Regulation:** Art. 123(3)(c) — 100%.

Art. 123(3)(a) assigns 45% to "**regulatory retail exposures that are**
transactor exposures". Qualification under Art. 123A and the transactor
property are **both** required; the transactor property alone does not earn the
rate. Art. 123(3)(c) then sweeps up "all other retail exposures that do not
qualify as regulatory retail exposures" at 100%.

This is the fourth corner of the (`qualifies_as_retail` × `is_qrre_transactor`)
square. ORC-061 covers (True, False) → 75%, ORC-062 (True, True) → 45%, ORC-063
(False, False) → 100%; **(False, True) was the only combination the estate did
not carry**, on either side of the engine. The engine returned 45% here — a
55pp understatement — because its transactor branch was ordered ahead of the
non-regulatory-retail branch, making the 100% limb unreachable for any
transactor row (P1.293).

Note the rule keys on Art. 123A qualification, **not** on the QRRE exposure
class: QRRE is an IRB construct (Art. 147(5A)) and Art. 123 does not mention
it, so this oracle is stated for a `retail_qrre` row deliberately — the same
answer is owed to `retail_other` and `retail_sme`.

**Arithmetic:** `RW = 1.00`; `RWA = 1,000,000.00`.

### Real estate (Art. 124F–124L)

Art. 124F(1): a regulatory residential real estate exposure **not** materially
dependent on the property's cash-flows takes 20% on the part up to 55% of the
value of the property, and the Art. 124L counterparty weight on the rest.
Art. 124H(1) does the same for regulatory commercial real estate to a natural
person or SME at 60%. Art. 124L(1)(a) sets the counterparty weight for a natural
person at 75%.

Art. 124G(1) Table 6B — regulatory residential real estate that **is** materially
dependent, weighted on the whole exposure:

| LTV | ≤50% | 50–60% | 60–70% | 70–80% | 80–90% | 90–100% | >100% |
|---|---|---|---|---|---|---|---|
| Risk weight | 30% | 35% | 40% | 50% | 60% | 75% | 105% |

Art. 124I(1)/(2) — regulatory commercial real estate that is materially
dependent: 100% where LTV ≤ 80%, 110% where LTV > 80%.

Art. 124K(1)/(2) — ADC exposures: 150%, or 100% for residential ADC with
substantial pre-sale contracts or borrower equity.

## ORC-065 — SA regulatory RRE, not materially dependent, LTV 50% (PS1/26)

**Inputs:** EAD £1,000,000; class `retail_mortgage`; natural person; LTV 50%;
not materially dependent on the property's cash-flows.
**Regulation:** Art. 124F(1)(a).
**Arithmetic:**

```
property value     = 1,000,000 / 0.50 = 2,000,000
55% of value       = 1,100,000  > the whole exposure
RW  = 0.20
RWA = 1,000,000 × 0.20 = 200,000.00
```

## ORC-066 — SA regulatory RRE, not materially dependent, LTV 100% (PS1/26)

**Inputs:** EAD £1,000,000; class `retail_mortgage`; natural person; LTV 100%;
not materially dependent.
**Regulation:** Art. 124F(1)(a) for the preferential slice, Art. 124F(1)(b) with
Art. 124L(1)(a) for the residual.
**Arithmetic:**

```
property value      = 1,000,000 / 1.00 = 1,000,000
preferential slice  = 55% × 1,000,000  =   550,000  at 20%
residual slice      = 1,000,000 - 550,000 = 450,000 at 75%

RW  = (550,000 × 0.20 + 450,000 × 0.75) / 1,000,000
    = (110,000 + 337,500) / 1,000,000
    = 0.4475
RWA = 1,000,000 × 0.4475 = 447,500.00
```

## ORC-067 — SA regulatory RRE, materially dependent, LTV 65% (PS1/26)

**Inputs:** EAD £1,000,000; class `retail_mortgage`; LTV 65%; materially
dependent on the property's cash-flows.
**Regulation:** Art. 124G(1) Table 6B, band 60% < LTV ≤ 70% → 40%. Applies to
the entirety of the exposure, not to a slice.
**Arithmetic:** `RW = 0.40`; `RWA = 400,000.00`.

## ORC-068 — SA regulatory RRE, materially dependent, LTV 105% (PS1/26)

**Inputs:** EAD £1,000,000; class `retail_mortgage`; LTV 105%; materially
dependent.
**Regulation:** Art. 124G(1) Table 6B, band LTV > 100% → 105%.
**Arithmetic:** `RW = 1.05`; `RWA = 1,050,000.00`.

## ORC-069 — SA regulatory CRE, not materially dependent, LTV 50% (PS1/26)

**Inputs:** EAD £1,000,000; class `commercial_mortgage`; natural person; LTV
50%; not materially dependent.
**Regulation:** Art. 124H(1)(a). As in ORC-065 the whole exposure sits inside
55% of the property value (£1,100,000), so no residual slice arises.
**Arithmetic:** `RW = 0.60`; `RWA = 600,000.00`.

## ORC-070 — SA regulatory CRE, materially dependent, LTV 70% (PS1/26)

**Inputs:** EAD £1,000,000; class `commercial_mortgage`; LTV 70%; materially
dependent.
**Regulation:** Art. 124I(1) — 100% where LTV ≤ 80%.
**Arithmetic:** `RW = 1.00`; `RWA = 1,000,000.00`.

## ORC-071 — SA regulatory CRE, materially dependent, LTV 90% (PS1/26)

**Inputs:** EAD £1,000,000; class `commercial_mortgage`; LTV 90%; materially
dependent.
**Regulation:** Art. 124I(2) — 110% where LTV > 80%.
**Arithmetic:** `RW = 1.10`; `RWA = 1,100,000.00`.

## ORC-072 — SA ADC exposure (PS1/26)

**Inputs:** EAD £1,000,000; commercial ADC exposure; no pre-sale contracts.
**Regulation:** Art. 124K(1) — 150%.
**Arithmetic:** `RW = 1.50`; `RWA = 1,500,000.00`.

## ORC-073 — SA residential ADC exposure with pre-sales (PS1/26)

**Inputs:** EAD £1,000,000; residential ADC exposure with substantial pre-sale
contracts.
**Regulation:** Art. 124K(2) — 100%.
**Arithmetic:** `RW = 1.00`; `RWA = 1,000,000.00`.

### Default, high risk, covered bonds, equity and other items

Art. 129(4) Table 7 (eligible covered bonds):

| CQS | 1 | 2 | 3 | 4 | 5 | 6 |
|---|---|---|---|---|---|---|
| Risk weight | 10% | 20% | 20% | 50% | 50% | 100% |

## ORC-074 — SA defaulted exposure, thin provisions (PS1/26)

**Inputs:** EAD £1,000,000; specific credit risk adjustments £100,000.
**Regulation:** Art. 127(1)(a) — 150% where the adjustments are below 20% of the
outstanding amount.
**Arithmetic:** `RW = 1.50`; `RWA = 1,500,000.00`.

## ORC-075 — SA defaulted exposure, thick provisions (PS1/26)

**Inputs:** EAD £1,000,000; specific credit risk adjustments £300,000.
**Regulation:** Art. 127(1)(b) — 100% at or above 20%.
**Arithmetic:** `RW = 1.00`; `RWA = 1,000,000.00`.

## ORC-076 — SA exposure associated with particularly high risk (PS1/26)

**Inputs:** EAD £1,000,000; class `high_risk`.
**Regulation:** Art. 128(1) — 150%. UK CRR omitted Art. 128 from 1 January 2022;
PS1/26 reinstates it.
**Arithmetic:** `RW = 1.50`; `RWA = 1,500,000.00`.

## ORC-077 — SA eligible covered bond, CQS 1 (PS1/26)

**Inputs:** EAD £1,000,000; CQS 1.
**Regulation:** Art. 129(4) Table 7, CQS 1 → 10%.
**Arithmetic:** `RW = 0.10`; `RWA = 100,000.00`.

## ORC-078 — SA eligible covered bond, CQS 3 (PS1/26)

**Inputs:** EAD £1,000,000; CQS 3.
**Regulation:** Art. 129(4) Table 7, CQS 3 → 20%.
**Arithmetic:** `RW = 0.20`; `RWA = 200,000.00`.

## ORC-079 — SA other items (PS1/26)

**Inputs:** EAD £1,000,000; class `other`; tangible assets.
**Regulation:** Art. 134(1) — 100%.
**Arithmetic:** `RW = 1.00`; `RWA = 1,000,000.00`.

## ORC-080 — SA equity (PS1/26)

**Inputs:** EAD £1,000,000; exchange-traded equity.
**Regulation:** Art. 133(3) — an equity exposure is assigned **250%** unless it
is a higher risk equity exposure (400% under Art. 133(4)) or falls in
Art. 133(6). CRR Art. 133(2) assigned 100%, so this is a 2.5× regime change on
the same instrument.
**Arithmetic:** `RW = 2.50`; `RWA = 2,500,000.00`.

---

# Phase O2 — Foundation and Advanced IRB

## The formulae

CRR Art. 153(1)(iii), for a corporate or institution exposure with `0 < PD < 1`:

```
RW = ( LGD · N( (G(PD) + √R · G(0.999)) / √(1−R) ) − LGD · PD )
     · (1 + (M − 2.5)·b) / (1 − 1.5·b)
     · 12.5 · 1.06

R  = 0.12 · A + 0.24 · (1 − A),   A = (1 − e^(−50·PD)) / (1 − e^(−50))
b  = (0.11852 − 0.05478 · ln(PD))²
```

PS1/26 Art. 153(1)(c) restates the same formula **without the 1.06 factor**.

CRR Art. 154(1)(ii) and PS1/26 Art. 154(1)(b), for retail — the same shape with
**no maturity adjustment**, and a different correlation:

```
RW = ( LGD · N( (G(PD) + √R · G(0.999)) / √(1−R) ) − LGD · PD ) · 12.5 [· 1.06]

R  = 0.03 · A + 0.16 · (1 − A),   A = (1 − e^(−35·PD)) / (1 − e^(−35))
```

with `R = 0.15` for retail secured by immovable property (Art. 154(3)) and
`R = 0.04` for qualifying revolving retail (Art. 154(4)).

Art. 153(2) multiplies the correlation by 1.25 for large or unregulated
financial sector entities. Art. 153(4) reduces it for SME corporates by
`0.04 · (1 − (min(max(floor, S), cap) − floor) / (cap − floor))`, with
`floor/cap` of EUR 5m/50m under CRR and GBP 4.4m/44m under PS1/26.

`N(·)` is the standard normal CDF and `G(·)` its inverse, evaluated in the
derivation script with `statistics.NormalDist`. Every figure below is carried at
full IEEE-754 double precision; the printed values are rounded for reading.

## Parameter floors and supervisory values

| Parameter | CRR | PS1/26 |
|---|---|---|
| F-IRB LGD, senior unsecured corporate | 45% (Art. 161(1)(a)) | **40%** (Art. 161(1)(aa)) |
| F-IRB LGD, senior unsecured financial sector entity | 45% (Art. 161(1)(a)) | 45% (Art. 161(1)(a)) |
| F-IRB LGD, subordinated | 75% (Art. 161(1)(b)) | 75% (Art. 161(1)(b)) |
| PD floor, corporate / institution | 0.03% (Art. 160(1)) | **0.05%** (Art. 160(1)) |
| PD floor, other retail | 0.03% (Art. 163(1)) | **0.05%** (Art. 163(1)(c)) |
| PD floor, non-transactor QRRE | 0.03% | **0.1%** (Art. 163(1)(a)) |
| PD floor, UK residential retail | 0.03% | **0.1%** (Art. 163(1)(b)) |
| A-IRB LGD floor, unsecured corporate | none | **25%** (Art. 161(5)(a)) |
| A-IRB LGD floor, retail secured by RRE | none | **5%** (Art. 164(4)(a)) |
| A-IRB LGD floor, QRRE | none | **50%** (Art. 164(4)(b)(i)) |
| A-IRB LGD floor, other unsecured retail | none | **30%** (Art. 164(4)(b)(ii)) |
| RWEA floor, UK residential retail | none | **10% of EAD** (Art. 154(4A)(b)) |
| F-IRB maturity | 2.5y (Art. 162(1)) | per Art. 162(2A) |

On every F-IRB oracle the bank supplies **no** own LGD estimate. The engine must
therefore derive the supervisory value from Art. 161 itself, and the derived
figure is compared separately as `firb_supervisory_lgd` before the risk weight
is compared. That makes these oracles a test of the Art. 161 table and not only
of the formula.

## ORC-003 — F-IRB corporate, senior unsecured, M = 2.5 (CRR)

**Inputs:** EAD £10,000,000; PD 1%; no own LGD; M = 2.5.
**Regulation:** Art. 153(1) with Art. 161(1)(a) and Art. 162(1).

```
A       = (1 − e^(−0.5)) / (1 − e^(−50))      = 0.3934693402873666
R       = 0.12·A + 0.24·(1−A)                 = 0.192783679165516
b       = (0.11852 − 0.05478·ln(0.01))²       = 0.13748613089693737
MA      = 1 / (1 − 1.5·b)                     = 1.2598095009238282
G(PD)   = G(0.01)                             = −2.3263478740408408
G(0.999)                                      =  3.090232306167813
N(inner)                                      =  0.14027267845651598

RW  = 0.45 × (0.14027267845651598 − 0.01) × 1.2598095009238282 × 12.5 × 1.06
    = 0.9785580947557455
RWA = 10,000,000 × 0.9785580947557455 = 9,785,580.95
```

## ORC-081 — F-IRB corporate, subordinated (CRR)

**Inputs:** EAD £10,000,000; PD 1%; seniority `subordinated`; M = 2.5.
**Regulation:** Art. 161(1)(b) sets LGD to 75%; the rest is ORC-003.
**Arithmetic:** `RW = 1.630930158`; `RWA = 16,309,301.58`. The ratio to ORC-003
is exactly `0.75 / 0.45`, because LGD enters the formula linearly.

## ORC-082 — A-IRB corporate, M = 5 (CRR)

**Inputs:** EAD £10,000,000; PD 1%; own LGD 30%; M = 5.
**Regulation:** Art. 153(1); Art. 162(2) caps M at five years.
**Arithmetic:** `MA = (1 + 2.5·b) / (1 − 1.5·b) = 1.692825336`;
`RW = 0.8766023403`; `RWA = 8,766,023.40`.

## ORC-083 — A-IRB corporate, M = 1 (CRR)

**Inputs:** EAD £10,000,000; PD 1%; own LGD 30%; M = 1.
**Regulation:** Art. 153(1).
**Arithmetic:** `MA = (1 − 1.5·b) / (1 − 1.5·b) = 1.0` exactly — at M = 1 the
numerator and denominator coincide, which is a useful degenerate case because a
sign error in the maturity adjustment cannot hide there.
`RW = 0.5178338969`; `RWA = 5,178,338.97`.

## ORC-084 — F-IRB corporate at the PD floor (CRR)

**Inputs:** EAD £10,000,000; reported PD 0.01%; no own LGD; M = 2.5.
**Regulation:** Art. 160(1) — "the PD … shall be at least 0.03%". The formula is
evaluated at 0.0003, not at the reported 0.0001.
**Arithmetic:** `R = 0.2382134328`; `b = 0.3168344172`; `MA = 1.905675271`;
`RW = 0.1531018133`; `RWA = 1,531,018.13`.

## ORC-085 — F-IRB institution (CRR)

**Inputs:** EAD £10,000,000; class `institution`; PD 0.2%; no own LGD; M = 2.5.
**Regulation:** Art. 153(1) applies the same formula and Art. 161(1)(a) the same
45% supervisory LGD to institutions as to corporates.
**Arithmetic:** `R = 0.2285804902`; `MA = 1.46190545`; `RW = 0.4652815286`;
`RWA = 4,652,815.29`.

## ORC-086 — F-IRB exposure to a financial sector entity (CRR)

**Inputs:** EAD £10,000,000; PD 1%; no own LGD; M = 2.5; large financial sector
entity.
**Regulation:** Art. 153(2) multiplies the coefficient of correlation by 1.25.
**Arithmetic:**

```
R   = 0.192783679165516 × 1.25 = 0.240979598956895
RW  = 1.250263534
RWA = 12,502,635.34
```

The 1.25 lands on `R` only — `b` and `MA` are unchanged, which is why ORC-086
and ORC-003 share a maturity adjustment. A defect that applied 1.25 to the risk
weight instead would give 1.2232 rather than 1.2503.

## ORC-087 — F-IRB SME corporate with the Art. 501 factor (CRR)

**Inputs:** EAD £1,000,000; PD 1%; no own LGD; M = 2.5; SME with size metric
£3m.
**Regulation:** Art. 153(4) for the correlation, Art. 501(1) for the RWEA.

Art. 153(4) states its bounds in euro (EUR 5m ≤ S ≤ EUR 50m) while the size
metric is reported in sterling, so the exact correlation would otherwise depend
on an FX rate that no article supplies. Both the size metric and the exposure
are chosen to make the conversion irrelevant: £3m is below the €5m floor at any
plausible rate, so `S` clamps to the floor and the size adjustment takes its
maximum value of a flat 0.04; and E\* of £1m is below the €2.5m Art. 501(1)
threshold, so the supporting factor is exactly 0.7619.

```
R   = 0.192783679165516 − 0.04 = 0.152783679165516
RW  = 0.7673841097
SF  = 0.7619
RWA = 1,000,000 × 0.7673841097 × 0.7619 = 584,669.95
```

## ORC-088 — A-IRB other retail (CRR)

**Inputs:** EAD £10,000,000; class `retail_other`; PD 2%; own LGD 40%.
**Regulation:** Art. 154(1)(ii).
**Arithmetic:** `A = (1 − e^(−0.7)) / (1 − e^(−35))`;
`R = 0.03·A + 0.16·(1−A) = 0.09455608949`; `N(inner) = 0.1230870097`;
`RW = 0.5463611516`; `RWA = 5,463,611.52`. No maturity adjustment appears.

## ORC-089 — A-IRB retail secured by immovable property (CRR)

**Inputs:** EAD £10,000,000; class `retail_mortgage`; PD 1%; own LGD 20%.
**Regulation:** Art. 154(3) — a flat correlation of 0.15 replaces the formula.
**Arithmetic:** `R = 0.15`; `N(inner) = 0.1102647566`; `RW = 0.2657016049`;
`RWA = 2,657,016.05`.

## ORC-090 — A-IRB qualifying revolving retail (CRR)

**Inputs:** EAD £10,000,000; class `retail_qrre`; PD 3%; own LGD 60%.
**Regulation:** Art. 154(4) — a flat correlation of 0.04.
**Arithmetic:** `R = 0.04`; `N(inner) = 0.09873626288`; `RW = 0.5464532899`;
`RWA = 5,464,532.90`.

## ORC-091 — F-IRB corporate, senior unsecured (PS1/26)

**Inputs:** EAD £10,000,000; PD 1%; no own LGD; M = 2.5; not a financial sector
entity.
**Regulation:** Art. 153(1)(c) with Art. 161(1)(aa) — LGD 40% and no 1.06
scaling factor.
**Arithmetic:** `R`, `b` and `MA` are identical to ORC-003;
`RW = 0.8205937902`; `RWA = 8,205,937.90`.

Against ORC-003 this is a compound change: `0.9785580948 × (0.40/0.45) / 1.06 =
0.8205937902`. Either half alone would give a different answer, so the oracle
pins both.

## ORC-092 — F-IRB financial sector entity (PS1/26)

**Inputs:** EAD £10,000,000; PD 1%; no own LGD; M = 2.5; financial sector entity.
**Regulation:** Art. 161(1)(a) keeps LGD at 45% for a financial sector entity —
the Art. 161(1)(aa) reduction to 40% is expressly for corporates that are not
FSEs. Art. 153(2) multiplies the correlation by 1.25.
**Arithmetic:** `R = 0.240979598956895`; `RW = 1.1794939`; `RWA = 11,794,939.00`.

## ORC-093 — F-IRB corporate, subordinated (PS1/26)

**Inputs:** EAD £10,000,000; PD 1%; seniority `subordinated`; M = 2.5.
**Regulation:** Art. 161(1)(b) — 75%.
**Arithmetic:** `RW = 1.538613357`; `RWA = 15,386,133.57`.

## ORC-094 — F-IRB corporate at the PD floor (PS1/26)

**Inputs:** EAD £10,000,000; reported PD 0.01%; no own LGD; M = 2.5.
**Regulation:** Art. 160(1) — no PD below **0.05%** may be used as an input.
**Arithmetic:** `R = 0.2370371894`; `b = 0.2861152678`; `MA = 1.751843952`;
`RW = 0.1746770344`; `RWA = 1,746,770.34`.

Comparing with ORC-084 shows the floor move on its own: same reported PD, and
the answer differs because 0.0005 replaces 0.0003 (and 1.06 is gone).

## ORC-095 — A-IRB corporate at the LGD input floor (PS1/26)

**Inputs:** EAD £10,000,000; PD 1%; own LGD estimate **10%**; M = 2.5;
unsecured.
**Regulation:** Art. 161(5)(a) — a flat 25% LGD input floor for unsecured
corporate exposures. The formula is evaluated at 0.25, not at the bank's 0.10.
**Arithmetic:** `RW = 0.5128711188`; `RWA = 5,128,711.19`. Had the floor not
been applied the risk weight would be `0.5128711188 × 0.10/0.25 = 0.2051484475`,
a 2.5× understatement, so this oracle is a direct guard on an anti-conservative
failure.

## ORC-096 — A-IRB corporate, M = 5 (PS1/26)

**Inputs:** EAD £10,000,000; PD 1%; own LGD 30%; M = 5.
**Regulation:** Art. 153(1)(c).
**Arithmetic:** `MA = 1.692825336`; `RW = 0.8269833399`; `RWA = 8,269,833.40`.
Exactly `ORC-082 / 1.06`, isolating the scaling-factor removal.

## ORC-097 — F-IRB SME corporate (PS1/26)

**Inputs:** EAD £10,000,000; PD 1%; no own LGD; M = 2.5; SME size metric
£22,000,000.
**Regulation:** Art. 153(4). The PS1/26 bounds are in sterling, so no conversion
arises.

```
S clamped   = 22.0                       (GBP 4.4m <= S <= GBP 44m)
adjustment  = 0.04 × (1 − (22.0 − 4.4)/39.6)
            = 0.04 × (1 − 0.4444444…)
            = 0.0222222…
R           = 0.192783679165516 − 0.0222222… = 0.1705614569
RW          = 0.7209125549
```

> **Not asserted:** the RWEA. Whether the CRR Art. 501 SME supporting factor
> survives Basel 3.1 could not be sourced — Art. 501 sits in Part Ten, which is
> in neither `ps126app1.pdf` nor the comparison document. The published figure
> of £7,209,125.55 assumes no supporting factor.

## ORC-098 — A-IRB other retail (PS1/26)

**Inputs:** EAD £10,000,000; PD 2%; own LGD 40%.
**Regulation:** Art. 154(1)(b) — same correlation curve as CRR, no 1.06.
**Arithmetic:** `R = 0.09455608949`; `RW = 0.5154350487`; `RWA = 5,154,350.49`.
Exactly `ORC-088 / 1.06`.

## ORC-099 — A-IRB other retail at the LGD input floor (PS1/26)

**Inputs:** EAD £10,000,000; PD 2%; own LGD estimate **12%**; unsecured.
**Regulation:** Art. 164(4)(b)(ii) — a flat 30% LGD input floor for other
unsecured retail exposures.
**Arithmetic:** evaluated at LGD 0.30; `RW = 0.3865762865`;
`RWA = 3,865,762.87`.

## ORC-100 — A-IRB UK residential mortgage where the RWEA floor binds (PS1/26)

**Inputs:** EAD £10,000,000; class `retail_mortgage`; PD 1%; own LGD estimate
**2%**.
**Regulation:** Art. 154(3) for the correlation, Art. 164(4)(a) for the 5% LGD
input floor, and Art. 154(4A)(b) for the RWEA floor of 10% of exposure value for
non-defaulted retail exposures secured by UK residential immovable property.

```
LGD           = max(0.02, 0.05) = 0.05      (Art. 164(4)(a))
R             = 0.15                        (Art. 154(3))
RW            = 0.06266547285
modelled RWEA = 10,000,000 × 0.06266547285 =   626,654.73
RWEA floor    = 10% × 10,000,000           = 1,000,000.00   <- binds
RWA           = 1,000,000.00
```

Art. 154(4A)(b) is worded as an increase to the risk-weighted exposure amount,
not to the risk weight, so the risk weight itself stays at the modelled
0.06266547285 and only the RWEA moves. The increase itself —
`1,000,000.00 − 626,654.73 = 373,345.27` — is compared as
`mortgage_rwea_floor_adjustment`.

### The scope of the Art. 154(4A)(b) floor

Verbatim from `ps126app1.pdf` p104, Art. 154(4A):

> An institution shall increase the total risk-weighted exposure amounts
> calculated under paragraphs 1, 3 and 4 for retail exposures to reflect: …
> (b) any amount needed to ensure that risk-weighted exposure amounts for
> **non-defaulted** exposures which are **retail** exposures secured by **UK
> residential** immovable property are greater than or equal to 10% of the
> exposure value for such exposures …

Three cumulative conditions, so three ways to be out of scope. ORC-100 pins the
in-scope case; the three oracles below pin one out-of-scope limb each. Each
asserts `mortgage_rwea_floor_adjustment = 0.00`, which follows straight from the
article without having to settle what the risk weight should be.

## ORC-140 — Defaulted retail residential mortgage (PS1/26)

**Inputs:** EAD £10,000,000; class `retail_mortgage`; PD 100%; own LGD 5%;
EL_BE 5%; defaulted.
**Regulation:** Art. 154(1)(a) gives `RW = max(0, 12.5 · (LGD − EL_BE))`.
Art. 154(4A)(b) reaches only **non-defaulted** exposures, so it contributes
nothing.
**Arithmetic:**

```
RW                       = max(0, 12.5 × (0.05 − 0.05)) = 0.00
RWA                      = 10,000,000 × 0.00 = 0.00
floor adjustment (4A(b)) = 0.00   -- out of scope, exposure is defaulted
```

LGD is set equal to EL_BE deliberately: it drives the modelled RWEA to zero, so
whether the floor is applied is directly observable rather than masked by a
risk weight that already exceeds 10%.

> **Was a known disagreement; resolved by P1.319.** The engine used to add a
> floor adjustment of £1,000,000 here, because the gate matched `exposure_class`
> against the regex `MORTGAGE|RESIDENTIAL` and read no default flag at all. It
> now gates on `is_defaulted` and agrees at 0.00. Note that `is_defaulted` is the
> only correct carrier: `risk_weight` and `rwa` are not proxies for it, because
> an A-IRB defaulted mortgage with LGD > EL_BE has `K > 0` and hence `RW > 0`.

## ORC-141 — Commercial real estate exposure (PS1/26)

**Inputs:** EAD £10,000,000; class `commercial_mortgage`; PD 0.05%; own LGD 5%.
**Regulation:** Art. 154(4A)(b) reaches only exposures secured by **residential**
immovable property. A commercial real estate exposure is out of scope whatever
its risk weight.
**Arithmetic:** `floor adjustment = 0.00`.

> **Not asserted:** the risk weight and the RWEA. The correlation for a
> commercial-real-estate row reaching the IRB *retail* branch is a
> classification question Art. 154 does not settle — Art. 154(3) gives R = 0.15
> to "retail exposures secured by immovable property", and whether a commercial
> mortgage is a retail exposure at all turns on Art. 147(5), not on Art. 154.
> Only the floor-scope claim, which the article does settle, is compared.

> **Was a known disagreement; resolved by P1.319.** The engine used to add a
> floor adjustment of £56,745.41, because the class name matched its
> `MORTGAGE|RESIDENTIAL` regex through the substring "MORTGAGE". The gate now
> tests `exposure_class == retail_mortgage` exactly, so `commercial_mortgage` is
> out of scope and the engine agrees at 0.00.
>
> That equality is the engine's closest available PROXY for the Art. 147(5B)(d)(ii)
> subclass, not the subclass itself, and it is over-inclusive in one direction the
> oracles do not currently sample: a *retail* exposure secured only on *commercial*
> property is classified `retail_mortgage` upstream — `hierarchy/enrich.py`
> computes `property_collateral_value` over both property kinds by design — and
> still takes the floor. That residual is conservative (the floor can only raise
> RWEA) and is tracked as its own item.

## ORC-142 — Residential mortgage on non-UK property (PS1/26)

**Inputs:** identical to ORC-100 — EAD £10,000,000; class `retail_mortgage`;
PD 1%; own LGD 2% floored to 5% — but the property is outside the UK.
**Regulation:** Art. 154(3) for the correlation, Art. 164(4)(a) for the LGD
floor, and Art. 154(4A)(b) **not** applying, because the property is not UK
residential immovable property.
**Arithmetic:**

```
LGD                      = max(0.02, 0.05) = 0.05
R                        = 0.15
RW                       = 0.06266547285          (identical to ORC-100)
RWA                      = 10,000,000 × 0.06266547285 = 626,654.73
floor adjustment (4A(b)) = 0.00   -- out of scope, property is not in the UK
```

> **Known disagreement, and worse than a mis-gate.** The engine applies the
> floor regardless, giving £1,000,000. This limb is not merely un-implemented
> but **unrepresentable**: no module under `engine/irb/` reads any obligor or
> property country column at all — the only country carrier there is
> `guarantor_country_code`, for the guarantee substitution path — so no input
> could switch the floor off. The oracle supplies `cp_country_code = "US"`,
> which the IRB branch ignores. See `test_oracle.py::KNOWN_DISAGREEMENTS`.

## ORC-101 — A-IRB non-transactor QRRE at both floors (PS1/26)

**Inputs:** EAD £10,000,000; class `retail_qrre`; reported PD **0.02%**; own LGD
estimate **35%**; not a transactor.
**Regulation:** Art. 154(4) (correlation 0.04), Art. 163(1)(a) (PD floor 0.1%
for non-transactor QRRE) and Art. 164(4)(b)(i) (LGD floor 50% for QRRE).
**Arithmetic:** evaluated at PD 0.001 and LGD 0.50; `R = 0.04`;
`N(inner) = 0.005815205462`; `RW = 0.03009503414`; `RWA = 300,950.34`.

Both floors bind at once, which is the point: an implementation that applies one
and not the other lands on a visibly different number.

## ORC-102 — A-IRB other retail at the PD floor (PS1/26)

**Inputs:** EAD £10,000,000; class `retail_other`; reported PD **0.02%**; own
LGD 40%.
**Regulation:** Art. 163(1)(c) — 0.05% floor for all other retail exposures.
**Arithmetic:** evaluated at PD 0.0005; `R = 0.1577447906`;
`RW = 0.05892550456`; `RWA = 589,255.05`.

## ORC-103 — A-IRB defaulted retail exposure (CRR)

**Inputs:** EAD £10,000,000; PD 100%; own LGD 45%; EL_BE 30%.
**Regulation:** Art. 154(1)(i) — `RW = max(0, 12.5 · (LGD − EL_BE))`.
**Arithmetic:** `RW = 12.5 × (0.45 − 0.30) = 1.875`; `RWA = 18,750,000.00`.
No correlation, no maturity adjustment and no 1.06 appear in this branch.

## ORC-104 — F-IRB defaulted corporate exposure (PS1/26)

**Inputs:** EAD £10,000,000; PD 100%; no own LGD (F-IRB).
**Regulation:** Art. 153(1)(b) — where an institution uses the Foundation IRB
Approach, `RW = 0` for a defaulted exposure. The loss is carried by the expected
loss amount under Art. 158, not by the risk weight.
**Arithmetic:** `RW = 0.00`; `RWA = 0.00`.

---

# Phase O4 — Slotting and IRB equity

## Slotting

CRR Art. 153(5) Table 1:

| Remaining maturity | Category 1 | 2 | 3 | 4 | 5 |
|---|---|---|---|---|---|
| Less than 2.5 years | 50% | 70% | 115% | 250% | 0% |
| 2.5 years or more | 70% | 90% | 115% | 250% | 0% |

PS1/26 Art. 153(5) Table A re-cuts the same grades into seven columns:

| | Strong A | Strong B | Good C | Good D | Satisfactory | Weak | Default |
|---|---|---|---|---|---|---|---|
| Object / project / commodities / IPRE | 50% | 70% | 70% | 90% | 115% | 250% | 0% |
| HVCRE | 70% | 95% | 95% | 120% | 140% | 250% | 0% |

Art. 153(5)(c) directs column B for Strong and column D for Good; Art. 153(5)(d)
permits columns A and C respectively where less than 2.5 years remain. For the
non-HVCRE rows that reproduces the CRR table exactly; the HVCRE row has no CRR
equivalent.

## ORC-110 — Slotting, strong, ≥ 2.5 years (CRR)

**Inputs:** EAD £1,000,000; project finance; category `strong`; long-dated.
**Regulation:** Art. 153(5) Table 1, category 1, "equal or more than 2.5 years".
**Arithmetic:** `RW = 0.70`; `RWA = 700,000.00`.

## ORC-111 — Slotting, strong, < 2.5 years (CRR)

**Inputs:** EAD £1,000,000; project finance; category `strong`; short maturity.
**Regulation:** Art. 153(5) Table 1, category 1, "less than 2.5 years".
**Arithmetic:** `RW = 0.50`; `RWA = 500,000.00`.

## ORC-112 — Slotting, good, ≥ 2.5 years (CRR)

**Inputs:** EAD £1,000,000; project finance; category `good`; long-dated.
**Regulation:** Art. 153(5) Table 1, category 2 → 90%.
**Arithmetic:** `RW = 0.90`; `RWA = 900,000.00`.

## ORC-113 — Slotting, satisfactory (CRR)

**Inputs:** EAD £1,000,000; project finance; category `satisfactory`.
**Regulation:** Art. 153(5) Table 1, category 3 → 115%, the same on both
maturity rows.
**Arithmetic:** `RW = 1.15`; `RWA = 1,150,000.00`.

## ORC-114 — Slotting, weak (CRR)

**Inputs:** EAD £1,000,000; project finance; category `weak`.
**Regulation:** Art. 153(5) Table 1, category 4 → 250%.
**Arithmetic:** `RW = 2.50`; `RWA = 2,500,000.00`.

## ORC-115 — Slotting, default (CRR)

**Inputs:** EAD £1,000,000; project finance; category `default`.
**Regulation:** Art. 153(5) Table 1, category 5 → 0%.
**Arithmetic:** `RW = 0.00`; `RWA = 0.00`.

## ORC-116 — Slotting, strong project finance, ≥ 2.5 years (PS1/26)

**Inputs:** EAD £1,000,000; project finance; category `strong`; long-dated.
**Regulation:** Art. 153(5)(c)(i) with Table A column B → 70%.
**Arithmetic:** `RW = 0.70`; `RWA = 700,000.00`.

## ORC-117 — Slotting, strong project finance, < 2.5 years (PS1/26)

**Inputs:** EAD £1,000,000; project finance; category `strong`; short maturity.
**Regulation:** Art. 153(5)(d)(i) with Table A column A → 50%.
**Arithmetic:** `RW = 0.50`; `RWA = 500,000.00`.

## ORC-118 — Slotting, good project finance, ≥ 2.5 years (PS1/26)

**Inputs:** EAD £1,000,000; project finance; category `good`; long-dated.
**Regulation:** Art. 153(5)(c)(ii) with Table A column D → 90%.
**Arithmetic:** `RW = 0.90`; `RWA = 900,000.00`.

## ORC-119 — Slotting, strong HVCRE, ≥ 2.5 years (PS1/26)

**Inputs:** EAD £1,000,000; HVCRE; category `strong`; long-dated.
**Regulation:** Art. 153(5)(c)(i) with the Table A HVCRE row, column B → 95%.
**Arithmetic:** `RW = 0.95`; `RWA = 950,000.00`.

## ORC-120 — Slotting, satisfactory HVCRE (PS1/26)

**Inputs:** EAD £1,000,000; HVCRE; category `satisfactory`.
**Regulation:** Art. 153(5)(c)(iii) with the Table A HVCRE row → 140%.
**Arithmetic:** `RW = 1.40`; `RWA = 1,400,000.00`.

## IRB equity — CRR Art. 155(2)

The simple risk-weight approach assigns 190% to private equity in sufficiently
diversified portfolios, 290% to exchange-traded equity and 370% to all other
equity exposures. PS1/26 Art. 155 marks every paragraph "[Note: Provision left
blank]" — the IRB equity treatments are withdrawn and equity is weighted under
Art. 133 instead, which ORC-080 covers.

## ORC-121 — IRB equity, diversified private equity (CRR)

**Inputs:** EAD £1,000,000; private equity in a sufficiently diversified
portfolio; IRB permission.
**Regulation:** Art. 155(2) — 190%.
**Arithmetic:** `RW = 1.90`; `RWA = 1,900,000.00`.

## ORC-122 — IRB equity, exchange traded (CRR)

**Inputs:** EAD £1,000,000; exchange-traded equity; IRB permission.
**Regulation:** Art. 155(2) — 290%.
**Arithmetic:** `RW = 2.90`; `RWA = 2,900,000.00`.

## ORC-123 — IRB equity, all other (CRR)

**Inputs:** EAD £1,000,000; unlisted equity; IRB permission.
**Regulation:** Art. 155(2) — 370%.
**Arithmetic:** `RW = 3.70`; `RWA = 3,700,000.00`.

---

# Phase O3 — Credit risk mitigation, Standardised Approach side

Every oracle in this phase runs the **CRM stage** and then the SA branch
(`drivers.run_crm_sa`). It is the one place in this suite where the CRM stage is
not bypassed, and it has to be: Art. 222 writes columns only the SA risk-weight
substitution reads, Art. 223 rewrites the exposure value, and Art. 235 splits
the exposure into two legs.

## The shared fact pattern

Unless a section says otherwise:

- **Obligor.** A corporate rated CQS 5. Art. 122(1) Table 6 puts that at **150%**,
  which is deliberately far from the Art. 222(3) 20% floor and from every
  collateral and guarantor weight used below, so a blended weight can only come
  out right for the right reason. A 100%-weighted obligor would make several of
  these oracles pass on a coincidence.
- **Exposure.** `E = £1,000,000`, drawn, on balance sheet, sterling. Art. 223(3)
  gives `E_VA = E × (1 + H_E)` and `H_E = 0` throughout: Art. 223(3) applies the
  exposure-side adjustment to the exposure itself, which is non-zero only where
  the exposure *is* a security (an SFT lending a bond out). These are all cash
  loans, so `E_VA = E`.
- **Pledge.** `C = £300,000` market value, sterling, pledged directly against the
  exposure. 30% cover is chosen so both the covered and the uncovered portion are
  material — a defect in either leg moves the answer.
- **Exposure maturity 0.25 years.** This input is load-bearing and is not
  cosmetic. Art. 238(1) caps the effective maturity of the underlying at five
  years, and the engine assumes that cap when the exposure carries no maturity —
  which puts an Art. 237/238 maturity-mismatch factor of `(t − 0.25)/(T − 0.25)`
  on every pledge maturing inside five years. At `T = 0.25` (the Art. 238 lower
  bound) every pledge below has `t ≥ T`, the factor is exactly 1.0, and what is
  measured is the Art. 224 volatility adjustment alone. Remove this input and
  these become maturity-mismatch oracles by accident: the first draft of this
  section read a 42% "understatement" at CQS 1 that was Art. 238 working
  correctly.

Art. 228(1) makes `E*` the SA exposure value, so under the Comprehensive Method
`RWEA = E* × 150%` and **the risk weight is untouched** — asserting `risk_weight
= 1.50` on every one of those oracles is itself a check that the collateral
benefit is taken once, on the exposure value, and not a second time on the
weight.

## Art. 224(1) Table 1 — debt securities

Read verbatim from the PDF. Columns 4–6 are the adjustments for securities issued
by the entities described in **Art. 197(1)(b)** (central governments and central
banks, plus the Art. 197(2) assimilations); columns 7–9 those for
**Art. 197(1)(c) and (d)** (institutions, and other entities). The securitisation
columns are not used here — see the note at the end of this phase.

| CQS | Residual maturity | Art. 197(1)(b), 20d | 10d | 5d | Art. 197(1)(c)/(d), 20d | 10d | 5d |
|---|---|---|---|---|---|---|---|
| 1 | ≤ 1 year | 0,707 | 0,5 | 0,354 | 1,414 | 1 | 0,707 |
| 1 | > 1 ≤ 5 years | 2,828 | 2 | 1,414 | 5,657 | 4 | 2,828 |
| 1 | > 5 years | 5,657 | 4 | 2,828 | 11,314 | 8 | 5,657 |
| 2–3 | ≤ 1 year | 1,414 | 1 | 0,707 | 2,828 | 2 | 1,414 |
| 2–3 | > 1 ≤ 5 years | 4,243 | 3 | 2,121 | 8,485 | 6 | 4,243 |
| 2–3 | > 5 years | 8,485 | 6 | 4,243 | 16,971 | 12 | 8,485 |
| 4 | all bands | 21,213 | 15 | 10,607 | N/A | N/A | N/A |

## Art. 224(1) Table 3 — other collateral, and Table 4 — currency mismatch

| Item | 20d | 10d | 5d |
|---|---|---|---|
| Main index equities, main index convertible bonds | 21,213 | 15 | 10,607 |
| Other equities or convertible bonds listed on a recognised exchange | 35,355 | 25 | 17,678 |
| Cash | 0 | 0 | 0 |
| Gold | 21,213 | 15 | 10,607 |
| **Table 4** — currency mismatch | 11,314 | 8 | 5,657 |

## Which column applies, and the square-root-of-time relation

Art. 224(2) fixes the liquidation period by transaction type: **(a)** 20 business
days for secured lending, **(b)** 5 for repurchase and securities lending or
borrowing, **(c)** 10 for other capital-market-driven transactions.

The three columns are one number scaled by the square root of time, and the
printed figures are that number rounded to three decimal places of a percent:
2% at ten days is 2.828427…% at twenty, printed "2,828". The oracle is compared
at a relative tolerance of 1e-6 and the printed 3-dp figure is only good to about
1e-4, so `derivations/crm_sa.py::_scaled` returns the unrounded value — and
`_assert_printed_columns` checks it against **every** printed 20-day and 5-day
figure this phase uses, at import, so the relation is evidenced rather than
assumed. If a future reading of the table disagrees, `derive.py` fails there
rather than quietly publishing a figure no column of Table 1 contains.

## Art. 224(1) Table 1 at the 10-day column — ORC-200 to ORC-220

Twelve populated sovereign cells and nine non-sovereign cells: the **whole**
populated domain of Table 1 excluding securitisations. Every member is pinned,
including the ones that agree today. A defect measured at two cells of a table is
not a characterised defect — the Art. 121 Table 5 finding recorded in
`test_oracle.py` reads as purely conservative at the first two steps, coincides
at the middle three, and is anti-conservative at the last.

Shared inputs for all twenty-one: as "the shared fact pattern" above, with the
pledge given `liquidation_period_days = 10` (Art. 224(2)(c)). Shared arithmetic:
`C_VA = 300,000 × (1 − H_C)`, `E* = 1,000,000 − C_VA`, `RWA = E* × 1.50`.

## ORC-200 — FCCM, Art. 197(1)(b) security, CQS 1, ≤ 1 year (CRR)

**Regulation:** Art. 224(1) Table 1, 10-day column → `H_C = 0.5%`.
**Arithmetic:** `C_VA = 300,000 × 0.995 = 298,500.00`; `E* = 701,500.00`;
`RWA = 1,052,250.00`.

## ORC-201 — FCCM, Art. 197(1)(b) security, CQS 1, > 1 ≤ 5 years (CRR)

**Regulation:** Art. 224(1) Table 1, 10-day column → `H_C = 2%`.
**Arithmetic:** `C_VA = 300,000 × 0.98 = 294,000.00`; `E* = 706,000.00`;
`RWA = 1,059,000.00`.

## ORC-202 — FCCM, Art. 197(1)(b) security, CQS 1, > 5 years (CRR)

**Regulation:** Art. 224(1) Table 1, 10-day column → `H_C = 4%`.
**Arithmetic:** `C_VA = 300,000 × 0.96 = 288,000.00`; `E* = 712,000.00`;
`RWA = 1,068,000.00`.

## ORC-203 — FCCM, Art. 197(1)(b) security, CQS 2, ≤ 1 year (CRR)

**Regulation:** Art. 224(1) Table 1, 10-day column, CQS 2–3 row → `H_C = 1%`.
**Arithmetic:** `C_VA = 297,000.00`; `E* = 703,000.00`; `RWA = 1,054,500.00`.

## ORC-204 — FCCM, Art. 197(1)(b) security, CQS 2, > 1 ≤ 5 years (CRR)

**Regulation:** Art. 224(1) Table 1, 10-day column → `H_C = 3%`.
**Arithmetic:** `C_VA = 291,000.00`; `E* = 709,000.00`; `RWA = 1,063,500.00`.

## ORC-205 — FCCM, Art. 197(1)(b) security, CQS 2, > 5 years (CRR)

**Regulation:** Art. 224(1) Table 1, 10-day column → `H_C = 6%`.
**Arithmetic:** `C_VA = 282,000.00`; `E* = 718,000.00`; `RWA = 1,077,000.00`.

## ORC-206 — FCCM, Art. 197(1)(b) security, CQS 3, ≤ 1 year (CRR)

**Regulation:** Art. 224(1) Table 1 bands CQS 2 and 3 together → `H_C = 1%`.
The CQS 3 triple is pinned separately from CQS 2 precisely because the article
shares a row: a change that split them would otherwise move CQS 3 silently.
**Arithmetic:** `C_VA = 297,000.00`; `E* = 703,000.00`; `RWA = 1,054,500.00`.

## ORC-207 — FCCM, Art. 197(1)(b) security, CQS 3, > 1 ≤ 5 years (CRR)

**Regulation:** Art. 224(1) Table 1, 10-day column → `H_C = 3%`.
**Arithmetic:** `C_VA = 291,000.00`; `E* = 709,000.00`; `RWA = 1,063,500.00`.

## ORC-208 — FCCM, Art. 197(1)(b) security, CQS 3, > 5 years (CRR)

**Regulation:** Art. 224(1) Table 1, 10-day column → `H_C = 6%`.
**Arithmetic:** `C_VA = 282,000.00`; `E* = 718,000.00`; `RWA = 1,077,000.00`.

## ORC-209 — FCCM, Art. 197(1)(b) security, CQS 4, ≤ 1 year (CRR)

**Regulation:** Art. 224(1) Table 1, 10-day column → `H_C = 15%`. The CQS 4 row
is **band-invariant** — 15% in all three maturity bands — and all three are
pinned, because band-invariance is exactly the property a change can break
without moving the band that happened to be sampled.
**Arithmetic:** `C_VA = 255,000.00`; `E* = 745,000.00`; `RWA = 1,117,500.00`.

## ORC-210 — FCCM, Art. 197(1)(b) security, CQS 4, > 1 ≤ 5 years (CRR)

**Regulation:** Art. 224(1) Table 1, 10-day column → `H_C = 15%`.
**Arithmetic:** `C_VA = 255,000.00`; `E* = 745,000.00`; `RWA = 1,117,500.00`.

## ORC-211 — FCCM, Art. 197(1)(b) security, CQS 4, > 5 years (CRR)

**Regulation:** Art. 224(1) Table 1, 10-day column → `H_C = 15%`.
**Arithmetic:** `C_VA = 255,000.00`; `E* = 745,000.00`; `RWA = 1,117,500.00`.

## ORC-212 — FCCM, Art. 197(1)(c)/(d) security, CQS 1, ≤ 1 year (CRR)

**Regulation:** Art. 224(1) Table 1, 10-day column → `H_C = 1%`.
**Arithmetic:** `C_VA = 297,000.00`; `E* = 703,000.00`; `RWA = 1,054,500.00`.

## ORC-213 — FCCM, Art. 197(1)(c)/(d) security, CQS 1, > 1 ≤ 5 years (CRR)

**Regulation:** Art. 224(1) Table 1, 10-day column → `H_C = 4%`.
**Arithmetic:** `C_VA = 288,000.00`; `E* = 712,000.00`; `RWA = 1,068,000.00`.

## ORC-214 — FCCM, Art. 197(1)(c)/(d) security, CQS 1, > 5 years (CRR)

**Regulation:** Art. 224(1) Table 1, 10-day column → `H_C = 8%`.
**Arithmetic:** `C_VA = 276,000.00`; `E* = 724,000.00`; `RWA = 1,086,000.00`.

## ORC-215 — FCCM, Art. 197(1)(c)/(d) security, CQS 2, ≤ 1 year (CRR)

**Regulation:** Art. 224(1) Table 1, 10-day column → `H_C = 2%`.
**Arithmetic:** `C_VA = 294,000.00`; `E* = 706,000.00`; `RWA = 1,059,000.00`.

## ORC-216 — FCCM, Art. 197(1)(c)/(d) security, CQS 2, > 1 ≤ 5 years (CRR)

**Regulation:** Art. 224(1) Table 1, 10-day column → `H_C = 6%`.
**Arithmetic:** `C_VA = 282,000.00`; `E* = 718,000.00`; `RWA = 1,077,000.00`.

## ORC-217 — FCCM, Art. 197(1)(c)/(d) security, CQS 2, > 5 years (CRR)

**Regulation:** Art. 224(1) Table 1, 10-day column → `H_C = 12%`.
**Arithmetic:** `C_VA = 264,000.00`; `E* = 736,000.00`; `RWA = 1,104,000.00`.

## ORC-218 — FCCM, Art. 197(1)(c)/(d) security, CQS 3, ≤ 1 year (CRR)

**Regulation:** Art. 224(1) Table 1, 10-day column → `H_C = 2%`.
**Arithmetic:** `C_VA = 294,000.00`; `E* = 706,000.00`; `RWA = 1,059,000.00`.

## ORC-219 — FCCM, Art. 197(1)(c)/(d) security, CQS 3, > 1 ≤ 5 years (CRR)

**Regulation:** Art. 224(1) Table 1, 10-day column → `H_C = 6%`.
**Arithmetic:** `C_VA = 282,000.00`; `E* = 718,000.00`; `RWA = 1,077,000.00`.

## ORC-220 — FCCM, Art. 197(1)(c)/(d) security, CQS 3, > 5 years (CRR)

**Regulation:** Art. 224(1) Table 1, 10-day column → `H_C = 12%`.
**Arithmetic:** `C_VA = 264,000.00`; `E* = 736,000.00`; `RWA = 1,104,000.00`.

## Art. 224(1) Table 3 at the 10-day column — ORC-221 to ORC-224

Every row of Table 3. Shared inputs and arithmetic as for ORC-200 to ORC-220.

## ORC-221 — FCCM, cash collateral (CRR)

**Regulation:** Art. 224(1) Table 3, cash → `H_C = 0%` in every column.
**Arithmetic:** `C_VA = 300,000.00`; `E* = 700,000.00`; `RWA = 1,050,000.00`.

## ORC-222 — FCCM, gold (CRR)

**Regulation:** Art. 224(1) Table 3, gold, 10-day → `H_C = 15%`.
**Arithmetic:** `C_VA = 255,000.00`; `E* = 745,000.00`; `RWA = 1,117,500.00`.

## ORC-223 — FCCM, main-index equity (CRR)

**Inputs:** as shared, pledge is equity with `is_main_index = true`,
`is_listed = true`.
**Regulation:** Art. 224(1) Table 3, "Main Index Equities, Main Index Convertible
Bonds", 10-day → `H_C = 15%`. Eligible under Art. 197(1)(f).
**Arithmetic:** `C_VA = 255,000.00`; `E* = 745,000.00`; `RWA = 1,117,500.00`.

## ORC-224 — FCCM, other equity listed on a recognised exchange (CRR)

**Inputs:** as shared, pledge is equity with `is_main_index = false`,
`is_listed = true`.
**Regulation:** Art. 224(1) Table 3, "Other Equities or Convertible Bonds listed
on a recognised exchange", 10-day → `H_C = 25%`. Eligible under Art. 198(1)(a),
which is available because the firm is on the Comprehensive Method.
**Arithmetic:** `C_VA = 225,000.00`; `E* = 775,000.00`; `RWA = 1,162,500.00`.

## Art. 197 eligibility under the Comprehensive Method — ORC-225 to ORC-232, ORC-282

Art. 197(1)(b) admits a central-government security only where its ECAI
assessment is associated with "credit quality step **4 or above**";
Art. 197(1)(c) and (d) admit an institution's or another entity's only at "credit
quality step **3 or above**". A security outside those steps is not eligible
collateral. Neither is an **unrated** one: the limb is conditioned on *having* an
assessment, so absence fails it. (Art. 197(4) opens a narrow route for unrated
*institution* securities meeting five listed criteria; it does not reach an
unrated sovereign or corporate security, and no oracle here asserts it.)

Art. 197(1)(f) admits equity only where it is "included in a main index".
Art. 198(1)(a) extends that to non-main-index equity "traded on a recognised
exchange" — but expressly only "where an institution uses the Financial
Collateral Comprehensive Method set out in Article 223". So the ineligible equity
here is the pledge that fails **both** tests.

Art. 218 makes a credit linked note cash collateral only where it was "issued by
the lending institution"; a third-party note is an ordinary debt security of
another entity and needs Art. 197(1)(d)'s CQS 3 or above.

Ineligible collateral contributes nothing: `C_VA = 0`, `E* = E = 1,000,000.00`,
`RWA = 1,500,000.00`. Shared inputs as above with the pledge at residual maturity
3 years and a 10-day liquidation period.

## ORC-225 — FCCM, CQS 5 central-government security is ineligible (CRR)

**Regulation:** Art. 197(1)(b) — CQS 5 is below "credit quality step 4 or above".
**Arithmetic:** `C_VA = 0.00`; `E* = 1,000,000.00`; `RWA = 1,500,000.00`.

## ORC-226 — FCCM, CQS 6 central-government security is ineligible (CRR)

**Regulation:** Art. 197(1)(b).
**Arithmetic:** `C_VA = 0.00`; `E* = 1,000,000.00`; `RWA = 1,500,000.00`.

## ORC-227 — FCCM, unrated central-government security is ineligible (CRR)

**Regulation:** Art. 197(1)(b) — the limb requires an ECAI assessment.
**Arithmetic:** `C_VA = 0.00`; `E* = 1,000,000.00`; `RWA = 1,500,000.00`.

## ORC-228 — FCCM, CQS 4 other-entity security is ineligible (CRR)

**Regulation:** Art. 197(1)(d) — CQS 4 is below "credit quality step 3 or above".
**Arithmetic:** `C_VA = 0.00`; `E* = 1,000,000.00`; `RWA = 1,500,000.00`.

## ORC-229 — FCCM, CQS 5 other-entity security is ineligible (CRR)

**Regulation:** Art. 197(1)(d).
**Arithmetic:** `C_VA = 0.00`; `E* = 1,000,000.00`; `RWA = 1,500,000.00`.

## ORC-230 — FCCM, CQS 6 other-entity security is ineligible (CRR)

**Regulation:** Art. 197(1)(d).
**Arithmetic:** `C_VA = 0.00`; `E* = 1,000,000.00`; `RWA = 1,500,000.00`.

## ORC-231 — FCCM, unrated other-entity security is ineligible (CRR)

**Regulation:** Art. 197(1)(d) — the limb requires an ECAI assessment.
**Arithmetic:** `C_VA = 0.00`; `E* = 1,000,000.00`; `RWA = 1,500,000.00`.

## ORC-232 — FCCM, equity neither in a main index nor listed is ineligible (CRR)

**Inputs:** pledge is equity with `is_main_index = false`, `is_listed = false`.
**Regulation:** Art. 197(1)(f) fails on main-index membership and Art. 198(1)(a)
fails on listing.
**Arithmetic:** `C_VA = 0.00`; `E* = 1,000,000.00`; `RWA = 1,500,000.00`.

## ORC-282 — FCCM, unrated third-party credit linked note is ineligible (CRR)

**Inputs:** pledge is a credit linked note, `is_own_issued_cln = false`, unrated.
**Regulation:** Art. 218 (only a note issued by the lending institution is cash
collateral) with Art. 197(1)(d) (an unrated other-entity security is not
eligible).
**Arithmetic:** `C_VA = 0.00`; `E* = 1,000,000.00`; `RWA = 1,500,000.00`.

This oracle is the **control for ORC-281**, which is the same pledge under the
Simple Method. A pair whose Simple-Method half disagrees with the engine and
whose Comprehensive half agrees localises a defect to one method rather than to
the rule; without the control, "the Art. 218 gate is missing" cannot be told
apart from "the Art. 218 gate does not exist".

## Currency mismatch and the three liquidation periods — ORC-233 to ORC-240

Art. 223(1), second sub-paragraph: where the collateral is denominated in a
different currency from the exposure, institutions "shall add an adjustment
reflecting currency volatility to the volatility adjustment appropriate to the
collateral". Art. 223(2) then subtracts the sum:
`C_VA = C × (1 − H_C − H_fx)`.

## ORC-233 — FCCM, EUR cash against a GBP exposure, 10-day (CRR)

**Inputs:** pledge £300,000-equivalent cash denominated in EUR; 10-day period.
**Regulation:** Art. 224(1) Table 3 cash → `H_C = 0%`; Table 4, 10-day →
`H_fx = 8%`.
**Arithmetic:** `C_VA = 300,000 × (1 − 0 − 0.08) = 276,000.00`;
`E* = 724,000.00`; `RWA = 1,086,000.00`.

## ORC-234 — FCCM, the two adjustments compose additively (CRR)

**Inputs:** pledge EUR CQS 1 central-government security, residual maturity
3 years; 10-day period.
**Regulation:** Art. 223(1)/(2) with Table 1 (`H_C = 2%`) and Table 4
(`H_fx = 8%`).
**Arithmetic:** `C_VA = 300,000 × (1 − 0.02 − 0.08) = 270,000.00`;
`E* = 730,000.00`; `RWA = 1,095,000.00`.

## ORC-235 — FCCM, secured lending, cash (CRR)

**Inputs:** pledge £300,000 cash, GBP, **no** explicit liquidation period, so
Art. 224(2)(a)'s 20 business days applies.
**Regulation:** Art. 224(2)(a); Table 3 cash is 0% in every column.
**Arithmetic:** `C_VA = 300,000.00`; `E* = 700,000.00`; `RWA = 1,050,000.00`.
This is the case that shows the period change is not silently rescaling a zero:
it is the same answer as ORC-221 *because* cash carries no adjustment at any
period, and ORC-236 to ORC-238 on the same 20-day basis do move.

## ORC-236 — FCCM, secured lending, CQS 1 sovereign security, 3 years (CRR)

**Inputs:** as ORC-235 but the pledge is a CQS 1 central-government security,
residual maturity 3 years.
**Regulation:** Art. 224(1) Table 1, 20-day column → 2,828%, i.e.
`H_C = 0.02 × √2 = 0.0282842712…`.
**Arithmetic:** `C_VA = 300,000 × (1 − 0.0282842712) = 291,514.7186…`;
`E* = 708,485.2814…`; `RWA = 1,062,727.9221…`.

## ORC-237 — FCCM, secured lending, gold (CRR)

**Regulation:** Art. 224(1) Table 3, gold, 20-day column → 21,213%, i.e.
`H_C = 0.15 × √2 = 0.2121320344…`.
**Arithmetic:** `C_VA = 236,360.3897…`; `E* = 763,639.6103…`;
`RWA = 1,145,459.4155…`.

## ORC-238 — FCCM, secured lending, EUR cash (CRR)

**Regulation:** Art. 224(1) Table 4, 20-day column → 11,314%, i.e.
`H_fx = 0.08 × √2 = 0.1131370850…`.
**Arithmetic:** `C_VA = 300,000 × (1 − 0 − 0.1131370850) = 266,058.8745…`;
`E* = 733,941.1255…`; `RWA = 1,100,911.6882…`.

## ORC-239 — FCCM, repurchase transaction, CQS 1 sovereign security, 3 years (CRR)

**Inputs:** as ORC-236 but the exposure carries `is_sft = true`, which is how the
engine selects Art. 224(2)(b)'s 5 business days. This is a period selector, not a
full repo model — the row is still a drawn on-balance-sheet exposure.
**Regulation:** Art. 224(1) Table 1, 5-day column → 1,414%, i.e.
`H_C = 0.02 × √0.5 = 0.0141421356…`.
**Arithmetic:** `C_VA = 295,757.3593…`; `E* = 704,242.6407…`;
`RWA = 1,056,363.9610…`.

## ORC-240 — FCCM, repurchase transaction, EUR cash (CRR)

**Regulation:** Art. 224(1) Table 4, 5-day column → 5,657%, i.e.
`H_fx = 0.08 × √0.5 = 0.0565685425…`.
**Arithmetic:** `C_VA = 283,029.4373…`; `E* = 716,970.5627…`;
`RWA = 1,075,455.8441…`.

## The Art. 223(5) composition itself — ORC-241 to ORC-243

## ORC-241 — FCCM, over-collateralisation floors E* at zero (CRR)

**Inputs:** pledge £1,200,000 cash, GBP, 10-day period, against a £1,000,000
exposure.
**Regulation:** Art. 223(5), `E* = max(0, E_VA − C_VAM)`.
**Arithmetic:** `C_VA = 1,200,000.00`; `E* = max(0, 1,000,000 − 1,200,000) =
0.00`; `RWA = 0.00`. A negative exposure value is not produced.

## ORC-242 — FCCM, the composition is a difference, not a ratio (CRR)

**Inputs:** `E = £500,000`; pledge £300,000 cash, GBP, 10-day period.
**Regulation:** Art. 223(5).
**Arithmetic:** `C_VA = 300,000.00`; `E* = 200,000.00`; `RWA = 300,000.00`.
Not `500,000 × (1 − 0.3) = 350,000`, which is the answer a proportional
implementation would give and which this oracle exists to exclude.

## ORC-243 — FCCM, two collateral items each take their own adjustment (CRR)

**Inputs:** two pledges — £200,000 cash and £200,000 gold — both GBP, 10-day.
**Regulation:** Art. 223(7): where the collateral consists of a number of
eligible items each carries the adjustment applicable to it.
**Arithmetic:** `C_VA = 200,000 × 1.00 + 200,000 × 0.85 = 200,000 + 170,000 =
370,000.00`; `E* = 630,000.00`; `RWA = 945,000.00`.

## Art. 222 Financial Collateral Simple Method — ORC-244 to ORC-258, ORC-274 to ORC-281

Art. 222(2) assigns eligible financial collateral "a value equal to its market
value" — **no volatility adjustment at all**. Art. 222(3) then assigns "to those
portions of exposure values that are collateralised by the market value of
eligible collateral the risk weight that they would assign … where the lending
institution had a direct exposure to the collateral instrument", subject to a
floor: "The risk weight of the collateralised portion shall be at least 20%
except as specified in paragraphs 4 to 6", and "Institutions shall apply to the
remainder of the exposure value the risk weight that they would assign to an
unsecured exposure to the counterparty".

So the Simple Method **does not reduce the exposure value** — it is a
risk-weight substitution. Every oracle below therefore asserts
`ead = 1,000,000.00` as well as the blended weight, and that assertion is not a
formality: reducing EAD *and* substituting the weight would double-count the
collateral.

`RW_blended = (C_recognised / E) × RW_collateral + (1 − C_recognised / E) ×
150%`, with `C_recognised / E` capped at 1.

Art. 222(6) is the carve-out from the 20% floor, for a **non-SFT** exposure where
"the exposure and the collateral are denominated in the same currency" and either
"(a) the collateral is cash on deposit or a cash assimilated instrument" or
"(b) the collateral is in the form of debt securities issued by central
governments or central banks eligible for a 0% risk weight under Article 114, and
its market value has been discounted by 20%".

The weights a direct exposure to the collateral instrument would carry:
Art. 114(2) Table 1 for a central-government security (CQS 1 → 0%, 2 → 20%,
3 → 50%, 4 → 100%, 5 → 100%, 6 → 150%; Art. 114(1) → 100% unrated);
Art. 122(1) Table 6 for a corporate security (1 → 20%, 2 → 50%, 3 → 100%,
4 → 100%, 5 → 150%, 6 → 150%; 100% unrated); Art. 133(1) 100% for equity;
Art. 134 0% for cash and gold.

Shared inputs for all of these: the shared fact pattern, plus
`crm_method = "simple"` (the Art. 191A method election).

## ORC-244 — FCSM, same-currency cash takes 0% (CRR)

**Inputs:** pledge £300,000 cash, GBP.
**Regulation:** Art. 222(6)(a) — same currency, cash on deposit, non-SFT — so the
Art. 222(3) 20% floor does not apply.
**Arithmetic:** collateralised value 300,000.00 at 0%; `RW = 0.3 × 0.00 +
0.7 × 1.50 = 1.05`; `EAD = 1,000,000.00`; `RWA = 1,050,000.00`.

## ORC-245 — FCSM, EUR cash fails the same-currency condition (CRR)

**Inputs:** pledge £300,000-equivalent cash denominated in EUR.
**Regulation:** Art. 222(6) requires the exposure and the collateral to be in the
same currency, so the carve-out is unavailable and Art. 222(3) applies:
`max(0%, 20%) = 20%`.
**Arithmetic:** 300,000.00 at 20%; `RW = 0.3 × 0.20 + 0.7 × 1.50 = 1.11`;
`RWA = 1,110,000.00`. The 6 percentage points of difference from ORC-244 *is* the
floor, measured.

## ORC-246 — FCSM, Art. 222(6)(b) 0% after the 20% market-value discount (CRR)

**Inputs:** pledge £500,000 CQS 1 central-government security, GBP, residual
maturity 3 years.
**Regulation:** Art. 222(6)(b). Art. 114(2) Table 1 makes a CQS 1 sovereign 0%,
so the security qualifies — but only on a market value "discounted by 20%".
**Arithmetic:** recognised value `500,000 × 0.80 = 400,000.00` at 0%;
`RW = 0.4 × 0.00 + 0.6 × 1.50 = 0.90`; `RWA = 900,000.00`.

## ORC-247 — FCSM, EUR CQS 1 sovereign security: no carve-out, no discount (CRR)

**Inputs:** as ORC-246 but denominated in EUR.
**Regulation:** the Art. 222(6)(b) carve-out fails on currency, so neither the 0%
weight nor the 20% market-value discount that conditions it applies. The whole
£500,000 is recognised at the Art. 222(3) floor.
**Arithmetic:** 500,000.00 at 20%; `RW = 0.5 × 0.20 + 0.5 × 1.50 = 0.85`;
`RWA = 850,000.00`. Note this is *lower* than ORC-246's 0.90 — losing the
carve-out costs the 20% discount too, and on these numbers the discount matters
more than the floor. That is the article's arithmetic, not an anomaly, and it is
why both members are pinned.

## ORC-248 — FCSM, CQS 2 central-government security (CRR)

**Regulation:** Art. 222(3) with Art. 114(2) Table 1 → 20%, exactly the floor.
**Arithmetic:** 300,000.00 at 20%; `RW = 1.11`; `RWA = 1,110,000.00`.

## ORC-249 — FCSM, CQS 3 central-government security (CRR)

**Regulation:** Art. 222(3) with Art. 114(2) Table 1 → 50%, above the floor.
**Arithmetic:** 300,000.00 at 50%; `RW = 0.3 × 0.50 + 0.7 × 1.50 = 1.20`;
`RWA = 1,200,000.00`.

## ORC-250 — FCSM, CQS 4 central-government security (CRR)

**Regulation:** Art. 222(3) with Art. 114(2) Table 1 → 100%.
**Arithmetic:** `RW = 0.3 × 1.00 + 0.7 × 1.50 = 1.35`; `RWA = 1,350,000.00`.

## ORC-251 — FCSM, CQS 1 other-entity security (CRR)

**Regulation:** Art. 222(3) with Art. 122(1) Table 6 → 20%.
**Arithmetic:** `RW = 1.11`; `RWA = 1,110,000.00`.

## ORC-252 — FCSM, CQS 2 other-entity security (CRR)

**Regulation:** Art. 222(3) with Art. 122(1) Table 6 → 50%.
**Arithmetic:** `RW = 1.20`; `RWA = 1,200,000.00`.

## ORC-253 — FCSM, CQS 3 other-entity security (CRR)

**Regulation:** Art. 222(3) with Art. 122(1) Table 6 → 100%.
**Arithmetic:** `RW = 1.35`; `RWA = 1,350,000.00`.

## ORC-254 — FCSM, main-index equity (CRR)

**Regulation:** Art. 222(1)/(3) with Art. 133(1) → 100%. Note that the
instrument's *collateral* character governs: there is no Art. 222 carve-out for
equity and no route to a higher equity weight here.
**Arithmetic:** `RW = 1.35`; `RWA = 1,350,000.00`.

## ORC-255 — FCSM, gold takes the 20% floor (CRR)

**Regulation:** Art. 134(4) would weight gold at 0% as a direct exposure, but
gold is neither "cash on deposit or a cash assimilated instrument" nor a
central-government security, so no Art. 222(6) carve-out reaches it and
Art. 222(3)'s floor binds at 20%.
**Arithmetic:** 300,000.00 at 20%; `RW = 1.11`; `RWA = 1,110,000.00`.
Contrast ORC-244: same 0% underlying weight, same currency, different answer,
because the carve-out is written by instrument type.

## ORC-256 — FCSM, over-collateralisation leaves no remainder (CRR)

**Inputs:** pledge £1,200,000 cash, GBP.
**Regulation:** Art. 222(3) — the collateralised portion cannot exceed the
exposure value, so there is no "remainder of the exposure value" to weight.
**Arithmetic:** collateralised value capped at 1,000,000.00 at 0%; `RW = 0.00`;
`EAD = 1,000,000.00`; `RWA = 0.00`.

## Art. 197 eligibility under the Simple Method — ORC-257, ORC-258, ORC-274 to ORC-281

Art. 222(2) and (3) both speak of "**eligible** financial collateral" and "the
market value of **eligible** collateral". Art. 197 is what makes collateral
eligible, and it is not method-specific — it is headed "Eligibility of collateral
under all approaches and methods". So every ineligibility that applies under the
Comprehensive Method (ORC-225 to ORC-232, ORC-282) applies identically here, and
an ineligible pledge collateralises no portion of the exposure: the whole
£1,000,000 keeps the obligor's 150% and `RWA = 1,500,000.00`.

Only the members whose own weight is **below** the obligor's 150% can show a
missing gate at all. A CQS 6 security carries the same 150% the obligor does, so
recognising it changes nothing and the oracle agrees for the wrong reason. Those
members are pinned precisely because they agree: a future change to the
collateral weight would move them silently otherwise. This is the Art. 121 Table
5 shape recorded in `test_oracle.py` — sampling the interesting members
mis-characterises the family.

## ORC-257 — FCSM, CQS 5 central-government security is ineligible (CRR)

**Regulation:** Art. 197(1)(b) via Art. 222(2).
**Arithmetic:** collateralised value 0.00; `RW = 1.50`; `RWA = 1,500,000.00`.

## ORC-258 — FCSM, CQS 4 other-entity security is ineligible (CRR)

**Regulation:** Art. 197(1)(d) via Art. 222(2).
**Arithmetic:** collateralised value 0.00; `RW = 1.50`; `RWA = 1,500,000.00`.

## ORC-274 — FCSM, CQS 6 central-government security is ineligible (CRR)

**Regulation:** Art. 197(1)(b) via Art. 222(2). Art. 114(2) Table 1 would weight
this security at 150%, the obligor's own weight, so this member cannot
distinguish a working eligibility gate from a missing one — it is pinned to fix
the value, not to catch a defect.
**Arithmetic:** collateralised value 0.00; `RW = 1.50`; `RWA = 1,500,000.00`.

## ORC-275 — FCSM, unrated central-government security is ineligible (CRR)

**Regulation:** Art. 197(1)(b) via Art. 222(2) — the limb requires an ECAI
assessment.
**Arithmetic:** collateralised value 0.00; `RW = 1.50`; `RWA = 1,500,000.00`.

## ORC-276 — FCSM, CQS 5 other-entity security is ineligible (CRR)

**Regulation:** Art. 197(1)(d) via Art. 222(2). Art. 122(1) Table 6 weights it at
150% — coincident with the unsecured answer, as ORC-274.
**Arithmetic:** collateralised value 0.00; `RW = 1.50`; `RWA = 1,500,000.00`.

## ORC-277 — FCSM, CQS 6 other-entity security is ineligible (CRR)

**Regulation:** Art. 197(1)(d) via Art. 222(2). Also 150%, also coincident.
**Arithmetic:** collateralised value 0.00; `RW = 1.50`; `RWA = 1,500,000.00`.

## ORC-278 — FCSM, unrated other-entity security is ineligible (CRR)

**Regulation:** Art. 197(1)(d) via Art. 222(2).
**Arithmetic:** collateralised value 0.00; `RW = 1.50`; `RWA = 1,500,000.00`.

## ORC-279 — FCSM, non-main-index equity is ineligible even when listed (CRR)

**Inputs:** pledge is equity with `is_main_index = false`, `is_listed = true` —
i.e. the pledge ORC-224 recognises at a 25% haircut under the Comprehensive
Method.
**Regulation:** Art. 197(1)(f) via Art. 222(2). Art. 198(1)(a)'s extension to
non-main-index listed equity is expressly confined to a firm using the
Comprehensive Method, so listing does not rescue it here. This pair — ORC-224 and
ORC-279, the same instrument, eligible under one method and not the other — is
what makes Art. 198(1)(a)'s method-conditionality testable at all.
**Arithmetic:** collateralised value 0.00; `RW = 1.50`; `RWA = 1,500,000.00`.

## ORC-280 — FCSM, CQS 5 central-government security at full cover (CRR)

**Inputs:** pledge £1,000,000 CQS 5 central-government security, GBP, residual
maturity 3 years — full cover of the £1,000,000 exposure.
**Regulation:** Art. 197(1)(b) via Art. 222(2). This is the **magnitude** case: if
the eligibility gate is missing, the whole exposure moves from the obligor's 150%
to the security's own Art. 114(2) 100%, so the oracle and a gate-less
implementation differ by a third of RWEA rather than by a tenth.
**Arithmetic:** collateralised value 0.00; `RW = 1.50`; `RWA = 1,500,000.00`.

## ORC-281 — FCSM, unrated third-party credit linked note is ineligible (CRR)

**Inputs:** pledge £300,000 credit linked note, `is_own_issued_cln = false`,
unrated, GBP.
**Regulation:** Art. 218 with Art. 197(1)(d), via Art. 222(2). ORC-282 is the
Comprehensive-Method control for this oracle.
**Arithmetic:** collateralised value 0.00; `RW = 1.50`; `RWA = 1,500,000.00`.

## Art. 235 substitution and Art. 201 eligibility — ORC-259 to ORC-273

Art. 235(1): `RWEA = max(0, E − G_A) × r + G_A × g`, where `r` is the obligor's
risk weight, `g` the protection provider's, and `G_A` the protection value from
Art. 233(3) further adjusted for maturity mismatch (no mismatch here — these
oracles carry no maturity on either side). Art. 235(2) permits the formula only
where the protected and unprotected parts of the exposure rank equally, which
they do.

Art. 233(3): `G* = G × (1 − H_fx)` where the protection is denominated in a
different currency from the exposure. Art. 233(4) fixes that adjustment on a
**10-business-day** liquidation period — Art. 224(1) Table 4's middle column, 8%
— "assuming daily revaluation". That is a different basis from the collateral
side, which follows the transaction's own period under Art. 224(2), and the pair
ORC-259 / ORC-260 is what pins it: if the guarantee adjustment were scaled to the
20 days a secured lending transaction uses, `H_fx` would be 11.3137…% rather than
8%, `G*` would be 354,745.17 rather than 368,000.00, and RWEA would be
1,038,831.28 rather than 1,021,600.00 — a 1.7% difference the oracle would catch.

Art. 201(1) lists the eligible providers of unfunded credit protection
exhaustively: (a) central governments and central banks; (b) regional governments
or local authorities; (c) multilateral development banks; (d) 0%-weighted
international organisations; (e) public sector entities under Art. 116;
(f) institutions, and Art. 119(5) financial institutions; (g) other corporate
entities where either "(i) those other corporate entities have a credit
assessment by an ECAI" or "(ii) in the case of institutions calculating
risk-weighted exposure amounts … under the IRB Approach", an internal rating;
(h) qualifying central counterparties. **There is no retail or natural-person
limb**, and limb (g)(ii) is closed to a firm on the Standardised Approach.

Where the protection is not recognised the whole exposure keeps `r`:
`RWEA = 1,000,000 × 1.50 = 1,500,000.00`.

Shared inputs: the shared fact pattern, with a single guarantee of £400,000
covering part of the £1,000,000 exposure and no collateral.

## ORC-259 — Art. 235(1), CQS 1 institution guarantor, partial cover (CRR)

**Regulation:** Art. 201(1)(f) makes an institution eligible; Art. 120(1) Table 3
weights a CQS 1 institution at 20%.
**Arithmetic:** `G* = G_A = 400,000.00`; `RWEA = 600,000 × 1.50 +
400,000 × 0.20 = 900,000 + 80,000 = 980,000.00`; `RW = 0.98`.

## ORC-260 — Art. 233(3), the same guarantee in EUR (CRR)

**Inputs:** the guarantee is denominated in EUR; the exposure in GBP.
**Regulation:** Art. 233(3)/(4) with Art. 224(1) Table 4, 10-day → `H_fx = 8%`.
**Arithmetic:** `G* = 400,000 × 0.92 = 368,000.00`; `G_A = 368,000.00`;
`RWEA = 632,000 × 1.50 + 368,000 × 0.20 = 948,000 + 73,600 = 1,021,600.00`;
`RW = 1.0216`.

## ORC-261 — Art. 235(1), CQS 3 institution guarantor (CRR)

**Regulation:** Art. 120(1) Table 3, CQS 3 → 50%.
**Arithmetic:** `RWEA = 600,000 × 1.50 + 400,000 × 0.50 = 1,100,000.00`;
`RW = 1.10`.

## ORC-262 — Art. 235(1), CQS 1 central-government guarantor (CRR)

**Regulation:** Art. 201(1)(a) with Art. 114(2) Table 1, CQS 1 → 0%.
**Arithmetic:** `RWEA = 600,000 × 1.50 + 400,000 × 0.00 = 900,000.00`;
`RW = 0.90`.

## ORC-263 — Art. 235(1), CQS 3 central-government guarantor (CRR)

**Regulation:** Art. 114(2) Table 1, CQS 3 → 50%.
**Arithmetic:** `RWEA = 1,100,000.00`; `RW = 1.10`.

## ORC-264 — Art. 235(1), CQS 1 regional-government guarantor (CRR)

**Regulation:** Art. 201(1)(b) makes a regional government or local authority
eligible; Art. 115(1) weights it as an institution, so CQS 1 → 20%.
**Arithmetic:** `RWEA = 980,000.00`; `RW = 0.98`.

## ORC-265 — Art. 235(1), CQS 1 public-sector-entity guarantor (CRR)

**Regulation:** Art. 201(1)(e) makes a public sector entity treated under
Art. 116 eligible; Art. 116(2) weights it as an institution, so CQS 1 → 20%.
**Arithmetic:** `RWEA = 980,000.00`; `RW = 0.98`.

## ORC-266 — Art. 235(1), named multilateral development bank guarantor (CRR)

**Regulation:** Art. 201(1)(c) with Art. 117(2) — an MDB on the Art. 117(2) list
carries 0%.
**Arithmetic:** `RWEA = 900,000.00`; `RW = 0.90`.

## ORC-267 — Art. 235(1), unlisted unrated MDB guarantor (CRR)

**Regulation:** Art. 201(1)(c) still makes it eligible, but Art. 117(1) requires
an MDB not referred to in paragraph 2 to be "treated the same as exposures to
institutions", and Art. 121(2) weights an unrated institution at 100%. Same
eligibility limb as ORC-266, very different weight — which is why both are
pinned.
**Arithmetic:** `RWEA = 600,000 × 1.50 + 400,000 × 1.00 = 1,300,000.00`;
`RW = 1.30`.

## ORC-268 — Art. 201(1)(g)(i), rated corporate guarantor (CRR)

**Regulation:** a corporate *with* an ECAI credit assessment is eligible;
Art. 122(1) Table 6 weights CQS 2 at 50%.
**Arithmetic:** `RWEA = 1,100,000.00`; `RW = 1.10`.

## ORC-269 — Art. 201(1)(g), unrated corporate guarantor is ineligible (CRR)

**Regulation:** limb (g)(i) requires an ECAI assessment and limb (g)(ii) is open
only to a firm calculating under the IRB Approach. Neither is satisfied, so the
protection is not recognised.
**Arithmetic:** `G_A = 0.00`; `RWEA = 1,000,000 × 1.50 = 1,500,000.00`;
`RW = 1.50`.

## ORC-270 — Art. 201(1), individual guarantor is ineligible (CRR)

**Regulation:** the Art. 201(1) list is exhaustive and has no retail or
natural-person limb.
**Arithmetic:** `G_A = 0.00`; `RWEA = 1,500,000.00`; `RW = 1.50`.

## ORC-271 — Art. 193(1), a non-beneficial guarantee is not applied (CRR)

**Inputs:** guarantor is a CQS 6 corporate, which Art. 122(1) Table 6 weights at
150% — the obligor's own weight.
**Regulation:** the guarantor is eligible under Art. 201(1)(g)(i), but Art. 193(1)
forbids an exposure with credit protection producing a higher RWEA than the same
exposure unprotected, and Art. 235(1) carries no `min` of its own. At equal
weights the substitution can only fail to help, and the engine's recorded
election (see `engine/sa/rw_adjustments.py`) is to decline it.
**Arithmetic:** `RWEA = 1,000,000 × 1.50 = 1,500,000.00`; `RW = 1.50`. Note the
answer is the same whether the substitution is applied or declined — this oracle
pins the value, and the *decision* is documented rather than measured here.

## ORC-272 — Art. 235(1) at full cover (CRR)

**Inputs:** guarantee of £1,000,000 from a CQS 1 institution.
**Regulation:** Art. 235(1) — `max(0, E − G_A) = 0`, so `RWEA = E × g`.
**Arithmetic:** `RWEA = 0 × 1.50 + 1,000,000 × 0.20 = 200,000.00`; `RW = 0.20`.

## ORC-273 — Art. 235(1) with protection above the exposure value (CRR)

**Inputs:** guarantee of £1,400,000 over a £1,000,000 exposure.
**Regulation:** Art. 235(1) — `max(0, E − G_A)` floors at zero and the covered
amount cannot exceed E, so the excess £400,000 buys nothing.
**Arithmetic:** `RWEA = 200,000.00`; `RW = 0.20`. Identical to ORC-272, which is
the point: over-protection must not produce a negative uncovered leg.

## Note on the securitisation columns of Art. 224(1) Table 1

Columns 10–12 of Table 1 (securitisation positions meeting Art. 197(1)(h)) are
**not** pinned, and are excluded from `_assert_printed_columns`. Three of their
printed figures are not the 3-decimal-place rounding of the square-root-of-time
relation the rest of the table follows: CQS 1 ≤ 1 year reads 2,829 at 20 days
against a derived 2.828, CQS 2–3 > 5 years reads 33,942 against 33.941, and the
5-day CQS 1 > 5 years cell reads 11,313 against 11.314. Whether those are
typesetting artefacts or a deliberately different base is a question the
securitisation family needs answered before it can be pinned, and answering it
needs Art. 261–264 read as well (Art. 197(1)(h) conditions eligibility on the
position's own risk weight being 100% or lower).

---

# Scope not yet covered

- **Phase O3 is partially covered.** The Simple Method (Art. 222), the
  Comprehensive Method's supervisory volatility adjustments and composition
  (Art. 223, 224, 228(1)), the Art. 233(3) currency-mismatch adjustment and the
  Art. 235(1) guarantee substitution are covered by ORC-200 to ORC-282. Three
  things are not:
  - **F-IRB `LGD*`** (Art. 228(2), 230, 231), and with it the PS1/26
    Art. 161(5)(b) and 164(4)(c) variable LGD input floors. Every O3 oracle is an
    SA exposure.
  - **The Art. 237/238 maturity-mismatch adjustment.** Held deliberately off, not
    merely absent — see the phase O3 preamble. Note for whoever picks it up: the
    Comprehensive-Method path takes `t` from the collateral's
    `residual_maturity_years`, the same column the Art. 224 maturity band reads,
    and `T` from the exposure's `maturity_date` defaulting to 5 years; while the
    Simple Method's Art. 239(1) binary gate reads a `residual_maturity_years`
    column **on the exposure frame**, which `CLASSIFIER_EXIT_EDGE` does not
    declare — so that gate cannot fire in a pipeline run at all. That is an
    observation from building this phase, not a finding this suite asserts.
  - **The securitisation columns of Art. 224(1) Table 1** — see the note at the
    end of phase O3.
- **Basel 3.1 CRM.** Every O3 oracle is CRR. PS1/26 revises the Art. 224 tables
  (five maturity bands rather than three, and different gold and equity
  adjustments), so the B31 half of this phase is a distinct reading and is owed.
- **The output floor** (PS1/26 Art. 92(2A), `TREA = max{U-TREA; 0.725 · S-TREA +
  OF-ADJ}`) is an entity-level quantity, not a per-exposure one, so it cannot be
  driven through a single-row `calculate_branch` call. The 72.5% identity is
  asserted as a property in `tests/properties/` instead.
- **Off-balance-sheet credit conversion factors** (Art. 111, 166) are not
  covered: the drivers construct fully-drawn on-balance-sheet rows.

---

## How to add a new oracle exposure

1. Add a new section to this file with the same structure (inputs, regulation
   citation, full arithmetic, expected outputs).
2. Add a corresponding record to the right module under `derivations/` that
   computes the same values using stdlib only.
3. Run `uv run python tests/oracle/derive.py` to regenerate
   `expected_values.json` (which embeds a fresh hash of this document).
4. Run `uv run pytest tests/oracle -n 0` and confirm both the hash test and the
   new value test pass.
5. Commit all four artefacts (this doc, the derivation module,
   `expected_values.json`, `test_oracle.py`) in a single commit.

## Why this layout

The engine cannot validate itself. `tests/expected_outputs/{crr,basel31}/*` are
recorded engine outputs — they catch regressions but are structurally incapable
of detecting a wrong implementation. The property suite in `tests/properties/`
closes part of that gap, but it is blind to a **wrong constant**: if a risk
weight is 45% where the regulation says 50%, conservation still holds,
monotonicity still holds, bounds still hold, and every property passes. Only an
independent re-derivation catches it, which is what this suite is.

The hash lock prevents the most likely failure mode of an oracle suite: silently
re-pinning the JSON to whatever the engine currently produces. A drift in this
document **must** be matched by a corresponding regeneration, making the
regeneration a deliberate, auditable act. The AST check in
`test_derivations_never_import_rwa_calc` closes the other route to the same
failure — reaching into `rwa_calc` for a value rather than reading the article.
