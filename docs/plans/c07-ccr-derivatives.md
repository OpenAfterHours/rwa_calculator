# C 07.00 and SA-CCR derivatives — a measured defect, and the fix

**Status:** OPEN — steps 1 (honest scope text) and 2 (goldens) DONE; steps 3–6 outstanding.
**Raised by:** an operator reading the cell-lineage drill-down, which surfaced a scope note that
turned out to be false. (The drill-down doing exactly its job: a hidden scope decision, made visible.)
**Date:** 2026-07-12

---

## 1. What the regulation requires

COREP Annex II, C 07.00:

- Rows 0070 / 0080 (on- and off-balance-sheet): *"Exposures that are subject to counterparty credit
  risk shall be reported in **rows 0090 – 0130**, and therefore shall not be reported in this row."*
- Rows 0090–0130: *"Exposures / Transactions subject to counterparty credit risk, i.e. derivative
  instruments, repurchase…"* — with **0110 = "Netting sets containing only derivatives listed in
  Annex II CRR and long settlement transactions"**, and 0100 / 0120 the "of which: centrally cleared
  through a QCCP" sub-rows, 0130 contractual cross-product netting sets.
- The column instructions take the CCR exposure value *"as per the instructions to column 0160 of
  template C 34.02"*.

**C 07.00 and C 34 are not alternatives.** C 34 analyses CCR by approach; C 07.00 risk-weights those
same CCR exposures under the standardised approach. A derivative belongs in **both**.

---

## 2. What the code does today (measured, not inferred)

Run: `tests/fixtures/ccr/golden_ccr_a10` (one SA-CCR derivative netting set), through the real
pipeline, both regimes.

| | CRR | Basel 3.1 |
|---|---|---|
| `approach_applied` on the derivative row | `standardised` | `standardised_ccr` |
| Admitted to C 07.00? | **yes** (incidentally) | **no** |
| C 07.00 total row 0010 (RWEA) | 17,735,775 | — (no sheet produced at all) |
| C 07.00 risk-weight band row | 17,735,775 (50% band) | — |
| C 07.00 rows 0070 / 0080 / 0090 / **0110** | **all null** | — |
| C 34.01 (EAD, RWEA) | 35,471,550 / 17,735,775 | 12,565,411 / 3,769,623 |

### The defects

1. **Both regimes:** rows 0100 / 0110 / 0120 / 0130 are inert (`_terms_for_row` returns `None`), so
   the exposure-type breakdown **does not foot to the total**. Row 0110 — the row that exists for
   exactly this — is empty.
2. **Basel 3.1, material:** derivatives are dropped from C 07.00 **entirely**; the SA credit-risk
   EAD and RWEA are **understated**.
3. **Basel 3.1:** C 02.00 rows 0010/0050 (total) include the derivative RWEA, row 0060 (SA) does
   not — so **C 02.00 does not foot** either. Pillar 3 OV1 row 2 carries the same asymmetry.
4. **The scope note was false.** "SA-CCR derivatives are excluded — they report under C 34" was
   never a scope decision: it rationalised an artefact.

### Root cause

`engine/stages/calc.py` relabels `approach_applied` to `standardised_ccr` for
`CCR_DERIVATIVE` + `CCR_SFT` rows **only when the `output_floor` feature is on** (Basel 3.1), so the
rows route into `FLOOR_ELIGIBLE_APPROACHES`. C 07.00 filters on `"standardised"`, so under Basel 3.1
they fall out and under CRR they do not. SFTs were later re-admitted explicitly by `risk_type`;
derivatives never were.

**The trap:** do NOT fix this by relabelling the approach back to `"standardised"` — that label is
load-bearing for the output floor. Admit by `risk_type`, the precedent SFTs already set.

### No double-count risk

C 02.00, OF 02.01 and Pillar 3 OV1 each read the **full sealed ledger** directly; none of them sums
C 07.00 and C 34 together. Changing the C 07.00 population moves nothing in the roll-ups.

---

## 3. Steps

- [x] **1 — Correct the false scope text** (`c07.py` docstrings, `generator.py` comment, and the
      `lineage.py` scope string the operator actually reads). No numbers move.
- [x] **2 — Goldens first.** `tests/fixtures/reporting_ccr_portfolio.py` + a golden set, so the
      remaining steps have an oracle. Deliberately authored **against current (defective) behaviour**:
      the goldens are a *snapshot*, not a blessing, and the fix's diff against them IS the proof.
      Partially closes the recorded Phase 7 S8-pre gap (the CCR templates had no goldens at all).
- [ ] **3 — Populate rows 0110 / 0100 / 0120** (`risk_type == "CCR_DERIVATIVE"`; QCCP via
      `cp_entity_type`/`cp_is_qccp` — all already sealed). Record 0130 (cross-product netting) as
      not-modelled.
- [ ] **4 — Basel 3.1: admit `CCR_DERIVATIVE` into `c07_population`** by `risk_type`.
      **NUMBER-CHANGING** — recorded decision + oracle sign-off.
- [ ] **5 — C 02.00 only.** Row 0060 ("Of which: SA") and the SA class rows must include
      `standardised_ccr` RWEA so the template foots. **NUMBER-CHANGING.**
      **Basis (read from the Annex II PDF):** C 02.00's parent credit row is "RISK WEIGHTED EXPOSURE
      AMOUNTS FOR CREDIT, **COUNTERPARTY CREDIT** AND DILUTION RISKS AND FREE DELIVERIES"; its
      "Standardised Approach (SA)" child is defined as *"CR SA and SEC SA templates at the level of
      total exposures"* — the SA row **is** the C 07.00 total, which now includes CCR.
      **~~and OV1 row 2~~ — REMOVED FROM STEP 5. That instruction was WRONG (see §4).**
- [ ] **6 — Tie-out tests** that would have caught this: C 07.00 total RWEA == C 02.00 SA row; a
      derivative RWEA conservation check across C 34 ↔ C 07.00 (the mirror of the SFT test at
      `tests/acceptance/reporting/test_reporting_sft_c07_0090.py`); and C 07.00's own section-2
      footing (0070+0080+0090+0110+0130 == row 0010).

---

## 4. Defects found while doing steps 3-5 — each its own slice, NOT half-fixed here

Surfaced by the step-5 investigation (a scenario-architect + an adversarial reviewer), then verified
by the orchestrator against the instruction PDFs and the committed goldens. **None is caused by the
C 07.00 fix**; all are pre-existing, and the C 07.00 fix merely made two of them visible.

### D1 — Pillar 3 OV1 has no CCR row block, and row 1 lies (BOTH regimes)

The plan's original step 5 said "OV1 row 2 carries the same asymmetry". **That was wrong, and wrong
in the opposite direction.** Verbatim, from the OV1 instructions:

> **Row 1 — Credit risk (excluding CCR):** "RWEAs and own funds requirements calculated in accordance
> with Chapters 1 to 4 of Title II of Part Three CRR … **RWEAs for securitisation exposures in the
> non-trading book and for CCR are excluded and disclosed in rows 6 and 16 of this template.**"
> **Row 6 — Counterparty credit risk – CCR:** "…calculated in accordance with Chapter 6…"
> **Row 7 — CCR – Of which the standardised approach:** "…in accordance with **Section 3** of
> Chapter 6…" (SA-CCR)
> **Row UK 8a — CCR – Of which exposures to a CCP:** "…in accordance with **Section 9** of Chapter 6…"

So: **adding CCR to OV1 row 2 would be a misstatement.** CCR must be *removed* from rows 1 and 2 and
disclosed in its own block. The of-whichs partition by *RWEA computation basis*, so a QCCP trade's
RWEA (Art. 306, Section 9) belongs in **UK 8a**, not row 7.

Measured today (`ccr_b31`/`ccr_crr` goldens): OV1 row 1, labelled *"Credit risk (excluding CCR)"*,
**includes** the CCR RWEA in both regimes; under CRR row 2 (the SA of-which) does too, because CRR
CCR legs carry `approach_origin == "standardised"`. Our OV1 row list has **no rows 6/7/8/UK 8a at
all** — so this is a template-structure change (new `P3Row`s), not a predicate tweak.

### D2 — Pillar 3 CMS1: the CCR row is null and the Total is not a total (Basel 3.1)

`cms1.py` gives row 0010 ("Credit risk excluding CCR") and row 0080 ("Total") *identical* cell specs,
and row 0020 ("Counterparty credit risk") is never bound. Internal oracle, no PDF needed: **CMS1
Total col c = 2,500,000 while CMS2 Total col c = 4,060,296.72** — the same book, disagreeing by
exactly the derivative RWEA. CMS2 is the correct one (it already books the derivative under
Institutions). CCR-via-SA is floor-eligible (`FLOOR_ELIGIBLE_APPROACHES`), so it must appear in the
floor comparison.

### D3 — OF 02.01: U-TREA is DOUBLE-COUNTED (pre-existing, regime-independent)

`of02.py` sets col 0010 = `Sum(rwa_pre_floor)` over the **whole** portfolio and col 0020 =
`Sum(sa_rwa)` over the **whole** portfolio, then col 0030 (U-TREA) = 0010 + 0020. But
`rwa_pre_floor` summed over the whole ledger **already is** U-TREA (own-approach RWA), and `sa_rwa`
summed over the whole ledger is S-TREA. Adding them is meaningless.

Verified on the **rich** portfolio at commit `c1a120ba` — i.e. before any CCR work touched anything:
modelled 137,449,963.91 + SA 161,655,833.33 → **U-TREA 299,105,797.25, 2.18× the modelled RWA.**
This is the most serious of the four: the output floor compares U-TREA against S-TREA.

### D4 — CRR CR4/CR5 leak CCR into SA disclosures (the mirror of the C 07.00 defect)

`cr4.py`/`cr5.py` filter `approaches_origin=("standardised",)`, which under **CRR** admits the CCR
legs (they carry `"standardised"` there; under Basel 3.1 the relabel excludes them, correctly — the
Basel SA disclosure templates scope CCR out, it has CCR1–CCR8). Measured in `ccr_crr`: CR4 row 6
(Institutions) reports RWEA 2,858,279.37 against **zero** exposure in cols a–d, giving a published
RWEA-to-exposure density of **1.07** — prima facie nonsense. CR5 row 6 carries the derivative EADs in
the 2% and 50% bands.

**Live trap for whoever fixes D1/D2:** do NOT implement by widening a *shared* SA-approach constant
to include `standardised_ccr` — that would silently pull the derivative into Basel 3.1 CR4/CR5 and
break the B3.1 disclosure too. Exclude/include CCR by **`risk_type`**, never by the approach label
(under CRR the label is `"standardised"`, so an approach-based rule no-ops exactly where the CRR
defect lives).

### Open question for step 3/4 — RESOLVED 2026-07-12 (read from the Annex II PDF)

**Col 0010 is correct as it stands; no CellSpec change needed.** Annex II, col 0010 "ORIGINAL
EXPOSURE PRE-CONVERSION FACTORS": *"…with the following qualifications stemming from Article 111(2)
CRR: 1. For Derivative instruments … subject to counterparty credit risk … **the original exposure
shall correspond to the Exposure Value for Counterparty Credit Risk** (see instructions to column
0210)."* The CCR adapter sets `drawn_amount = ead_ccr`, so `SafeSum(drawn_amount, undrawn_amount)`
already yields the SA-CCR EAD. (The C 34.02 col-0160 cross-reference belongs to **col 0210**, not
col 0010 — it governs allocating an obligor's exposure across netting-set rows.)

**Cols 0210/0211 are REQUIRED, not optional — folded into step 3.** Col 0200: *"Exposure values for
CCR business shall be the same as reported in column 0210."* Col 0210 = *"Of which: Arising from
Counterparty Credit Risk"* — the CCR exposure value. Col 0211 = *"Exposures reported in column 0210
excluding those arising from contracts and transactions listed in Article 301(1) CRR"* (i.e.
excluding CCP-cleared). Both are hard-coded null today; the same inert-CCR-cell defect.

### Row membership (settled)

0110 is the **additive parent** = every derivative netting set, *including* the QCCP-cleared ones;
0120 is the **"of which"** QCCP subset of 0110; 0100 is the QCCP subset of **0090** (SFTs), not of
the CCR block. **Trap:** writing 0110 as "derivative AND NOT qccp" makes 0120 a sibling rather than
an of-which, and the breakdown stops footing.

Row 0130 (contractual cross-product netting, Art. 295(c)) stays null — **not modelled**: there is no
input carrier for a cross-product netting agreement. Recorded as a scope limitation, not as
"we checked and there are none".
