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
disclosed in its own block.

Measured today (`ccr_b31`/`ccr_crr` goldens): OV1 row 1, labelled *"Credit risk (excluding CCR)"*,
**includes** the CCR RWEA in both regimes; under CRR row 2 (the SA of-which) does too, because CRR
CCR legs carry `approach_origin == "standardised"`. Our OV1 row list has **no rows 6/7/8/UK 8a/9/10 at
all** — so this is a template-structure change (new `P3Row`s), not a predicate tweak.

**The CCR block, resolved (both regimes — UKB OV1 carries the identical block):**

| Row | Instruction (verbatim) | Our population |
|---|---|---|
| 6 | "Counterparty credit risk – CCR … in accordance with Chapter 6 / the CCR Part" | `risk_type ∈ CCR set` (the additive parent) |
| 7 | "Of which the standardised approach … **Section 3**" (SA-CCR) | the bilateral derivative |
| 8 | "Of which internal model method (IMM) … Section 6" | **null** — IMM not implemented (CCR1 row 2 sets the precedent) |
| UK 8a | "Of which exposures to a central counterparty (CCP) … **Section 9**" | the QCCP-cleared derivative (Art. 306) |
| 9 | "Of which **other CCR** — CCR RWEAs … **that are not disclosed under rows 7, 8 and UK 8a**" | the residual: FCCM SFTs, default-fund contributions |
| 10 | "Credit valuation adjustment (CVA)" | not modelled here — see the CVA gap below |

Row 9's text **settles the partition**: rows 7/8/UK 8a/9 partition row 6, with 9 as the explicit
residual. So a QCCP trade's RWEA (computed under Section 9) belongs in **UK 8a**, not row 7 — and
SFTs, which are neither Section 3 nor Section 9, have a home in row 9 rather than breaking the
footing. Our engine already splits exactly this way, with citations
(`aggregator.py` — `rwa_ccr_default` vs `rwa_ccr_qccp_trade`), and **our own CCR1/CCR8 goldens
corroborate it**: CCR1 row 1 (SA-CCR) carries the bilateral RWEA only; CCR8 carries the QCCP RWEA.
Booking the QCCP into row 7 would make OV1 contradict CCR1/CCR8 on the same book.

**The CCR set is THREE risk types**, not two: `CCR_DERIVATIVE`, `CCR_SFT`, **and `CCR_DEFAULT_FUND`**
(Art. 307-309, Chapter 6, carries `rwa_final`). No fixture has one, so nothing moves today — but
`c07.py::_CCR_RISK_TYPES` and `of02.py::_CCR_RISK_TYPES` both omit it, which would silently
under-report for a book with default-fund contributions. Latent, unfixtured; recorded.

**Two further gaps found in passing (not this slice):** OV1 has no CVA row, and the engine's BA-CVA
charge is not a per-row `rwa_final`, so a book with a CVA charge publishes an OV1 Total that omits it.
And our B31 OV1 refs `4a/5a/5b/6a/6b/7a/7b` (pre-floor totals and capital ratios) look like BCBS
**KM1** row numbers grafted into OV1 with no citation — they do not collide with the CCR block as
strings, but one of the two numbering systems is likely wrong.

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

### D5 — Equity is missing from S-TREA (anti-conservative; NEW)

`sa_rwa` is **null on equity rows** — equity bypasses the SA calculator (it arrives via
`equity_exposures` and is concatenated at the aggregator), so the `sa_rwa` snapshot never runs on it.
Evidence: `b31/pillar3__cms2.ndjson` row 0030 (equity) — own RWEA 2,500,000, SA-equivalent **0.0**.

Under Basel 3.1 equity is Art. 133 **SA**, so its RWA *is* its SA RWA and belongs in S-TREA. Today
OF 02.01 col 0040, C 02.00 col 0020 and CMS2 col d all **understate S-TREA** by the equity RWA. A
smaller S-TREA is a **lower floor** — this is anti-conservative. Engine-carrier fix (`sa_rwa` on the
equity path); moves C 02.00 and CMS2 goldens. Its own slice.

### D6 — The engine's output floor omits the SA book's headroom (HIGHEST SEVERITY; NEW)

`engine/aggregator/_floor.py` computes U-TREA and S-TREA over `FLOOR_ELIGIBLE_APPROACHES` **only**,
justified by a comment saying *"SA exposures cancel out … so we only need the modelled subset."*
**They cancel under a subtraction, not under a `max()`.** With `A` = the SA book, the correct TREA is
`A + max(U_m, x·S_m + adj − (1−x)·A)`; the engine returns `A + max(U_m, x·S_m + adj)`. So the engine
**overstates TREA by up to (1−x)·A whenever the floor binds** — conservative, but a misstatement, and
invisible in both goldens precisely because the floor binds in neither.

Consequence for OF 02.01: `OutputFloorSummary.u_trea`/`.s_trea` are **modelled-subset** quantities,
NOT the Art. 92 U-TREA/S-TREA (rich book: `summary.u_trea` = 115,369,130.58 while the template's
U-TREA = 137,449,963.91). **OF 02.01 must keep reading nothing off `OutputFloorSummary`** — wiring
col 0030 to `summary.u_trea` would look reasonable and be wrong.

**This needs a binding-floor fixture to prove, which no golden currently has.**

### D7 — An IRB-treated CCR leg would be reported in BOTH C 07.00 and C 08.01 (NEW, latent)

`c07_population` admits any row whose `risk_type` is in the CCR set **regardless of approach**. But an
IRB-permissioned counterparty's derivative routes through IRB (`approach_applied == "foundation_irb"`),
so such a leg would land in C 07.00 (the **SA** template, via the `risk_type` limb) *and* in C 08.01
(via the IRB population) — double-reported across templates, and breaking the new C 07.00 ↔ C 02.00
tie-out (C 02.00 would book it in the IRB rows).

Pre-existing in shape (the SFT limb had the same unconditional admission), but widening the limb to
derivatives makes it likelier to bite. **No fixture exercises it** — the CCR portfolio is SA-only. The
fix is presumably to conjoin the CCR limb with "not IRB-treated", but that needs a decision about
where an IRB-treated derivative *should* report. Flagged by two independent reviewers.

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
