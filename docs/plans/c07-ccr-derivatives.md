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
- [ ] **5 — C 02.00 row 0060 (and OV1 row 2)** to include `standardised_ccr` RWEA so the breakdown
      foots to the total. **NUMBER-CHANGING.**
- [ ] **6 — Tie-out tests** that would have caught this: C 07.00 total RWEA == C 02.00 SA row; and a
      derivative EAD/RWEA conservation check across C 34 ↔ C 07.00 (the mirror of the SFT test at
      `tests/acceptance/reporting/test_reporting_sft_c07_0090.py`, which exists for SFTs only).

### Open question for step 3/4

C 07.00 col 0010 ("Original exposure pre conversion factors") is `SafeSum(drawn_amount,
undrawn_amount)`. The CCR adapter sets `drawn_amount = ead_ccr`
(`engine/ccr/pipeline_adapter.py`), so the column does populate for derivative rows — but whether
the *exposure value* is the right thing to report in col 0010 for a CCR row (vs the C 34.02 col 0160
cross-reference) must be checked against the column instructions before step 4 lands.
