# IRB collateral → COREP reporting rectification

Status: in progress (branch `fix/irb-collateral-corep-reporting`)

Reported symptom: collateral allocated to retail mortgages (retail IRB) to drive the
LGD calculation does not feed through to COREP reporting. Investigation widened, at
the operator's request, to the whole collateral field set.

## Regulatory basis

Quoted verbatim from the primary sources in `docs/assets/`:

- **PS1/26 Annex II, cols 0150-0210** (`ps1-26-annex-ii-reporting-instructions.pdf`
  pp. 105-109) — "CREDIT RISK MITIGATION TECHNIQUES TAKEN INTO ACCOUNT IN LGD
  ESTIMATES". Col 0190 REAL ESTATE: *"Where exposures are subject to the Foundation
  Collateral Method … firms shall report the adjusted value of collateral Ci
  following the application of volatility adjustments and maturity mismatch
  adjustment … Where exposures are subject to the AIRB approach, the amount to be
  reported shall be the estimated market value."* Cols 0180/0200/0210 carry the same
  two-limb rule.
- **CRR Annex II, cols 0150-0210** (`crr-annex-ii-reporting-instructins.pdf`
  pp. 100-102) — the same split keyed on *"where own estimates of LGD are (not)
  used"*.
- **PS1/26 col 0060** (p. 103) — *"Other funded credit protection that is treated as
  a guarantee in accordance with Article 232 … shall be included. Other funded credit
  protection that i[s] not treated as a guarantee … shall be reported in 0172. Other
  funded credit protection recognised by firms applying the AIRB approach and using
  the LGD Modelling Collateral Method shall be reported in columns 0171, 0172 and
  0173."*
- **PS1/26 cols 0171-0173** (p. 108) — Art. 200(1)(a)/(b)/(c), each with *"The value
  of collateral reported shall be limited to the value of the exposure at the level
  of an individual exposure."*
- Retail exposures are **always A-IRB** (own LGD estimates are mandatory for retail),
  so every retail-mortgage row falls on the AIRB limb of each rule above.

## Recorded decisions

- **RD-1 — basis is method-dependent.** Cols 0180/0190/0200/0210 report the
  *estimated market value* on AIRB rows and the *adjusted value C<sub>i</sub>* on FIRB /
  Foundation-Collateral-Method rows. Today the engine reports the adjusted value on
  both limbs.
- **RD-2 (REVISED) — the cap differs BETWEEN COREP and Pillar 3.** Established by
  exhaustive regex over the full column-instruction span of all four instruction
  PDFs, so the absence of a clause is evidenced, not assumed.

  | Template / column | Cap? | Source |
  |---|---|---|
  | COREP C 08.01/02 **0180 / 0190 / 0200 / 0210** | **NO CAP** — no clause exists in either regime | PS1/26 Annex II pp.107-109; CRR Annex II pp.101-102 |
  | COREP C 08.01/02 0171 / 0172 / 0173 | Capped — "limited to the value of the exposure at the level of an individual exposure" | PS1/26 p.107 (×3); CRR pp.100-101 |
  | COREP 0040 / 0050 | Capped at the exposure value | PS1/26 p.102; CRR p.98 |
  | COREP 0150 / 0160 | Capped at the exposure value ("internal valuation … capped") | PS1/26 p.106 |
  | COREP 0060 (CRR only) | Capped at the **original exposure pre conversion factors** — a different reference amount | CRR p.99 |
  | COREP 0220 (CRR, double default) | "shall not exceed the value of the corresponding exposures" | CRR p.102 |
  | **Pillar 3 CR7-A b / c / d / e / f** (and g/h/i/j) | **CAPPED at the individual exposure value**, on BOTH the FIRB and the AIRB limb, in BOTH regimes | PS1/26 Annex XXII pp.10-11 (clause repeated per column); CRR Pillar 3 IRB pp.9-11 |

  So the same collateral is reported **uncapped** in COREP C 08.01 col 0190 and
  **capped at the exposure** in Pillar 3 CR7-A col d. That is a genuine per-template
  divergence in the published instructions, not an inconsistency to be smoothed over
  — and it is exactly the kind of per-template basis the Phase 7 F3 work already
  records per template rather than deriving once.

  PS1/26 Annex XXII col d, verbatim: *"For the FIRB approach … calculated as Ci,
  after the application of volatility adjustments and a maturity mismatch adjustment
  if relevant … and shall be capped at the individual exposure value. For the AIRB
  approach: immovable property collateral recognised under the LGD modelling
  collateral method. The amount to be included in the numerator shall be the
  estimated market value of the collateral, capped at the individual exposure
  value."*
- **RD-3 — cols 0170-0173 are conditional on the recognition method, not
  unconditionally zero.** Art. 200(1) protection the engine recognises via the
  Art. 232 guarantee treatment belongs in col 0060 and must NOT restate in
  0170-0173 (PS1/26 col 0060, quoted above). It belongs in 0171/0172/0173 only where
  the row is AIRB **and** the LGD Modelling Collateral Method is elected
  (`AIRBCollateralMethod.LGD_MODELLING` with the pack feature
  `airb_lgd_collateral_method_applicable` on). The two routes are mutually exclusive
  per leg — that exclusivity is the invariant to test.
- **RD-5 — recognition follows the firm-level election; the row flag is a positive
  override.** PS1/26 Art. 169A(1) (`ps126app1.pdf` p.120): an institution applying
  the LGD Modelling Collateral Method "may recognise the existence of collateral in
  its LGD estimates. **Collateral recognised by the institution** shall be taken into
  account…", and Art. 169A(2) frames that recognition as an institution-level
  election. CRR Annex II states the same for own-LGD firms via Art. 181(1)(e)-(f).
  So on an A-IRB exposure, collateral pledged against it is recognised for the
  purposes of the cols 0150-0210 block by virtue of the firm's election; the per-row
  `is_airb_model_collateral` flag remains a **positive** override meaning "this row
  is in the internal model, route it exclusively to the AIRB pool" (its existing
  semantics, unchanged). Recorded limitation: the column's loader default is `False`
  (`data/schemas.py:760`), so there is today no way to assert "explicitly NOT
  recognised"; no requirement for that has been identified, and making the column
  null-permissive was judged a larger, riskier change than the defect warrants.
- **RD-6 — the fix is purely additive; no existing carrier is repointed.** The
  original W1 design (repointing the unflagged pro-rata denominators on the existing
  `collateral_*_value` carriers) was **withdrawn**: those carriers are not pure
  disclosure. `collateral_adjusted_value` drives the SA Comprehensive-Method EAD
  reduction (`engine/crm/collateral.py:1438-1453`, `engine/crm/simple_method.py:381-412`)
  and `collateral_re_value` / `collateral_other_physical_value` feed the CRR Art. 230
  minimum-collateralisation threshold gate (`collateral.py:1274-1300`) — all effect
  paths. Repointing them would have moved SA and FIRB capital and reverted the
  deliberate migration pinned by
  `tests/unit/crm/test_airb_model_collateral_flag.py::TestUnflaggedCounterpartyCollateral::test_airb_excluded_from_pro_rata_base`.
  Instead the **new market-value carriers** (W2) are computed pool-agnostically and
  are consumed by the reporting layer only. Consequences: FIRB/FCM rows keep
  reporting the existing adjusted carriers unchanged; A-IRB rows report the new
  market-value carriers; **no capital number moves**; and the conflicting test needs
  no edit.
- **RD-4 — disclosure carriers are pool-agnostic; effect carriers stay pool-gated.**
  The AIRB pool gate (`engine/crm/collateral.py:1528-1541`, `:1214-1226`) is a
  deliberate, cited decision — on an A-IRB row the LGD is the firm's own estimate,
  so only collateral the firm actually modelled (`is_airb_model_collateral=True`)
  may move it (CRR Art. 181 / PS1/26 Art. 169A). That reasoning is sound and is NOT
  overturned. The defect is that the same pool-gated blend also feeds the pure
  **disclosure** carriers, which Annex II requires to report the collateral that
  exists against the exposure regardless of whether it moved the modelled LGD — and
  the gate is applied inconsistently anyway, since the direct/loan-level term
  `_n_d` in `_sum6` carries no gate at all.
  - **Disclosure carriers** (`collateral_<category>_value` and their new
    market-value twins): pool-agnostic, at every beneficiary level.
  - **Effect carriers** (`crm_alloc_*`, `total_collateral_for_lgd`,
    `ead_after_collateral`, `lgd_post_crm`): pool gate unchanged.
  - Flagged collateral must not reach a non-AIRB exposure on **either** path.
  - Consequence: **this fix moves no capital number.** That invariant is itself a
    test.

## Defects

| ID | Defect | Evidence |
|----|--------|----------|
| **D1** | Unflagged collateral pledged at **facility or counterparty** level is invisible to any A-IRB row: `_cw_n` is hard-zero when `_is_airb_pool` (`engine/crm/collateral.py:1216-1219`) and `_w_n` likewise (`:1572-1581`). Loan-level unflagged collateral flows unconditionally (`_n_d` in `_sum6`, `:1237-1248`). Retail is always A-IRB, so the same property reports or vanishes purely on where it is pledged. No warning is raised. | Probe: counterparty-level pledge → `collateral_re_value` 0.0; identical row at loan level → 500,000. |
| **D2** | A-IRB rows report the **adjusted (post-haircut) value** where the instructions require the **estimated market value**. Under B3.1 the real-estate supervisory haircut is 40% (`rulebook/packs/b31.py:913`), so a 500,000 property publishes as 300,000. Under CRR the haircut is 0%, which is the only reason CRR looks right. The CRR-vs-B3.1 divergence on identical input (500,000 vs 300,000, goldens) is the symptom. | `engine/crm/collateral.py:1250-1257`, `engine/crm/haircuts.py:326-335`. |
| **D3** | The guarantee leg-split never pro-rates collateral: `_stock_split_cols()` (`engine/crm/guarantees.py:61-76`) omits every `collateral_*` / `crm_alloc_*` column, so each `__G_` / `__REM` leg inherits the **full** value and `Sum()` counts it once per leg. **Pure disclosure defect** — see RD-7; an earlier draft of this row claimed a capital defect and was WRONG. | 2-leg split reproduces at exactly 2× the correct value; 3-leg Art. 234 tranche split at 3×. Affects C 08.01/02 cols 0180-0210, C 07.00 col 0130 and Pillar 3 CR7-A on any guaranteed exposure. |
| **D4** | `cash` / `deposit` is categorised ahead of `financial` (`engine/crm/expressions.py:229-233`), so it lands in `collateral_cash_value` — **a carrier no template reads**. Col 0180 (Art. 197 eligible financial collateral) under-reports cash on every IRB row. The Art. 231 waterfall groups them correctly (`WATERFALL_ORDER`, `:248`), so the engine contradicts itself. | — |
| **D5** | An unrecognised `collateral_type` falls silently to category `"other"` (`engine/crm/expressions.py:241`). No DQ error is raised, the collateral reports in no CRM column, **and RWA changes** (probe: B3.1 39,848 → 71,534 when `real_estate` is spelled `residential_real_estate`). | — |
| **D6** | Cols 0170/0171/0172/0173 are hardcoded `_const(0.0)` (`reporting/corep/c08.py:832-835`) with no method condition. 9 ERROR + 2 WARNING published rules (`boe_b0750`, `boe_b0375/6/7`, `boe_b0752_15/16/17`, `boe_b0814_13`, `v09751_m`, `v09752_m`) pass vacuously. | See RD-3. |
| **D8** | **Pillar 3 CR7-A collateral ratios are uncapped and exceed 100%.** `reporting/pillar3/cr7a.py:111-112` binds `Ratio(source, "reporting_ead", scale=100.0)` with no cap, but PS1/26 Annex XXII and the CRR Pillar 3 IRB instructions both require the numerator "capped at the individual exposure value" on every collateral column (b/c/d/e/f) and both limbs. The committed golden `irb_classes_crr/pillar3__cr7a__advanced_irb.ndjson` publishes **col d = 166.67%** (500,000 / 300,000) — a live breach. The B3.1 golden reads 100.0% only by the coincidence of 60% LTV × 40% haircut, not because any cap was applied. | See RD-2. |
| **D7** | `collateral_market_value` / `collateral_adjusted_value` are filtered by `is_eligible_financial_collateral` (`engine/crm/collateral.py:986-990, 1117-1118`), whose loader default is `False`. They are therefore 0.0 on every property-collateralised row while their names promise a total. Documentation/naming defect only — the SA FCCM consumers are correct. | Record; do not change behaviour. |
| **D9** | **The P1.235 Art. 199(2)/(5)/(6) eligibility gate stops at `effectively_secured` and never reaches the `_adj_*` carriers.** So an unattested property pledge is *zeroed for LGD* but *published in full* in C 08.01/02 col 0190 and Pillar 3 CR7-A — the reported symptom: `reporting_crm_lgd_real_estate` populated while the F-IRB LGD stays at the supervisory unsecured 0.45. Same shape on 0200 (Art. 199(6)) and 0210 (Art. 199(5) receivables). It is also a **capital** defect: the ungated `collateral_re_value` is the C in the Art. 230 C\* test, so an ineligible pledge buys an eligible one the 30% threshold. `is_eligible_irb_collateral` has loader default `False` (`data/schemas.py:1023`), so **every portfolio that does not populate the flag is in this state**. | Probe (CRR, £1m senior corporate-SME F-IRB, £1.5m RE): unattested → `lgd_post_crm` 0.45, `collateral_re_value` 1,500,000, one CRM014. Mixed probe: eligible £200k alone → 0.45; + unattested £500k → 0.435714. See RD-9. |

- **RD-7 — the Art. 231 waterfall allocations are NOT split across guarantee legs,
  and D3 carries no capital effect.** An earlier draft asserted that the pre-fix
  A-IRB blended LGD floor was understated because a per-leg `ead` met a
  whole-exposure `total_coll`. **That premise was false** and was caught in review.
  The floor divides by `lgd_star_exposure_basis_expr()` = `ead_for_crm × (1 + HE)`
  (`engine/crm/expressions.py:107`), and `ead_for_crm` is neither in
  `_stock_split_cols()` nor recomputed after `_initialize_ead` — it stays
  whole-exposure on **every** leg. The blend is a rate, homogeneous of degree 0:
  splitting both sides is number-neutral, splitting neither is number-neutral, and
  splitting only the numerator is the single wrong option. The pre-fix code split
  neither, so the floor was correct; the first cut of D3 split only the numerator
  and would have raised the floor on every guaranteed leg (conservative in
  direction, but wrong, and invisible to the suite). Worked example from the
  review — E' = 1,000,000, C = 425,000 real estate at LGDS 10%, LGDU 25%, coverage
  0.4: 18.625% before, 21.175% after, +2.55pp of spurious floor.
  Nothing under `reporting/` reads `crm_alloc_*` or `total_collateral_for_lgd`
  (grepped), so splitting them buys no disclosure benefit against that risk. They
  are therefore excluded, and **only the seven collateral valuations are split**.
  If a future change needs them per-leg, `ead_for_crm` must be split in the same
  commit.

- **RD-8 — the Art. 200(1) routing decision is made ONCE in `engine/crm/`, not in
  `reporting/`.** PS1/26 col 0060 (p.103) makes cols 0060 and 0171-0173 mutually
  exclusive per leg: protection treated as a guarantee under Art. 232 reports in
  0060, protection recognised under the AIRB LGD Modelling Collateral Method
  reports in 0171/0172/0173. Which route applies depends on the run-level
  `AIRBCollateralMethod` election, and **that election does not reach the COREP
  generator** — `generate_c08_01` and siblings receive only
  `(results, cols, framework, errors)`, with no `config`, no `resolved_pack` and no
  per-row method flag. Threading `framework` in is easy plumbing; threading the
  election in is not, and re-deriving it in `reporting/` would put a regulatory
  decision in the presentation layer, against the sealed-ledger design.

  So the CRM stage — which already holds the config and pack and already computes
  `airb_lgd_preserved_expr` — emits three **mutually exclusive by construction**
  amounts, and the aggregator seals them as plain aliases:

  | engine carrier | sealed as | cell |
  |---|---|---|
  | `ofcp_lgd_cash_deposit` (Art. 200(1)(a), capped at exposure) | `reporting_ofcp_lgd_cash_deposit` | 0171 |
  | `ofcp_lgd_life_insurance` (Art. 200(1)(b), capped at exposure) | `reporting_ofcp_lgd_life_insurance` | 0172 |
  | `ofcp_substitution_amount` (Art. 232 guarantee route) | `reporting_ofcp_substitution` | 0060 |

  Col 0173 (Art. 200(1)(c)) stays 0.0 — no engine carrier exists for instruments
  repurchased on request. The `{c0170} = {c0171}+{c0172}+{c0173}` identity
  (`boe_b0750`, `v09752_m`, `v09751_m`) and the `{c017x} <= {c0170}` bounds
  (`boe_b0375/6/7`) then hold by construction, and the 0060/0171-0172 exclusivity
  becomes structural rather than a reporting-layer convention. Under CRR the
  LGD-Modelling route cannot arise at all —
  `airb_lgd_collateral_method_applicable` is a Basel-3.1-only pack Feature — so the
  CRR limb keeps today's behaviour unchanged.
- **RD-9 — the Foundation limb of cols 0190/0200/0210 is scoped by Art. 199, so the
  Art. 199(2)/(5)/(6) eligibility gate must reach the `_adj_*` carriers.** RD-4 made
  the *pool* gate a disclosure/effect split; it did **not** licence disclosing
  collateral that is regulatorily unrecognisable. Both instruction sets scope the
  Foundation limb's population by article, not merely by valuation basis:

  - CRR Annex II col 0190 (`crr-annex-ii-reporting-instructins.pdf` p.102), verbatim:
    *"Where own estimates of LGD are not used, values shall be determined in
    accordance with paragraphs 2, 3 and 4 of Article 199 CRR and shall be reported in
    this column."* Col 0200 reads *"paragraphs 6 and 8 of Article 199"*, col 0210
    *"Articles 199(5) and 229(2)"*.
  - PS1/26 Annex II col 0190 (`ps1-26-annex-ii-reporting-instructions.pdf` p.109),
    verbatim: *"Where exposures are subject to the Foundation Collateral Method …
    collateral in accordance with Article 199(2) of the Credit Risk Mitigation (CRR)
    Part … Firms shall report the adjusted value of collateral Ci …"*
  - The block heading is *"CREDIT RISK MITIGATION TECHNIQUES **TAKEN INTO ACCOUNT IN
    LGD ESTIMATES**"*. Collateral the P1.235 gate zeroes is taken into account in no
    LGD estimate.

  The **AIRB limb stays ungated** — both regimes condition it on Art. 169A(1)/169B
  (PS1/26) and Art. 181(1)(e)-(f) (CRR), the firm's institution-level election, not
  the FCM attestation — so the `_mv_*` carriers are untouched and RD-5 stands. The
  financial/cash carriers are likewise untouched: col 0180's eligibility is Art. 197's
  own `is_eligible_financial_collateral` gate (D7).

  **This one moves capital, conservatively, and that is the second half of the
  defect.** `collateral_re_value` / `collateral_other_physical_value` are the C in the
  CRR Art. 230 minimum-collateralisation (C\*) test, so on the ungated carriers an
  *ineligible* pledge lifted an *eligible* one over the 30% threshold it failed alone.
  Measured on a £1m senior corporate-SME F-IRB exposure under CRR: eligible £200k
  alone → C/E 20% → C\* fails → LGD 0.45; adding an **unattested** £500k row → C
  reads £700k → C\* passes → LGD **0.435714** off £142,857 of secured amount that the
  unattested row contributed nothing to. Post-fix both read 0.45.

## Verified stage order (settles the D3 capital question)

`engine/crm/processor.py`: `_apply_collateral_unified_step` (`:654`) runs **before**
`_apply_guarantees_step` (`:686`) — the documented chain is provisions → CCF → EAD →
collateral → guarantees → finalise. The SA Comprehensive-Method EAD reduction has
therefore already consumed `collateral_adjusted_value` and produced
`ead_after_collateral` by the time the guarantee split runs, so pro-rating the
collateral carriers across legs **cannot** move SA `E*`. The only capital consumer
downstream of the split is the A-IRB blended LGD floor
(`engine/irb/formulas.py:455-461`), which the split moves in the **conservative**
direction. This is why D3 changed no number in the committed estate: no fixture
pairs a guaranteed IRB leg with collateral — the path is uncovered, not inert.

## Work items

| ID | Scope | Files owned | Depends on |
|----|-------|-------------|------------|
| **W1** | D1 — split the disclosure carriers off the pool-gated blend so they are pool-agnostic at every beneficiary level, leaving the effect carriers' gate untouched, per RD-4. | `engine/crm/collateral.py` | — |
| **W2** | D2/D4 — add per-category **market-value** carriers mirroring the `_adj_*` set; fold `cash` into the financial category for reporting. | `engine/crm/collateral.py`, `contracts/edges.py` | W1 |
| **W3** | D3 — add the collateral / `crm_alloc_*` carriers to the guarantee leg-split stock columns. | `engine/crm/guarantees.py` | — |
| **W4** | D5 — DQ warning for a `collateral_type` matching no known category. | `engine/crm/expressions.py`, `engine/crm/collateral.py`, `contracts/errors.py` | W2 |
| **W5** | RD-1/RD-3 — seal the method-resolved CRM-in-LGD carriers on the reporting projection. | `engine/aggregator/aggregator.py`, `contracts/edges.py` | W2 |
| **W6** | D6 + RD-2 — bind the sealed carriers in C 08.01/02 and Pillar 3 CR7-A; wire 0170-0173 behind the LGD-Modelling condition; cap 0171-0173 only. | `reporting/corep/c08.py`, `reporting/pillar3/cr7a.py` | W5 |
| **W7** | Fixtures, tests, goldens, changelog, docs. | `tests/**`, `docs/appendix/changelog.md` | W1-W6 |

## Known coverage gaps this branch must close before merge

1. **No committed portfolio pairs a guaranteed IRB leg with collateral.** The whole
   10,595-test estate was green through a real capital error in the first cut of D3
   for exactly this reason (see RD-7). A fixture combining B3.1 + A-IRB + a guarantee
   split + collateral is required, asserting that the blended LGD floor on the
   `__REM` leg equals the unsplit exposure's floored LGD — i.e. that the allocations
   are NOT split. Without it, the RD-7 reasoning is documented but unenforced.
2. **Cols 0200 (other physical) and 0210 (receivables) are zero in every committed
   golden and asserted nowhere.** Only `collateral_re_value` is ever exercised, on
   one sheet. Their first value assertions arrive with W6.
3. **Two W6 tests currently pass for the wrong reason** — col 0060's `SafeSum` finds
   neither raw carrier in the new fixture and falls back to the zero-fill convention,
   so green means "column absent", not "exclusivity implemented". They become genuine
   only once 0060 is repointed at `reporting_ofcp_substitution`. Same failure mode as
   the C 07.00 CCF-bucket defect that published nulls for the template's life.
4. **Nine ERROR-severity published rules over cols 0170-0173 pass vacuously today**
   (`boe_b0750`, `boe_b0375/6/7`, `boe_b0752_15/16/17`, `boe_b0814_13`, plus
   `v09752_m` / `v09751_m` as WARNINGs). They go live the moment a value appears. The
   supervisory validation register ratchets BOTH ways, so a newly-passing rule fails
   the ratchet until the register is regenerated centrally.
5. **The CR7-A golden is knowingly red** pending regeneration on a stable tree
   (`pillar3__cr7a__advanced_irb` cols c and d, 166.67 → 100.0). Regeneration must be
   serial — regenerating while agents share the tree captures unrelated in-flight
   state, and `REGEN` rewrites ALL goldens.

## Engine traps found while building the enforcement fixture

- **A "corporate + real-estate collateral + A-IRB" exposure is unreachable via the
  classifier.** `engine/stages/classify/attributes.py:625-639`'s `is_mortgage` rule
  fires on `property_collateral_value > 0` **regardless of the borrower's
  `entity_type`**, so such a row reclassifies to `commercial_mortgage` — and
  `engine/irb/formulas.py:387-390` records that `commercial_mortgage` /
  `residential_mortgage` are SA-re-splitter-only classes that never carry an IRB
  approach. Verified empirically: `approach` comes back `"standardised"` on both
  legs despite an A-IRB `model_permissions` grant. Any future fixture needing
  corporate + IRB + immovable-property collateral must either bypass the classifier
  or use a different collateral category.
- **`denomination_currency_expr` prefers `original_currency` over `currency`
  whenever the column is PRESENT, even if null**, silently applying the Art. 233(3)
  8% FX cut to a life-insurance pledge. A CRM fixture that omits `original_currency`
  gets a quietly reduced value.

## Follow-ups deliberately NOT taken in this branch

- **A-IRB third-party deposits are reportable nowhere.**
  `engine/crm/third_party_deposit.py:140` zeroes `third_party_deposit_value` for
  BOTH F-IRB and A-IRB, while the variable is named `is_firb` and the docstring
  says only F-IRB is deferred. So an A-IRB Art. 200(1)(a) deposit has no value to
  route, and COREP col 0171 reports 0.0 — truthfully, since the engine grants no
  recognition, but the underlying gate looks unintended.

  **Narrowing it is RWA-reducing and must not ride along with a disclosure fix.**
  The obvious argument for narrowing — "no A-IRB capital consumes this column" —
  is wrong: `engine/sa/calculator.py:110-118` runs
  `apply_third_party_deposit_rw_mapping` **unconditionally**, its own comment
  saying it "also provides SA-equivalent RW for the IRB output floor". So the
  carrier feeds `sa_rwa` on A-IRB legs, and the blend is benefit-only capped
  (`min_horizontal(blended_rw, risk_weight)`), so it can only reduce the
  SA-equivalent — lowering the Basel 3.1 output floor wherever it binds. This was
  attempted mid-branch and reverted. The output-floor path makes almost every
  `engine/sa/` function an indirect IRB consumer; "nothing reads X" needs checking
  against it specifically.

  Requires its own review, its own output-floor regression evidence, and its own
  scope decision.
- **Art. 200(1)(c) instruments repurchased on request (col 0173)** — no engine
  carrier exists; the column stays a recorded 0.0.

## Invariants a fix must preserve

- `{OF08.01 r0070, cNNNN} = sum({OF08.02, cNNNN})` for c0150/0160/0171/0172/0173/0180/0190/0200/0210 (`boe_b0752_12..21`, `boe_b0814_11..17`, all ERROR/live). C 08.01 and C 08.02 share `_value_cells`, so this holds structurally — do not fork them.
- `{c0170} = {c0171} + {c0172} + {c0173}` (`boe_b0750`, `v09752_m`, `v09751_m`) and `{c017x} <= {c0170}` (`boe_b0375/6/7`).
- Cols 0150-0220 must never enter `_NEGATIVE_COLS` — `v3713_s` / `v3721_s` assert `>= 0` over that span.
- Pillar 3 CR7-A cols b/d/e/f read the same four carriers as C 08.01 cols 0180/0190/0200/0210 and must move in lockstep.
- The supervisory validation register ratchets **both** ways; a newly-passing rule fails the ratchet until the register is regenerated centrally.
