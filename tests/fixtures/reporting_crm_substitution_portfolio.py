"""
CRM guarantee-substitution reporting portfolio — the C 07.00 / C 08.01 / C 08.02
outflow/inflow axis.

Pipeline position:
    build_reporting_crm_substitution_bundle() -> RawDataBundle -> PipelineOrchestrator
        -> AggregatedResultBundle -> COREPGenerator / Pillar3Generator

Why this portfolio: every substitution cell (C 07.00 cols 0050/0060/0090/0100,
C 08.01 cols 0040/0050/0070/0080, C 08.02 col 0080) is exactly 0.0 in every one of
the 70+ frozen golden ndjson files under ``tests/expected_outputs/reporting/`` —
no golden portfolio contains a guaranteed exposure that migrates exposure class.
This portfolio closes that blind spot with guarantee legs, each on a
distinct obligor/guarantor pair with a distinct round guaranteed amount so a
mis-posted cell is identifiable on sight. S1-S5 are all BENEFICIALLY substituted
(``is_guarantee_beneficial`` derives True); S6 adds the DECLINED complement
(Finding 4 / ``engine/aggregator/aggregator.py::_beneficial_gate``) — a guarantee
that exists (``is_guaranteed=True``, positive ``guaranteed_portion``) but must
NOT migrate class/approach or book any outflow/inflow, because the guarantor's
risk weight is no better than the obligor's own. S7 adds a SECOND blind spot,
on the COUNTRY axis rather than the class axis: S1-S6, verified by direct
inspection, put every counterparty that ever reaches a reported leg in GB —
S6's non-GB (US) guarantor is DECLINED, so its country never reaches a leg at
all (see the OB_S7/GTOR_S7 constant declarations below). PRA PS1/26 Annex II
Section 3.4 para 87 (C 09.01/C 09.02 geographical breakdown) requires "original
exposure pre-conversion factors" to key the country of residence of the
IMMEDIATE obligor, while "exposure value" and "Risk-weighted exposure amounts"
key the country of residence of the ULTIMATE obligor — a column-level basis
split that migrates with a beneficial guarantee exactly as class does (para 86:
"CRM techniques with substitution effects can change the allocation of an
exposure to a country"). A GB-only portfolio cannot exercise that split at all:
immediate and ultimate obligor are the same country on every leg, so the two
bases are indistinguishable. S7 is a beneficially-substituted guarantee whose
guarantor sits in a different country from its obligor, closing that gap.

S8 adds a THIRD blind spot, orthogonal to both: no beneficially-substituted
SLOTTING leg exists anywhere (S6, the fixture's only slotting-origin leg, is
DECLINED), so COREP C 08.06 / Pillar 3 CR10's per-category risk-weight
columns are never reached at all. Worse than a coverage gap: a slotting
category holding BOTH an unguaranteed leg (at the category's own weight) and
a substituted leg (at the guarantor's) produces a MEANINGLESS EAD-weighted
BLENDED risk weight that sits inside the category's own band and looks
plausible rather than obviously wrong — a single fully-guaranteed leg would
not expose this. S8 reproduces exactly that two-leg shape in its own
isolated category. See the OB_S8/GTOR_S8 constant declarations below for
the production-shaped prototype that surfaced this and the full mechanism.

CRM substitution physically splits a guaranteed loan into a ``__G_<guarantor>``
guaranteed leg and a ``__REM`` retained leg (``engine/crm/guarantees.py``). The
sealed reporting projection (``engine/aggregator/aggregator.py``) then carries,
per leg:
    reporting_class_origin / reporting_approach_origin  = the OBLIGOR's applied
        class / approach (``exposure_class_applied`` / ``approach_applied``) —
        UNIFORM across a loan's legs, including the ``__G_`` leg. This is the
        key BOTH templates sheet on: C 07.00's module docstring says "Sheets
        key the OBLIGOR applied class"; C 08.01/02's says the five dicts "key
        the sealed ``reporting_class_origin`` ... the obligor basis" — same
        rule, each template's own column name for it. A guaranteed leg
        therefore never appears as a ROW on the guarantor's own class sheet —
        it stays on the obligor's ORIGIN sheet, contributing to that sheet's
        outflow column (C 07.00 col 0090 / C 08.01 col 0070).
        NO LONGER TRUE FOR C 07.00 as of task #8 (landed): C 07.00's exposure
        value / RWEA columns (0200/0210/0211/0215/0216/0217/0220/0230/0235 +
        the CCF buckets) now read a per-sheet UNION of the origin and
        post-substitution populations (``c07_basis_origin`` /
        ``c07_basis_post`` in ``reporting/corep/c07.py::_prepare``), so a
        beneficially-substituted leg DOES appear as a row on the guarantor's
        own C 07.00 sheet for those columns — the flow/gross columns still
        key on the origin population alone, so the SENTENCE'S ORIGIN-sheet-
        KEYING claim (which sheet a leg's outflow posts to) remains true; only
        the stronger "never appears as a row at all" reading is now false.
        Kept rather than deleted because the keying half still holds and the
        distinction is easy to miss. C 08.01 is unaffected (task #8 scoped to
        C 07.00 only; see task #9/S3 for the equivalent C 08.01 work).
    reporting_class / reporting_approach = the POST-substitution twin
        (``exposure_class_post_crm`` / ``approach_post_crm``) — the guarantor's
        class on the ``__G_`` leg. This is NOT a sheet key; it feeds the
        cross-template INFLOW, a per-destination-class SCALAR computed by
        ``reporting/corep/crm_substitution.py::substitution_inflows`` — ONE
        function, run once over the WHOLE sealed population (not a
        per-template slice) — that lands on the destination class's Total row
        (C 07.00 col 0100, C 08.01 col 0080). The destination class need NOT
        already have a native origin-basis row on that template — the sheet
        axis is the UNION of "classes with native rows" and "classes
        receiving an inflow", so a class with zero native rows still gets an
        INFLOW-ONLY sheet (Total row 0010/0020 = 0, the inflow column
        populated). Routing to a TEMPLATE reads ``reporting_approach`` (==
        ``approach_post_crm``): the IRB approaches (``foundation_irb`` /
        ``advanced_irb`` / ``slotting``) route to C 08.01, everything else
        (including the output floor's ``standardised_ccr`` relabel) is the SA
        complement and routes to C 07.00 — independent of which population
        the OUTFLOW leg itself sits in, so an IRB-origin obligor with an
        SA-treated guarantor puts the outflow on C 08.01 and the inflow on
        C 07.00 (see S3 below). Every BENEFICIALLY-SUBSTITUTED leg is
        counted (``is_guarantee_beneficial`` True — the guarantor's risk
        weight beats the obligor's own), including one whose guarantor sits
        in the obligor's own class (see S5 below); a DECLINED leg (guarantor
        no better than the obligor — see S6 below) is NOT counted and
        produces no outflow/inflow at all despite keeping a positive
        ``guaranteed_portion`` (Finding 4 /
        ``engine/aggregator/aggregator.py::_beneficial_gate``).

``substitution_inflows`` retired the two former per-template helpers
(``c07.py``'s and ``c08.py``'s own class-inequality-gated inflow builders,
each keyed to its OWN approach-filtered population) precisely because that
split could report an outflow on one template and land its inflow on
NEITHER — the defect S3 isolates — and its class-inequality gate excluded a
same-class migration from both sides at once — the defect S5 isolates. This
is what makes the scenarios below orthogonal rather than redundant:

    ref    | obligor        | guarantor              | outflow | inflow  | what it exercises
    -------|----------------|-------------------------|---------|---------|------------------------------
    S1     | IRB corporate  | IRB institution,        | C 08.01 | C 08.01 | within-template inflow,
           |                | OWN IRB exposure         |         |         | destination class HAS a
           |                |                          |         |         | native row already
    S2     | IRB corporate  | IRB retail_other,        | C 08.01 | C 08.01 | within-template inflow,
           |                | NO own exposure          |         |         | destination class has NO
           |                |                          |         |         | native row — an inflow-only
           |                |                          |         |         | sheet
    S3     | IRB corporate  | SA sovereign (domestic   | C 08.01 | C 07.00 | CROSS-TEMPLATE: the outflow
           |                | CGCB, 0% RW), NO own     |         |         | leg is only ever visible to
           |                | exposure                 |         |         | C 08.01's origin-IRB
           |                |                          |         |         | population, but the SA
           |                |                          |         |         | guarantor's inflow belongs
           |                |                          |         |         | on C 07.00 — crossing the
           |                |                          |         |         | SA/IRB template boundary,
           |                |                          |         |         | landing on an inflow-only
           |                |                          |         |         | C 07.00 sheet
    S4     | SA corporate   | SA institution, OWN SA   | C 07.00 | C 07.00 | within-template inflow,
           |                | exposure                 |         |         | destination class HAS a
           |                |                          |         |         | native row already
    S5     | IRB corporate  | IRB corporate (DIFFERENT | C 08.01 | C 08.01 | SAME-CLASS outflow/inflow:
           |                | counterparty, SAME class)|         |         | Annex II requires an outflow
           |                |                          |         |         | AND an equal inflow on the
           |                |                          |         |         | SAME sheet, netting to no
           |                |                          |         |         | change in col 0090 — the
           |                |                          |         |         | sharpest case, since the
           |                |                          |         |         | destination sheet IS the
           |                |                          |         |         | origin sheet, not merely a
           |                |                          |         |         | sheet that happens to exist
    S6     | slotting       | unrated non-GB sovereign, | none   | none    | DECLINED: guarantor SA RW
           | (specialised_  | NO own exposure          |         |         | (1.00, CQS.UNRATED) is NOT
           | lending,       |                          |         |         | better than the slotting
           | "strong")      |                          |         |         | "strong" weight (0.70), so
           |                |                          |         |         | ``is_guarantee_beneficial``
           |                |                          |         |         | derives False through the
           |                |                          |         |         | real engine path (Art. 213 /
           |                |                          |         |         | 193(1)) — no migration, no
           |                |                          |         |         | outflow, no inflow, despite
           |                |                          |         |         | a positive
           |                |                          |         |         | ``guaranteed_portion``. Also
           |                |                          |         |         | the fixture's only slotting-
           |                |                          |         |         | origin leg (S1-S5 cover only
           |                |                          |         |         | IRB-graded and SA obligors)
           |                |                          |         |         | — reproduces Finding 4's
           |                |                          |         |         | worked example verbatim
           |                |                          |         |         | (10,000,000 "strong" slotting
           |                |                          |         |         | loan, unrated non-GB sovereign
           |                |                          |         |         | guarantor)
    S7     | IRB corporate  | IRB institution (Germany),| C 08.01 | C 08.01 | CROSS-BORDER: obligor GB,
           | (GB)           | NO own exposure          |         |         | guarantor DE — a BENEFICIAL
           |                |                          |         |         | substitution (like S1-S5) whose
           |                |                          |         |         | guarantor is NOT in the
           |                |                          |         |         | obligor's country. Exercises
           |                |                          |         |         | the COUNTRY axis PS1/26 Annex
           |                |                          |         |         | II Section 3.4 para 86/87
           |                |                          |         |         | prescribes for C 09.01/C 09.02
           |                |                          |         |         | (immediate obligor's country
           |                |                          |         |         | for "original exposure
           |                |                          |         |         | pre-conversion factors";
           |                |                          |         |         | ultimate obligor's country —
           |                |                          |         |         | i.e. the guarantor's — for
           |                |                          |         |         | "exposure value"/RWEA once
           |                |                          |         |         | substituted) — orthogonal to
           |                |                          |         |         | S1-S6, which never move
           |                |                          |         |         | country at all (every leg in
           |                |                          |         |         | S1-S6 that ever reports is GB;
           |                |                          |         |         | see CROSS_BORDER_GUARANTEE_
           |                |                          |         |         | DESIGN below). SAME class +
           |                |                          |         |         | template destination as S1
           |                |                          |         |         | (institution/C 08.01) —
           |                |                          |         |         | deliberately: a sovereign
           |                |                          |         |         | guarantor gives a FRESH
           |                |                          |         |         | destination but breaks
           |                |                          |         |         | CRR/B31 regime-uniformity
           |                |                          |         |         | (PS1/26 Art. 147A forces SA
           |                |                          |         |         | for CGCB); institution
           |                |                          |         |         | preserves regime-neutrality
           |                |                          |         |         | at the cost of reusing S1's
           |                |                          |         |         | destination cell
    S8     | slotting       | SA corporate (CQS 1,      | C 08.01 | C 07.00 | BLEND: a "good" (0.90) PF
           | (project_      | 0.20 SA RW), NO own       |         |         | category holding BOTH an
           | finance,       | exposure                 |         |         | unguaranteed leg
           | "good") x2     |                          |         |         | (LN_S8_PLAIN) AND a
           | loans, one     |                          |         |         | BENEFICIALLY-substituted one
           | unguaranteed   |                          |         |         | (LN_S8_GTD) — the shape that
           |                |                          |         |         | exposes C 08.06/CR10's
           |                |                          |         |         | meaningless EAD-weighted
           |                |                          |         |         | blended risk weight (see
           |                |                          |         |         | SLOTTING_BLEND_DESIGN
           |                |                          |         |         | below). CROSS-TEMPLATE like
           |                |                          |         |         | S3: a slotting beneficiary's
           |                |                          |         |         | guarantor is ALWAYS
           |                |                          |         |         | SA-treated (Art. 201(2)'s
           |                |                          |         |         | internal-rating limb never
           |                |                          |         |         | reaches slotting), so the
           |                |                          |         |         | outflow stays on C 08.01 and
           |                |                          |         |         | the inflow crosses to
           |                |                          |         |         | C 07.00[corporate] — a FRESH
           |                |                          |         |         | destination that happens to
           |                |                          |         |         | land on S4's ALREADY-
           |                |                          |         |         | POPULATED native sheet

S1/S4 are the happy-path pair (one IRB, one SA) proving the mechanism works
when the destination class already has a native row. S2 isolates the
"destination class has no native population, same template" case. S3 isolates
the cross-template case: the leg is only ever visible to C 08.01's population
(its origin approach is IRB), so its OUTFLOW cannot be anywhere but C 08.01,
while its guarantor is SA-treated, so its INFLOW belongs on C 07.00 — the two
sides of one migration legitimately live on different templates. S5 isolates
the THIRD, orthogonal case COREP Annex II (both regimes, both templates)
calls out by name — "Inflows and outflows within the same exposure classes
and, where relevant, obligor grades or pools, shall also be considered" —
where ``pre_crm_exposure_class == post_crm_exposure_class_guaranteed`` and a
correct implementation must still recognise BOTH an outflow (col 0070 /
C 07.00 col 0090) and an equal inflow (col 0080 / C 07.00 col 0100) on that
one sheet, netting to no change in the post-substitution total (col 0090 /
col 0110) despite nothing leaving the class. S6 isolates a FOURTH, orthogonal
case none of S1-S5 exercise at all: the guarantee GATE itself. S1-S5 are all
beneficially substituted by construction, so a reporting-layer regression that
deleted the ``is_guarantee_beneficial`` check entirely (migrating every
guarantee regardless of benefit) would move none of their numbers — S6 is the
only scenario that would move if that gate regressed, and it doubles as the
fixture's only slotting-origin leg. S7 isolates a SIXTH, orthogonal case none
of S1-S6 exercise: the COUNTRY basis a beneficial substitution reports under,
independent of the CLASS basis S1-S6 already pin. Its guarantor's class and
template (institution / C 08.01) DELIBERATELY reuse S1's destination cell
(see the OB_S7/GTOR_S7 constant declarations for why: the natural FRESH
choice, a sovereign guarantor, breaks CRR/B31 regime-uniformity), so
``SUBSTITUTION_INFLOW_DESIGN[GUAR_S7]`` and ``[GUAR_S1]`` now share one
destination — the acceptance suite's generic per-scenario inflow check needs
generalising to sum contributions per destination rather than assume exactly
one (flagged to test-writer). S7's entire reason for existing is the country
pair it carries (``CROSS_BORDER_GUARANTEE_DESIGN`` below), which no prior
scenario can express (see the "Why this portfolio" GB-only finding above).
S8 isolates a SEVENTH, orthogonal case: a beneficially-substituted SLOTTING
leg, which none of S1-S7 exercise (S6 is slotting but DECLINED; S1-S5/S7 are
beneficial but never slotting). Its own category ("good") is deliberately
DIFFERENT from S6's ("strong") so the two slotting scenarios stay on
separate C 08.06/CR10 rows — a blend regression on S8 cannot be confused
with a decline-gate regression on S6, keeping both independently
attributable. S8 is a SEPARATE scenario from S7 rather than the same
cross-border leg (see the OB_S8/GTOR_S8 constant declarations for the full
reasoning): a slotting guarantor's benefit is always SA-CQS-based, never
IRB-PD-based, so fusing the two would have forced a redesign of S7's
already-verified mechanics for uncertain benefit. This is the fixture-level
reproduction backing the CRM substitution investigation tracked against
C 07.00/C 08.01/C 08.02/C 08.06/C 09.01/C 09.02/CR10; see the module-level
``NOTE`` below for the specific behaviour observed when this fixture was
built and verified.

NOTE (as observed 2026-08-04, CRR and B31, via a direct
``PipelineOrchestrator`` + ``COREPGenerator``/``Pillar3Generator`` run
against the fixture-builder verification build — re-verify against a live
run before relying on this as a current-state claim): all eight scenarios
land correctly and identically under both regimes, and portfolio-wide gross
(80,000,000, up from 61,500,000 with S8's 18,500,000 added) reconciles
exactly to net across every sheet with zero leakage. Per sheet, Total row
(unchanged from the S1-S7 figures below except ``corporate`` on BOTH
templates and ``specialised_lending``, which S8 perturbs by design):

    c08_01 corporate            : 0020=38,000,000  0040=-12,300,000  0050=-8,800,000  0070=-21,100,000  0080=+5,400,000  0090=22,300,000
    c08_01 institution           : 0020= 4,000,000                                                        0080=+7,500,000  0090=11,500,000   <- S1 (2,000,000) + S7 (5,500,000)
    c08_01 retail_other          : 0020=         0                                                          0080=+3,300,000  0090= 3,300,000   <- S2, inflow-only sheet
    c08_01 specialised_lending   : 0020=28,500,000                                    0050=-7,800,000  0070=-7,800,000                     0090=20,700,000   <- S6 (10,000,000, DECLINED) + S8 (18,500,000)
    c07_00 corporate             : 0010= 8,000,000                                    0060=-2,800,000  0090=-2,800,000  0100=+7,800,000  0110=13,000,000   <- S4 native + S8 inflow
    c07_00 institution           : 0010= 1,500,000                                                                          0100=+2,800,000  0110= 4,300,000
    c07_00 cgcb                  : 0010=         0                                                                          0100=+4,900,000  0110= 4,900,000   <- S3 ONLY

``corporate``'s 0020 rises by exactly DRAWN_S7 (11,000,000 — S7's own ORIGIN
loan, corporate class, same as S1/S2/S3/S5); its col 0050 (the
``"credit_derivative"`` outflow bucket S2/S4/S7 share) rises by exactly
AMOUNT_COVERED_S7 (5,500,000: -3,300,000 -> -8,800,000), while col 0040 (the
``"guarantee"`` bucket) is UNCHANGED — confirming S7's outflow posts to the
correct protection_type column. ``institution``'s col 0080 is the SUM of
GUAR_S1's and GUAR_S7's inflows (2,000,000 + 5,500,000 = 7,500,000) —
DELIBERATELY, since both share this destination (see the OB_S7/GTOR_S7
constant declarations). ``specialised_lending``'s col 0050 (the
``"credit_derivative"`` outflow S8 uses) moves by exactly AMOUNT_COVERED_S8
(-7,800,000: S6 contributes none, being DECLINED); col 0020 rises by
DRAWN_S8_PLAIN + DRAWN_S8_GTD (18,500,000: 10,000,000 -> 28,500,000).
``corporate`` on C 07.00 gains an inflow for the FIRST time (col 0100: 0 ->
7,800,000 = AMOUNT_COVERED_S8, DELIBERATELY landing on S4's already-
populated native sheet — see the OB_S8/GTOR_S8 constant declarations).
Every other sheet (retail_other, C 07.00 institution/cgcb) is BYTE-IDENTICAL
to the S1-S7 figures, confirming S8 perturbs nothing outside its own origin
(specialised_lending) and destination (corporate, C 07.00) sheets.

S6's ``specialised_lending`` ROW (Category 1 "Strong" on C 08.06/CR10, kept
separate from S8's Category 2 "Good") has NO outflow and NO inflow (0070/
0080 both 0) — its net equals its gross with nothing having moved, and
``rwa_final`` sums to 7,000,000 (== 10,000,000 x 0.70, the undiminished
slotting weight) under BOTH regimes identically. The ``cgcb`` sheet's col
0100 stays exactly S3's 4,900,000 — S6's guarantor shares that SAME class,
so a regression that applied the decline anyway would inflate this
EXISTING, already-asserted cell to 9,400,000 rather than create a new one,
which is what makes S6 the sharpest possible pin on the gate (see
``DECLINED_GUARANTEE_DESIGN`` below).

S7's guaranteed leg (``CSUB-LN-S7__G_CSUB-CP-GTOR-S7``) confirmed
``is_guarantee_beneficial = True`` under BOTH regimes: ``guarantor_rw``
(the substituted institution risk weight, driven by ``PD_GTOR_S7`` = 0.0015)
came out at 0.62018 (CRR) / 0.52007 (B31), comfortably below
``risk_weight_irb_original`` (the obligor's own corporate risk weight,
driven by ``PD_OB_S7`` = 0.0075) at 1.20522 (CRR) / 1.01067 (B31) — the same
margin direction under both regimes despite the absolute risk weights
differing (as they do for every other scenario in this fixture). ``cp_
country_code`` stayed "GB" on BOTH the ``__G_`` and ``__REM`` legs in this
verification run (the CURRENT single-basis behaviour — see
``CROSS_BORDER_GUARANTEE_DESIGN`` for the DESIGN intent once C 09.01/C 09.02
read ``guarantor_country_code`` instead, on the ``__G_`` leg only).

S8's THREE legs confirmed the per-leg mechanics ``SLOTTING_BLEND_DESIGN``
records, identically under BOTH regimes: LN_S8_PLAIN reports
``risk_weight=0.90``, ``rwa_final=5,850,000`` (6,500,000 x 0.90);
LN_S8_GTD's ``__REM`` leg reports the SAME 0.90, ``rwa_final=3,780,000``
(4,200,000 x 0.90) — the never-guaranteed remainder stays on the category's
own basis; LN_S8_GTD's ``__G_`` leg confirmed ``is_guarantee_beneficial =
True`` with ``guarantor_rw=0.20`` (CQS_GTOR_S8=1), ``risk_weight=0.20``,
``rwa_final=1,560,000`` (7,800,000 x 0.20), ``exposure_class_post_crm=
"corporate"`` (routing the inflow to C 07.00) while
``reporting_approach_origin`` stays ``"slotting"`` (keeping the OUTFLOW on
C 08.01) — the S3-shaped cross-template split, confirmed on a slotting
beneficiary for the first time. The DEFECT itself reproduces EXACTLY as the
brief's prototype described, confirmed on C 08.06's own "good" row (Category
2) and Pillar 3 CR10's own row: C 08.06 col 0070 (risk weight) reports
0.604865 — EXACTLY ``category_total_rwa_correct_basis`` /
``category_total_ead`` (11,190,000 / 18,500,000, as ``SLOTTING_BLEND_DESIGN``
predicts) — a number with no regulatory meaning, sitting inside neither the
0.90 nor the 0.20 band; CR10's own row prints a FIXED col c = 90.0 (the
category's nominal weight) directly beside col e = 11,190,000 over col d =
18,500,000, implying the SAME 60.49% — the exact "fixed 70% next to an
implied 36.67%" incoherence the brief's prototype reports, reproduced here
at S8's own numbers. NUANCE the brief's summary does not distinguish: C
08.06's col 0080 (RWA) already reports the CORRECT total, 11,190,000 — the
sum of each leg's own (EAD x its own risk weight); it is ONLY the col 0070
"risk weight" DISPLAY column, derived from that correct RWA divided by the
category's total EAD, that is meaningless. Capital (RWA) is right; the
disclosed ratio next to it is not — the same character of defect as Finding
4's ``_beneficial_gate`` (S6): a pure disclosure defect, not a capital one,
which is exactly why neither shows up as a capital-conservation failure and
both need a dedicated fixture leg to surface at all. S6's OWN "strong" row
(Category 1) stays clean (col 0070 = 0.70, unblended) throughout, confirming
S8's category is fully isolated and the defect is attributable to S8 alone.

S5's isolated ``corporate`` sheet Total row (S5 alone, no other scenario on
the sheet) reports ``0020=9,000,000 / 0040=-5,400,000 / 0070=-5,400,000 /
0080=5,400,000 / 0090=9,000,000`` (== 0020, i.e. no change, exactly as
Annex II requires), matching ``v1663_m`` ({c0070} = {c0040}+{c0050}+{c0060})
and the corrected col 0090 waterfall.

Every guarantee is PARTIAL cover (never 100%), so a retained ``__REM`` leg
genuinely coexists with the ``__G_`` leg on all eight scenarios, and every
guaranteed amount is a distinct round GBP figure so any template cell is
traceable to exactly one leg — including S6, whose decline means that figure
should appear on NO outflow/inflow cell anywhere; its only footprint is the
undiminished gross total on its own native sheet. ``protection_type`` covers
both values Annex II splits (C 08.01 cols 0040/0050): S1/S3/S5/S6 are
``"guarantee"``, S2/S4/S7/S8 are ``"credit_derivative"``.

No CRR/Basel 3.1 regime divergence is exercised here (deliberately, unlike
``reporting_irb_classes_portfolio.py``'s sovereign-class carve-out) — every
obligor keeps the same approach under both regimes, so the sheet-routing
answer is identical for both; the CRR/B31 expected-sheet dicts below are
provided as a matched pair purely for parity with the sibling fixture's
convention and because a future regime-conditioned defect fix could make them
diverge. S7's PD gap (0.0075 obligor vs 0.0015 guarantor, a comfortable ~5x
margin) is deliberately wide enough that ``is_guarantee_beneficial`` derives
True under both regimes' IRB risk-weight formulas without needing to tune the
margin per regime — confirmed empirically (see the dated NOTE below). S8's
guarantor CQS (1 -> 0.20 SA RW under BOTH ``corporate_cqs_rw`` (CRR) and
``b31_corporate_risk_weights`` (PS1/26) — comfortably below the "good"
category's 0.90) is similarly regime-uniform BY CONSTRUCTION, unlike the
REJECTED sovereign design for S7, which was NOT (see the OB_S7/GTOR_S7
constant declarations) — confirmed empirically here too (see the dated NOTE).

References:
- CRR Art. 235 / PS1/26 Art. 235: SA risk-weight substitution (RWSM).
- CRR Art. 161 / CRE22.70-85: IRB parameter substitution (PSM).
- CRR Art. 153(5) / PS1/26 Art. 153(5): specialised-lending slotting
  categories and risk weights (S6's and S8's obligors — Table A "strong"
  0.70 / "good" 0.90, remaining maturity >= 2.5y, non-HVCRE, identical
  entries under both regimes in ``rulebook/packs/{crr,b31}.py::
  slotting_rw_base``).
- CRR Art. 114(4)/(7) / Art. 235(3): the domestic-currency CGCB 0% RW
  extension to a centrally-guaranteed exposure (S3's guarantor); S6's
  guarantor is a non-GB sovereign specifically so this extension does NOT
  apply and the unrated CQS fallback (1.00) governs instead.
- CRR Art. 213 / Art. 193(1) / Art. 113(3): a guarantee must never raise
  capital — the basis for declining a non-beneficial guarantee (S6). See
  task #13 (S0-revise) for the citation-basis correction from Art. 213 alone
  to Art. 193(1) (mandatory, per-exposure) + Art. 113(3) (the permissive
  amendment hook Art. 235(1) is framed against).
- CRR Art. 201: eligible-guarantor eligibility gate; Art. 201(1)(g)/(2)'s
  rating-based eligibility test applies only to a CORPORATE guarantor
  (``_assign_guarantor_approach``'s ``is_corporate_guarantor`` check) — an
  "institution" guarantor (S1, S4, S7) is governed by other Art. 201 limbs
  and is not gated here, same as GTOR_S1/GTOR_S4. GTOR_S8 IS a corporate
  guarantor and DOES trip this gate, satisfied by its ECAI CQS rating (Art.
  201(1)(g) — an internal PD would not satisfy it here, since Art. 201(2)'s
  internal-rating limb never reaches a slotting beneficiary; see the
  OB_S8/GTOR_S8 constant declarations).
- PRA PS1/26 Art. 147A: mandates SA-only treatment for sovereign / quasi-
  sovereign counterparties at a 0% SA risk weight (CGCB, sovereign-treated
  RGLAs/PSEs, MDBs, international orgs) REGARDLESS of internal rating —
  the reason S7's guarantor is "institution", not "sovereign" (see the
  OB_S7/GTOR_S7 constant declarations for the empirical reproduction).
- COREP Annex II, C 07.00 / C 08.01 / C 08.02: the outflow/inflow columns,
  including the same-exposure-class inflow/outflow requirement (S5).
- PRA PS1/26 Annex II Section 3.4 para 86/87 (Regulation (EU) 2021/451,
  Annex II, C 09.01/C 09.02 instructions worded identically): the
  geographical-breakdown column basis — immediate obligor's country for
  "original exposure pre-conversion factors", ultimate obligor's country for
  "exposure value"/RWEA, migrating with a beneficial substitution exactly as
  exposure class does (S7; not yet implemented — see task "S2a: C 09.01
  exposure-value / RWEA columns to the post-substitution basis" and
  ``CROSS_BORDER_GUARANTEE_DESIGN`` below).
- engine/crm/guarantees.py: the ``__G_`` / ``__REM`` physical split.
- engine/aggregator/aggregator.py: ``_add_reporting_projection`` (the sealed
  ``reporting_class`` / ``reporting_class_origin`` twins) and
  ``_beneficial_gate`` (the S6 decline gate this fixture pins — Finding 4).
- reporting/corep/c07.py, reporting/corep/c08.py: module docstrings on sheet
  keying (each reads its per-class rows off ``reporting_class_origin``, the
  obligor basis).
- reporting/corep/crm_substitution.py: ``substitution_inflows`` — the single
  cross-template inflow router keyed on ``reporting_approach`` (S3), which
  counts every BENEFICIALLY-SUBSTITUTED leg (not merely every leg with a
  positive ``guaranteed_portion`` — S6 has one and is excluded) including
  same-class ones (S5); ``crm_waterfall`` / ``waterfall_refs`` — the
  C 08.01/02 col 0090 identity this fixture also exercises (0090 = 0020 -
  0070 + 0080 over positive magnitudes, col 0070 as the single whole-outflow
  subtotal).
- reporting/corep/c09.py: ``_country_frames`` — the CURRENT single-basis
  per-country split, keyed on ``cp_country_code`` for every column (S7's gap;
  see ``CROSS_BORDER_GUARANTEE_DESIGN`` above). ``cp_country_code`` is joined
  onto every exposure row by its OWN ``counterparty_reference``
  (``engine/classify/attributes.py::add_counterparty_attributes``),
  which the CRM splitter never reassigns on the ``__G_`` leg — the raw input
  the immediate-obligor basis needs is already correct today.
  ``guarantor_country_code`` — the raw input the ultimate-obligor basis will
  need — is ALREADY sealed separately, joined by ``guarantor_reference``
  (``engine/crm/guarantees.py::_join_guarantor_counterparty``); only
  C 09.01/C 09.02's column bindings do not yet read it.
- COREP C 08.06 / Pillar 3 CR10: the specialised-lending slotting grid
  (task "S4: C 08.06 + CR10 slotting grid and lineage correction" —
  S8's gap; see ``SLOTTING_BLEND_DESIGN`` above). C 08.06's col 0070 /
  CR10's implied col d/e ratio currently derive a single EAD-weighted-
  average "risk weight" per category, which is meaningless whenever a
  category mixes unguaranteed and beneficially-substituted legs (confirmed
  empirically — see the dated NOTE); C 08.06's col 0080 (RWA total) is
  UNAFFECTED — it already sums each leg's own correctly-weighted RWA, so
  this is a disclosure defect, not a capital one.
- engine/slotting/transforms.py: ``apply_guarantee_substitution`` — the
  slotting RWSM consumer (Art. 235(1)), reusing the SAME shared SA
  substitution step (and therefore the same beneficial gate) the
  ``_assign_guarantor_approach`` SA branch runs; the reason a slotting
  guarantor is ALWAYS SA-treated (S8's guarantor mechanism, vs S1-S5/S7's
  IRB-PD-based one).
"""

from __future__ import annotations

from datetime import date

import polars as pl

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import (
    COUNTERPARTY_SCHEMA,
    GUARANTEE_SCHEMA,
    LOAN_SCHEMA,
    RATINGS_SCHEMA,
    SPECIALISED_LENDING_SCHEMA,
)
from tests.fixtures.irb_test_helpers import create_full_irb_model_permissions
from tests.fixtures.raw_bundle import make_raw_bundle

# ---------------------------------------------------------------------------
# Scenario constants — the single source of truth for test assertions.
# ---------------------------------------------------------------------------

#: Must match ``create_full_irb_model_permissions`` (F-IRB + A-IRB + slotting
#: for every class), or no row routes IRB at all.
_MODEL_ID: str = "TEST_FULL_IRB"

# -- S1: IRB obligor, IRB guarantor WITH its own IRB exposure ---------------
OB_S1: str = "CSUB-CP-OB-S1"
GTOR_S1: str = "CSUB-CP-GTOR-S1"
LN_S1: str = "CSUB-LN-S1"
LN_S1_GTOR_OWN: str = "CSUB-LN-S1-GTOR-OWN"
GUAR_S1: str = "CSUB-GUAR-S1"

# -- S2: IRB obligor, IRB guarantor with NO other IRB exposure in this book -
OB_S2: str = "CSUB-CP-OB-S2"
GTOR_S2: str = "CSUB-CP-GTOR-S2"
LN_S2: str = "CSUB-LN-S2"
GUAR_S2: str = "CSUB-GUAR-S2"

# -- S3: IRB obligor, SA (domestic CGCB) guarantor, no own exposure ---------
OB_S3: str = "CSUB-CP-OB-S3"
GTOR_S3: str = "CSUB-CP-GTOR-S3"
LN_S3: str = "CSUB-LN-S3"
GUAR_S3: str = "CSUB-GUAR-S3"

# -- S4: SA obligor, SA guarantor WITH its own SA exposure -------------------
OB_S4: str = "CSUB-CP-OB-S4"
GTOR_S4: str = "CSUB-CP-GTOR-S4"
LN_S4: str = "CSUB-LN-S4"
LN_S4_GTOR_OWN: str = "CSUB-LN-S4-GTOR-OWN"
GUAR_S4: str = "CSUB-GUAR-S4"

# -- S5: IRB obligor, IRB guarantor in the SAME exposure class (corporate) --
OB_S5: str = "CSUB-CP-OB-S5"
GTOR_S5: str = "CSUB-CP-GTOR-S5"
LN_S5: str = "CSUB-LN-S5"
GUAR_S5: str = "CSUB-GUAR-S5"

# -- S6: slotting obligor, unrated non-GB sovereign guarantor -- DECLINED ---
# (guarantor SA RW >= the slotting weight, so ``is_guarantee_beneficial``
# derives False through the real engine path; no own exposure needed since
# a declined guarantee never creates an inflow to pre-establish a sheet for).
OB_S6: str = "CSUB-CP-OB-S6"
GTOR_S6: str = "CSUB-CP-GTOR-S6"
LN_S6: str = "CSUB-LN-S6"
GUAR_S6: str = "CSUB-GUAR-S6"

# -- S7: IRB obligor (GB), IRB institution guarantor (DE) -- CROSS-BORDER ---
# Beneficially substituted (derives True through the same real engine path as
# S1 — see PD_OB_S7 / PD_GTOR_S7 below), but with the guarantor incorporated
# in a DIFFERENT country from the obligor. PRA PS1/26 Annex II Section 3.4
# para 87 (C 09.01/C 09.02 geographical breakdown): "original exposure
# pre-conversion factors" keys the IMMEDIATE obligor's country of residence
# (unaffected by substitution), while "exposure value" and "Risk-weighted
# exposure amounts" key the ULTIMATE obligor's country once a guarantee
# substitutes. This portfolio has never exercised that column-level country
# basis before: every prior BENEFICIAL guarantor (S1-S5) shares the
# obligor's GB country, and S6's non-GB (US) guarantor is DECLINED, so its
# country never reaches any exposure-bearing leg at all (GTOR_S6 has no own
# loan, and a declined guarantee keeps the covered leg on the obligor's own
# basis end to end — see DECLINED_GUARANTEE_DESIGN). Confirmed by direct
# inspection of every counterparty row below: GB is, in effect, the ONLY
# country any leg in S1-S6 ever reports. S7 closes that gap. The obligor
# deliberately STAYS on the fixture-wide GB default, and the guarantor is
# "institution" — the SAME entity_type as GTOR_S1, deliberately, changing
# EXACTLY ONE thing versus S1's already-proven mechanics (the same "change
# exactly one thing" discipline S6 used for the decline gate): its country.
# A "sovereign" guarantor (central_govt_central_bank) was tried first and
# REJECTED, empirically, not merely on paper: PRA PS1/26 Art. 147A mandates
# SA-only treatment for CGCB (Art. 147(3) sovereign/quasi-sovereign at 0% SA
# RW) REGARDLESS of the guarantor's internal rating (see
# ``IRBPermissions.full_irb_b31`` — "Sovereign / quasi-sovereign with 0% SA
# risk weight: SA only"). A verification run confirmed a sovereign S7 landed
# on C 08.01[central_govt_central_bank] under CRR (guarantor treated IRB) but
# C 07.00[central_govt_central_bank] under B31 (guarantor forced SA,
# ``guarantor_rw`` = 1.0, the CQS.UNRATED SA fallback) — a genuine
# CRR/Basel 3.1 regime divergence this portfolio's own docstring says it does
# NOT exercise, and one ``SUBSTITUTION_INFLOW_DESIGN`` (a single, regime-
# independent dict) cannot express since ``destination_template`` would need
# to differ by regime for the SAME entry. "institution" carries no such
# restriction under B31 (``full_irb_b31``: "Institution ... F-IRB only (no
# A-IRB)" — still IRB-eligible, merely restricted to F-IRB, and
# ``create_full_irb_model_permissions`` grants F-IRB regardless), so it lands
# on the SAME (class, template) — C 08.01[institution] — under BOTH regimes,
# preserving the fixture-wide regime-neutrality invariant. The trade-off:
# this REUSES GTOR_S1's destination (C 08.01[institution]), which is the
# SAME reuse-an-existing-cell principle S6 applied to the class axis, now
# applied a second time — deliberately, since no B31-regime-safe entity_type
# reachable from a plain counterparty was found with a genuinely FRESH
# (class, template) pair (every one either shares an existing destination, as
# institution/corporate/retail_other all do, or breaks regime-uniformity, as
# sovereign/CGCB does — see CROSS_BORDER_GUARANTEE_DESIGN below).
# ``SUBSTITUTION_INFLOW_DESIGN[GUAR_S7]`` records this combined cell; the
# acceptance suite's generic per-scenario check needs generalising to SUM
# contributions per (class, template) destination rather than assume exactly
# one — flagged to test-writer, not fixed here (fixture-builder owns
# ``tests/fixtures/`` only).
OB_S7: str = "CSUB-CP-OB-S7"
GTOR_S7: str = "CSUB-CP-GTOR-S7"
LN_S7: str = "CSUB-LN-S7"
GUAR_S7: str = "CSUB-GUAR-S7"

# -- S8: slotting "good" obligor with BOTH an unguaranteed leg AND a --------
# -- BENEFICIALLY-SUBSTITUTED leg in the SAME category ----------------------
# S6 is the fixture's only slotting-origin leg so far, and it is DECLINED —
# so no beneficially-substituted slotting leg exists anywhere, and C 08.06 /
# Pillar 3 CR10's per-category risk-weight columns (``v09782_m`` /
# ``v09783_m`` and their B31 twins) are never even reached. Worse: a
# category containing legs on BOTH bases (unguaranteed at the category's own
# weight, substituted at the guarantor's) produces a MEANINGLESS EAD-weighted
# BLENDED risk weight that sits inside the category's own band and looks
# like a plausible number rather than an obviously wrong one — measured on a
# production-shaped prototype (PF "strong", 5,000,000 unguaranteed @ 70% +
# 10,000,000 substituted to 20%): C 08.06 reports a blended 0.366667 next to
# a FIXED-display 70.0 on CR10, with CR10's own d/e columns implying 36.67%
# — incoherent, and a SINGLE fully-guaranteed leg would not expose it (a
# clean 20% merely looks wrong, not incoherent). It takes TWO legs in one
# category — one substituted, one not — and that is what a real slotting
# book looks like. S8 reproduces this shape as its own, ISOLATED category
# (CRR/PS1/26 Art. 153(5) Table A "good", 0.90, remaining maturity >= 2.5y,
# non-HVCRE — deliberately NOT S6's "strong" (0.70): the two scenarios stay
# on separate rows so a blend regression on one cannot be confused with a
# decline-gate regression on the other, keeping S6's gate-pin and S8's
# blend-pin independently attributable). ``specialised_lending`` is a
# per-COUNTERPARTY join (one row, no ``loan_reference`` column — see
# ``SPECIALISED_LENDING_SCHEMA``), so ONE obligor (OB_S8) with TWO loans
# (LN_S8_PLAIN, unguaranteed; LN_S8_GTD, guaranteed) automatically shares one
# category — no second obligor needed.
#
# GTOR_S8 is "corporate" (not "institution"/"sovereign"): a slotting
# beneficiary is EXCLUDED from the IRB internal-rating eligibility limb
# (``_assign_guarantor_approach``'s ``beneficiary_is_irb`` check only admits
# FIRB/AIRB, never slotting — "SLOTTING beneficiaries are deliberately
# excluded, so the Art. 201(2) internal-rating eligibility limb does not
# reach them either"), so a slotting guarantor is ALWAYS treated SA
# regardless of any internal PD — a DIFFERENT mechanism from S1-S5/S7's IRB
# PD-based substitution, and the reason S8 is a separate scenario from S7
# rather than the same leg (see the merge-vs-separate note below). A
# "corporate" guarantor DOES trip the Art. 201(1)(g)/(2) eligibility gate
# (``is_corporate_guarantor``), so GTOR_S8 carries an ECAI CQS rating (CQS 1
# -> 0.20 SA RW under BOTH regimes — ``corporate_cqs_rw`` / PS1/26 Table 6
# CQS1 — comfortably below the "good" category's 0.90) to satisfy it AND to
# make ``is_guarantee_beneficial`` derive True through the real engine path
# (``engine/slotting/transforms.py::apply_guarantee_substitution`` — the
# SAME shared SA substitution step S6's decline reproduces, just with the
# opposite outcome). "corporate" is ALSO a FRESH C 07.00 destination (S3 ->
# central_govt_central_bank, S4 -> institution; corporate is unclaimed) that
# happens to land on an ALREADY-POPULATED, ALREADY-ASSERTED native sheet —
# C 07.00[corporate]'s Total row already carries S4's OWN obligor gross/
# outflow numbers — so a basis regression here inflates an EXISTING cell
# rather than populating an empty one, the same "make it loud" principle S6
# applied to the class axis, achieved here WITHOUT colliding with any
# existing ``SUBSTITUTION_INFLOW_DESIGN`` entry's exact-amount assertion
# (nothing currently claims C 07.00[corporate] as a destination).
#
# MERGE-VS-SEPARATE (asked explicitly): kept as its OWN scenario, not fused
# into S7's cross-border leg, for three reasons. (1) Mechanism mismatch: S7's
# guarantor benefit is IRB-PD-based (mirrors S1); a slotting guarantor's
# benefit is ALWAYS SA-CQS-based (see above) — fusing them would force S7's
# proven, already-regime-verified mechanics to change. (2) The blend needs a
# SECOND, unguaranteed leg regardless of which obligor carries the
# cross-border leg, so "one leg, two axes" was never fully available — at
# least one extra loan is unavoidable either way. (3) Attribution: S7 is
# fully verified and reported complete; redesigning it around a second axis
# risks re-breaking a solid, already-reviewed result for uncertain benefit,
# whereas a fresh S8 stays a pure, minimal-diff extension of S6's proven
# slotting-benefit mechanism (same gate, opposite outcome) — mirroring the
# "change exactly one thing" discipline S6 (vs S3) and S7 (vs S1) already
# established twice.
OB_S8: str = "CSUB-CP-OB-S8"
GTOR_S8: str = "CSUB-CP-GTOR-S8"
LN_S8_PLAIN: str = "CSUB-LN-S8-PLAIN"
LN_S8_GTD: str = "CSUB-LN-S8-GTD"
GUAR_S8: str = "CSUB-GUAR-S8"

#: Drawn amounts (GBP), each a distinct round figure. EAD = drawn_amount (no
#: facility / CCF machinery involved — every row is a plain drawn term loan).
DRAWN_S1: float = 5_000_000.0
DRAWN_S1_GTOR_OWN: float = 4_000_000.0
DRAWN_S2: float = 6_000_000.0
DRAWN_S3: float = 7_000_000.0
DRAWN_S4: float = 8_000_000.0
DRAWN_S4_GTOR_OWN: float = 1_500_000.0
DRAWN_S5: float = 9_000_000.0
#: Matches Finding 4's worked reproduction verbatim (see
#: ``engine/aggregator/aggregator.py::_beneficial_gate``) — a 10,000,000
#: project-finance "strong" slotting loan.
DRAWN_S6: float = 10_000_000.0
DRAWN_S7: float = 11_000_000.0
#: S8's PLAIN (unguaranteed) leg and GTD (guaranteed) leg, same category.
DRAWN_S8_PLAIN: float = 6_500_000.0
DRAWN_S8_GTD: float = 12_000_000.0

#: Guarantee coverage — always PARTIAL, so a retained ``__REM`` leg coexists
#: with the ``__G_`` leg on every scenario, including the DECLINED S6 (a
#: decline is not the same thing as no cover — the protection exists, the
#: engine just must not apply it). Distinct percentages per scenario.
PCT_COVERED_S1: float = 0.40
PCT_COVERED_S2: float = 0.55
PCT_COVERED_S3: float = 0.70
PCT_COVERED_S4: float = 0.35
PCT_COVERED_S5: float = 0.60
PCT_COVERED_S6: float = 0.45
PCT_COVERED_S7: float = 0.50
PCT_COVERED_S8: float = 0.65

#: amount_covered = drawn_amount * pct_covered, rounded to a clean GBP figure.
AMOUNT_COVERED_S1: float = DRAWN_S1 * PCT_COVERED_S1  # 2,000,000
AMOUNT_COVERED_S2: float = DRAWN_S2 * PCT_COVERED_S2  # 3,300,000
AMOUNT_COVERED_S3: float = DRAWN_S3 * PCT_COVERED_S3  # 4,900,000
AMOUNT_COVERED_S4: float = DRAWN_S4 * PCT_COVERED_S4  # 2,800,000
AMOUNT_COVERED_S5: float = DRAWN_S5 * PCT_COVERED_S5  # 5,400,000
#: S6 is DECLINED, so this figure should appear on NO outflow/inflow cell —
#: see ``DECLINED_GUARANTEE_DESIGN`` below.
AMOUNT_COVERED_S6: float = DRAWN_S6 * PCT_COVERED_S6  # 4,500,000
AMOUNT_COVERED_S7: float = DRAWN_S7 * PCT_COVERED_S7  # 5,500,000
AMOUNT_COVERED_S8: float = DRAWN_S8_GTD * PCT_COVERED_S8  # 7,800,000

#: Internal PDs (IRB legs only). Each guarantor with an internal PD is a
#: deliberately IRB-routing signal — see ``_assign_guarantor_approach``
#: (guarantor treated IRB iff the beneficiary is IRB, the guarantor's class
#: has IRB model permission, AND the guarantor carries an internal PD).
PD_OB_S1: float = 0.0050
PD_GTOR_S1: float = 0.0030
PD_OB_S2: float = 0.0060
PD_GTOR_S2: float = 0.0200
PD_OB_S3: float = 0.0080
PD_OB_S5: float = 0.0090
#: GTOR_S5 is a DIFFERENT corporate counterparty from OB_S5, not the same one
#: — the SAME-CLASS defect requires two distinct obligors of one class, not a
#: self-guarantee.
PD_GTOR_S5: float = 0.0045
PD_OB_S7: float = 0.0075
#: The institution guarantor's internal PD, well below OB_S7's own (a ~0.2x
#: ratio, a sharper margin than S1's ~0.6x, chosen comfortable rather than
#: borderline): ``is_guarantee_beneficial`` derives True through the real
#: engine path (``guarantor_rw < risk_weight_irb_original`` —
#: ``engine/irb/guarantee.py``) with no ambiguity — confirmed under BOTH
#: regimes (see the dated NOTE below).
PD_GTOR_S7: float = 0.0015

#: S7's cross-border pair. The obligor stays on the fixture-wide GB default —
#: isolating country as the ONLY new variable relative to S1's proven
#: mechanics (see the OB_S7/GTOR_S7 comment above). The guarantor sits in
#: Germany: distinct from GB (the obligor, and every other BENEFICIAL
#: guarantor in this fixture) and from US (S6's guarantor — but that
#: guarantee is DECLINED and never reaches an exposure-bearing leg, so it
#: cannot be confused with a genuine cross-border substitution).
COUNTRY_OB_S7: str = "GB"
COUNTRY_GTOR_S7: str = "DE"

#: External CQS assignments (SA / non-IRB-rated legs).
#: CQS 1 sovereign -> 0% RW under both regimes; also triggers the Art.
#: 114(4)/(7) domestic-CGCB 0% short-circuit for GTOR_S3 (GB / GBP), which
#: forces ``guarantor_approach="sa"`` unconditionally (CRR Art. 235(3)).
CQS_GTOR_S3: int = 1
#: CQS 2 institution -> a defined, non-zero SA risk weight.
CQS_GTOR_S4: int = 2
#: GTOR_S6 carries NO rating row at all (unrated) — the ``cgcb_risk_weights``
#: pack table's ``CQS.UNRATED`` entry (1.00, both regimes) then governs, well
#: above the 0.70 "strong" slotting weight it is compared against. Its
#: country_code is deliberately non-GB so the Art. 114(4)/(7) domestic-CGCB
#: 0% short-circuit (S3's path) does NOT apply here — this is the plain
#: unrated-sovereign fallback, not the domestic carve-out.
#: CQS 1 corporate -> 0.20 SA RW under both regimes (``corporate_cqs_rw`` /
#: PS1/26 Table 6) — comfortably below the "good" slotting weight (0.90) it
#: is compared against, so GTOR_S8's substitution derives beneficial with no
#: ambiguity; also satisfies the Art. 201(1)(g)/(2) corporate-guarantor
#: eligibility gate (an ECAI rating makes it eligible outright).
CQS_GTOR_S8: int = 1

#: S6's obligor slotting category (CRR/PS1/26 Art. 153(5) Table A, remaining
#: maturity >= 2.5y, non-HVCRE): "strong" -> 0.70 under BOTH regimes
#: (identical entries in ``rulebook/packs/{crr,b31}.py::slotting_rw_base``).
SLOTTING_CATEGORY_S6: str = "strong"
#: S8's obligor slotting category — deliberately DIFFERENT from S6's
#: ("good" -> 0.90 under both regimes, vs S6's "strong" -> 0.70) so the two
#: scenarios sit on separate C 08.06 / CR10 rows and stay independently
#: attributable (see the OB_S8/GTOR_S8 constant declarations above).
SLOTTING_CATEGORY_S8: str = "good"

_VALUE_DATE: date = date(2020, 1, 1)
#: Beyond both reporting dates under test (CRR 2025-06-30, B31 2027-06-30).
_MATURITY: date = date(2033, 12, 31)
#: Guarantee maturity matches the loan exactly — no Art. 239(3) mismatch haircut.
_GUARANTEE_MATURITY: date = _MATURITY
#: Comfortably >= 1y — Art. 237(2)(a) original-maturity eligibility satisfied.
_ORIGINAL_MATURITY_YEARS: float = 10.0

#: Above the SME revenue ceiling for every corporate counterparty (obligors),
#: so the SME supporting factor never perturbs a substitution cell under test.
_LARGE_CORPORATE_REVENUE: float = 400_000_000.0

#: Per-loan (BASE reference) expected ORIGIN sheet — (template, class) — under
#: EACH regime. This is where EVERY leg of that loan (whole / ``__G_`` /
#: ``__REM``) physically sits: ``reporting_class_origin`` /
#: ``reporting_approach_origin`` are uniform across a loan's legs and never
#: reflect the guarantor. Consumed by the fixture-integrity test: a
#: mis-classified obligor silently moves a leg off its expected sheet without
#: any gate turning red. "c08_01" / "c07" name the template; the class is the
#: sheet key within it.
LOAN_EXPECTED_ORIGIN_SHEET_CRR: dict[str, tuple[str, str]] = {
    LN_S1: ("c08_01", "corporate"),
    LN_S1_GTOR_OWN: ("c08_01", "institution"),
    LN_S2: ("c08_01", "corporate"),
    LN_S3: ("c08_01", "corporate"),
    LN_S4: ("c07", "corporate"),
    LN_S4_GTOR_OWN: ("c07", "institution"),
    LN_S5: ("c08_01", "corporate"),
    # Slotting is its OWN IRB exposure class (ExposureClass.SPECIALISED_LENDING),
    # not merged into "corporate" — that Art. 112 Table A2 merge is a C 07.00
    # SA-side rule only (``c07.py::_merge_specialised_lending``); C 08.01 keys
    # slotting-origin legs on the raw class ("C 08.01 does NOT exclude
    # slotting" — ``c08.py::c08_01_plans``). No S1-S5 loan reaches this sheet.
    LN_S6: ("c08_01", "specialised_lending"),
    LN_S7: ("c08_01", "corporate"),
    LN_S8_PLAIN: ("c08_01", "specialised_lending"),
    LN_S8_GTD: ("c08_01", "specialised_lending"),
}
#: No regime divergence is exercised in this portfolio (see module docstring)
#: — identical to the CRR map.
LOAN_EXPECTED_ORIGIN_SHEET_B31: dict[str, tuple[str, str]] = dict(LOAN_EXPECTED_ORIGIN_SHEET_CRR)

#: Per-scenario substitution-inflow expectations, keyed by the guarantee
#: reference. ``destination_class`` is ``post_crm_exposure_class_guaranteed``
#: — the class the guaranteed portion is regulatory-attributed to
#: (CRR Art. 235). ``destination_template`` is which TEMPLATE the inflow
#: scalar (``reporting/corep/crm_substitution.py::substitution_inflows``,
#: grouped by ``post_crm_exposure_class_guaranteed`` and routed by
#: ``reporting_approach``) lands on — S3's guarantor is SA, so its inflow
#: belongs on C 07.00 even though the OUTFLOW leg itself is only ever visible
#: to C 08.01's origin-IRB population (its origin approach is IRB) — the two
#: sides of one migration can sit on different templates.
#: ``destination_has_native_population`` records whether the destination
#: class ALREADY has an origin-basis row on that template independent of any
#: inflow — S1/S4/S5 True, S2/S3 False. This is NOT the same question as
#: "does a sheet get emitted for it": the sheet axis is the UNION of "classes
#: with native rows" and "classes receiving an inflow", so S2's
#: ``retail_other`` C 08.01 sheet and S3's ``central_govt_central_bank``
#: C 07.00 sheet are both emitted as INFLOW-ONLY sheets (row 0010 total = 0,
#: nothing native, the inflow scalar populated) — see the dated NOTE in the
#: module docstring. ``same_class`` is True only for S5, where
#: ``destination_class`` equals the ORIGIN class (``LOAN_EXPECTED_ORIGIN_
#: SHEET_CRR[LN_S5][1]``) — i.e. the "destination sheet" is not a different
#: sheet at all, it is the SAME sheet the outflow leg already sits on, so a
#: correct implementation nets col 0090 back to the un-guaranteed total.
#: fixture-builder does not assert the engine's CURRENT behaviour here (that
#: is test-writer's job over a live pipeline run) — this dict only records
#: the fixture's DESIGN intent (confirmed to match observed behaviour in the
#: fixture-builder verification run — see the dated NOTE above).
#:
#: GUAR_S1 and GUAR_S7 DELIBERATELY share one destination
#: (institution/C 08.01) — see the OB_S7/GTOR_S7 constant declarations for
#: why (a sovereign guarantor would give S7 a fresh destination but breaks
#: CRR/B31 regime-uniformity). ``TestPerScenarioInflowLandsOnce``
#: (``test_crm_substitution_flows.py``), which currently asserts the shared
#: sheet's inflow column against ONE scenario's ``guaranteed_amount`` in
#: isolation, needs generalising to sum contributions per (destination_class,
#: destination_template) pair before both entries can pass simultaneously —
#: flagged to test-writer, not fixed here.
SUBSTITUTION_INFLOW_DESIGN: dict[str, dict[str, object]] = {
    GUAR_S1: {
        "loan_reference": LN_S1,
        "guarantor_reference": GTOR_S1,
        "guaranteed_amount": AMOUNT_COVERED_S1,
        "destination_class": "institution",
        "destination_template": "c08_01",
        "destination_has_native_population": True,
        "same_class": False,
    },
    GUAR_S2: {
        "loan_reference": LN_S2,
        "guarantor_reference": GTOR_S2,
        "guaranteed_amount": AMOUNT_COVERED_S2,
        "destination_class": "retail_other",
        "destination_template": "c08_01",
        "destination_has_native_population": False,
        "same_class": False,
    },
    GUAR_S3: {
        "loan_reference": LN_S3,
        "guarantor_reference": GTOR_S3,
        "guaranteed_amount": AMOUNT_COVERED_S3,
        "destination_class": "central_govt_central_bank",
        # The OUTFLOW leg is only ever visible to C 08.01's population (its
        # origin approach is IRB) — but the guarantor is SA-treated, so the
        # INFLOW scalar belongs on C 07.00 (confirmed: it lands there as an
        # inflow-only sheet — see the module docstring NOTE). The two sides
        # of this one migration cross the SA/IRB template boundary.
        "destination_template": "c07",
        "destination_has_native_population": False,
        "same_class": False,
    },
    GUAR_S4: {
        "loan_reference": LN_S4,
        "guarantor_reference": GTOR_S4,
        "guaranteed_amount": AMOUNT_COVERED_S4,
        "destination_class": "institution",
        "destination_template": "c07",
        "destination_has_native_population": True,
        "same_class": False,
    },
    GUAR_S5: {
        "loan_reference": LN_S5,
        "guarantor_reference": GTOR_S5,
        "guaranteed_amount": AMOUNT_COVERED_S5,
        # Same class as the origin ("corporate") — see the module docstring
        # and ``same_class`` above.
        "destination_class": "corporate",
        "destination_template": "c08_01",
        "destination_has_native_population": True,
        "same_class": True,
    },
    # GUAR_S6 is DELIBERATELY ABSENT: it is DECLINED, so it has no
    # destination — see ``DECLINED_GUARANTEE_DESIGN`` below. Adding it here
    # with a zero/blank destination would silently corrupt
    # ``TestPerScenarioInflowLandsOnce`` (``test_crm_substitution_flows.py``),
    # which iterates this dict generically and asserts the recorded
    # ``guaranteed_amount`` lands on the recorded destination sheet: S6's
    # guarantor shares GTOR_S3's class (``central_govt_central_bank``), which
    # already has a real inflow from S3, so a zero-amount S6 entry would
    # wrongly assert that shared sheet's inflow column is 0.0.
    GUAR_S7: {
        "loan_reference": LN_S7,
        "guarantor_reference": GTOR_S7,
        "guaranteed_amount": AMOUNT_COVERED_S7,
        # DELIBERATELY the SAME (class, template) as GUAR_S1 — see the
        # OB_S7/GTOR_S7 comment above the constant declarations for why (a
        # sovereign guarantor would give a fresh destination but breaks
        # CRR/B31 regime-uniformity). The shared sheet's inflow column
        # (institution/C 08.01 col 0080) reports AMOUNT_COVERED_S1 +
        # AMOUNT_COVERED_S7 = 2,000,000 + 5,500,000 = 7,500,000 once both
        # scenarios are counted correctly — see the module docstring NOTE
        # and the header comment on this dict for the test-writer follow-up.
        "destination_class": "institution",
        "destination_template": "c08_01",
        "destination_has_native_population": True,
        "same_class": False,
    },
    GUAR_S8: {
        "loan_reference": LN_S8_GTD,
        "guarantor_reference": GTOR_S8,
        "guaranteed_amount": AMOUNT_COVERED_S8,
        # CROSS-TEMPLATE, mirroring S3: the outflow leg is only ever visible
        # to C 08.01's origin-slotting population, but the guarantor is
        # SA-treated (a slotting beneficiary's guarantor always is — see the
        # OB_S8/GTOR_S8 constant declarations), so the inflow belongs on
        # C 07.00. "corporate" is a FRESH C 07.00 destination (unlike S3's
        # central_govt_central_bank or S4's institution) that happens to
        # land on an ALREADY-POPULATED native sheet — S4's own corporate
        # loan — so a regression here inflates an EXISTING cell (see the
        # OB_S8/GTOR_S8 comment for the "make it loud" reasoning).
        "destination_class": "corporate",
        "destination_template": "c07",
        "destination_has_native_population": True,
        "same_class": False,
    },
}

#: S6's declined-guarantee design intent (Finding 4 /
#: ``engine/aggregator/aggregator.py::_beneficial_gate``): a guarantee the
#: engine DECLINES — guarantor SA risk weight no better than the leg's own —
#: produces NO substitution effect at all. The covered leg keeps the
#: obligor's basis end to end:
#:   - ``exposure_class_post_crm`` stays ``exposure_class_applied``
#:     (no class migration)
#:   - ``approach_post_crm`` stays ``approach_applied`` (no approach migration)
#:   - the origin sheet's outflow column (C 08.01 col 0070) gets NO
#:     contribution from this leg
#:   - NO guarantor-class sheet anywhere receives an inflow from this leg —
#:     in particular, GTOR_S6's class (``central_govt_central_bank``) already
#:     carries a real inflow from S3 (``AMOUNT_COVERED_S3`` on C 07.00 col
#:     0100); a regression that applied S6 anyway would inflate THAT existing
#:     cell by exactly ``AMOUNT_COVERED_S6``, not create a new one — the
#:     sharpest possible pin, since it reuses an already-asserted cell rather
#:     than an empty one
#: even though ``is_guaranteed`` stays True and ``guaranteed_portion`` stays
#: positive throughout (the physical ``__G_`` / ``__REM`` split happens
#: upstream of the benefit decision — see ``engine/crm/guarantees.py``).
#: fixture-builder does not assert the engine's CURRENT behaviour here (that
#: is test-writer's job over a live pipeline run) — this dict only records
#: the fixture's DESIGN intent, as required by Finding 4 / task #7's fix.
DECLINED_GUARANTEE_DESIGN: dict[str, dict[str, object]] = {
    GUAR_S6: {
        "loan_reference": LN_S6,
        "guarantor_reference": GTOR_S6,
        "guaranteed_amount": AMOUNT_COVERED_S6,
        "origin_class": "specialised_lending",
        "origin_template": "c08_01",
        # The class a beneficial substitution WOULD have targeted, and the
        # sheet that already exists (from S3) to receive it if the gate ever
        # regresses.
        "would_be_destination_class": "central_govt_central_bank",
        "would_be_destination_template": "c07",
    },
}

#: S7's cross-border country-basis design intent (PRA PS1/26 Annex II
#: Section 3.4 para 86/87 — C 09.01/C 09.02 geographical breakdown). NOT YET
#: IMPLEMENTED: today ``cp_country_code`` is joined onto every exposure row
#: (including the ``__G_`` guaranteed leg) by the exposure's OWN
#: ``counterparty_reference``, which the CRM splitter never reassigns to the
#: guarantor (``engine/crm/guarantees.py::_build_guarantor_sub_rows`` sets
#: ``guarantor_reference`` but leaves ``counterparty_reference`` — and
#: therefore ``cp_country_code`` — on the obligor's own basis throughout, for
#: every column, on every leg); ``guarantor_country_code`` is ALREADY joined
#: separately onto every exposure row via ``guarantor_reference``
#: (``_join_guarantor_counterparty``), so the raw input the fix needs is
#: already sealed and available — only C 09.01/C 09.02's column bindings
#: still need to read it (task "S2a: C 09.01 exposure-value / RWEA columns to
#: the post-substitution basis"). Recorded here as the fixture's DESIGN
#: intent for that fix, not the engine's CURRENT behaviour — mirroring
#: ``DECLINED_GUARANTEE_DESIGN`` and ``SUBSTITUTION_INFLOW_DESIGN`` above.
#: Once built:
#:   - "original exposure pre-conversion factors" (C 09.01 cols 0010/0020,
#:     C 09.02 cols 0010/0030) key the IMMEDIATE obligor's country
#:     (``obligor_country``) UNCONDITIONALLY, on every leg of LN_S7
#:     (``__G_`` and ``__REM`` alike) — substitution never moves this column,
#:     only the guaranteed leg's exposure-value / RWEA columns.
#:   - every other populated column ("exposure value", "Risk-weighted
#:     exposure amounts") keys the ULTIMATE obligor's country
#:     (``guarantor_country``) on the beneficially-substituted ``__G_`` leg
#:     ONLY. The ``__REM`` leg (never guaranteed) stays on
#:     ``obligor_country`` throughout, as does the WHOLE loan if the
#:     guarantee were ever declined instead of applied (S6's guarantor
#:     country never reaches a reported leg at all — the sharpest contrast:
#:     S6 proves a declined guarantee's country must NOT migrate, S7 proves
#:     a beneficial one MUST).
CROSS_BORDER_GUARANTEE_DESIGN: dict[str, dict[str, object]] = {
    GUAR_S7: {
        "loan_reference": LN_S7,
        "guarantor_reference": GTOR_S7,
        "guaranteed_amount": AMOUNT_COVERED_S7,
        "obligor_country": COUNTRY_OB_S7,
        "guarantor_country": COUNTRY_GTOR_S7,
        # Cross-referenced from SUBSTITUTION_INFLOW_DESIGN[GUAR_S7] — the
        # (class, template) pair the guaranteed leg's exposure-value / RWEA
        # columns are also reported under, independent of country. Shared
        # with GUAR_S1 — see the OB_S7/GTOR_S7 constant declarations.
        "destination_class": "institution",
        "destination_template": "c08_01",
    },
}

#: S8's slotting-blend design intent (COREP C 08.06 / Pillar 3 CR10 — the
#: per-category risk-weight columns; task "S4: C 08.06 + CR10 slotting grid
#: and lineage correction"). Two legs share ONE category (``SLOTTING_
#: CATEGORY_S8``, "good" -> 0.90 SA-equivalent):
#:   - LN_S8_PLAIN: unguaranteed, EAD = DRAWN_S8_PLAIN (6,500,000), reports
#:     at the category's OWN weight, 0.90, UNCONDITIONALLY.
#:   - LN_S8_GTD: PARTIALLY guaranteed. Its ``__REM`` leg (EAD =
#:     DRAWN_S8_GTD - AMOUNT_COVERED_S8 = 12,000,000 - 7,800,000 =
#:     4,200,000) is NEVER guaranteed and stays at the category's OWN
#:     weight, 0.90 — identical basis to LN_S8_PLAIN. Its ``__G_`` leg (EAD
#:     = AMOUNT_COVERED_S8 = 7,800,000) is beneficially substituted to
#:     GTOR_S8's SA risk weight, 0.20 (``CQS_GTOR_S8`` = 1).
#: A CORRECT per-leg treatment therefore reports THREE risk-weight tiers
#: within the SAME category (0.90, 0.90, 0.20), not one: total category EAD
#: 18,500,000, total RWA 6,500,000*0.90 + 4,200,000*0.90 + 7,800,000*0.20 =
#: 5,850,000 + 3,780,000 + 1,560,000 = 11,190,000. A defective SINGLE
#: EAD-weighted-average "risk weight" column (the shape this scenario
#: reproduces — see the OB_S8/GTOR_S8 constant declarations for the
#: production-shaped prototype that surfaced it) instead reports
#: 11,190,000 / 18,500,000 ≈ 0.6049 (~60.5%) — a number with NO regulatory
#: meaning, sitting inside neither the "good" (0.90) nor GTOR_S8's (0.20)
#: band, while any FIXED-display column elsewhere in the same template
#: (e.g. a "category" or "weight" column keyed off ``slotting_category``
#: alone) would print 0.90 next to it — the same incoherence the brief's
#: worked prototype reproduces, confirmed to reproduce identically here
#: — see the dated NOTE for the fixture-builder verification run's actual
#: observed C 08.06/CR10 output (current, pre-fix behaviour) alongside this
#: recorded correct-basis design intent. fixture-builder does not assert
#: the engine's CURRENT behaviour here (that is test-writer's job over a
#: live pipeline run) — this dict only records the fixture's DESIGN intent,
#: mirroring ``DECLINED_GUARANTEE_DESIGN`` / ``CROSS_BORDER_GUARANTEE_
#: DESIGN`` above.
SLOTTING_BLEND_DESIGN: dict[str, object] = {
    "slotting_category": SLOTTING_CATEGORY_S8,
    "plain_loan_reference": LN_S8_PLAIN,
    "plain_ead": DRAWN_S8_PLAIN,
    "plain_risk_weight": 0.90,
    "guaranteed_loan_reference": LN_S8_GTD,
    "guaranteed_remainder_ead": DRAWN_S8_GTD - AMOUNT_COVERED_S8,  # 4,200,000
    "guaranteed_remainder_risk_weight": 0.90,
    "guaranteed_substituted_ead": AMOUNT_COVERED_S8,  # 7,800,000
    "guaranteed_substituted_risk_weight": 0.20,
    "category_total_ead": DRAWN_S8_PLAIN + DRAWN_S8_GTD,  # 18,500,000
    "category_total_rwa_correct_basis": (
        DRAWN_S8_PLAIN * 0.90 + (DRAWN_S8_GTD - AMOUNT_COVERED_S8) * 0.90 + AMOUNT_COVERED_S8 * 0.20
    ),  # 11,190,000
}


def guaranteed_leg_ref(loan_reference: str, guarantor_reference: str) -> str:
    """The physical ``__G_`` guaranteed-leg exposure reference the CRM splitter
    emits (``engine/crm/guarantees.py::_build_guarantor_sub_rows``)."""
    return f"{loan_reference}__G_{guarantor_reference}"


def remainder_leg_ref(loan_reference: str) -> str:
    """The physical ``__REM`` retained-leg exposure reference the CRM splitter
    emits (``engine/crm/guarantees.py::_retained_tranche_rows``)."""
    return f"{loan_reference}__REM"


# ---------------------------------------------------------------------------
# Main public entry point
# ---------------------------------------------------------------------------


def build_reporting_crm_substitution_bundle() -> RawDataBundle:
    """Assemble the CRM guarantee-substitution portfolio as a sealed bundle.

    Sealed against the loader edge contracts by ``make_raw_bundle``, so it is
    shape-identical to a parquet-loaded production bundle. Run it through
    ``PipelineOrchestrator().run_with_data`` under either regime with
    ``PermissionMode.IRB`` — every IRB-routed obligor/guarantor carries an
    internal PD and the matching ``model_permissions`` row.
    """
    return make_raw_bundle(
        counterparties=_counterparties(),
        loans=_loans(),
        ratings=_ratings(),
        guarantees=_guarantees(),
        specialised_lending=_specialised_lending(),
        model_permissions=create_full_irb_model_permissions(),
    )


# ---------------------------------------------------------------------------
# Table builders (private)
# ---------------------------------------------------------------------------


def _counterparties() -> pl.DataFrame:
    """Eight obligor/guarantor pairs, one per scenario (S8 adds a NINTH row —
    its obligor carries two loans in one category, no second obligor needed).

    Obligors S1-S3/S5/S7 are ``corporate`` above the SME revenue ceiling so
    the supporting factor never perturbs a substitution cell; S4 is unrated so
    its own-basis SA risk weight is unambiguous; S6 is ``corporate`` too —
    like ``reporting_portfolio.py``'s slotting counterparty, specialised-
    lending routing comes from the ``specialised_lending`` join row
    (``_specialised_lending``), NOT from ``entity_type`` — plus a matching
    ``model_id``-only (no PD) rating so F-IRB/A-IRB stay unavailable and the
    exposure falls to slotting (CRR Art. 153(5)). Guarantors span the four SA
    classes ``ENTITY_TYPE_TO_SA_CLASS`` can reach from a counterparty
    (``institution`` x2, ``individual`` -> retail_other, ``sovereign`` x2 ->
    central_govt_central_bank), PLUS a fifth guarantor deliberately in the
    SAME class as its obligor (``corporate`` — S5) — see the module docstring
    table. GTOR_S6 is UNRATED (no rating row at all, like OB_S4) and non-GB
    (``US``) so neither an ECAI rating nor the Art. 114(4)/(7) domestic-CGCB
    0% carve-out can make its guarantee beneficial — only the plain
    ``CQS.UNRATED`` fallback (1.00) applies, strictly above the 0.70 slotting
    weight it is compared against. GTOR_S7 is a THIRD ``institution`` (after
    GTOR_S1 and GTOR_S4), IRB-rated (an internal PD, not an ECAI CQS) and
    incorporated in Germany rather than GB — see the OB_S7/GTOR_S7 comment
    above the constant declarations for why "institution" (not "sovereign",
    which was tried first and empirically broke CRR/B31 regime-uniformity)
    and why "DE". OB_S8 is the fixture's SECOND slotting-origin counterparty
    (after OB_S6), also ``corporate`` with a ``model_id``-only rating so it
    falls to slotting too; GTOR_S8 is ``corporate`` (not "institution", to
    keep it distinct from GTOR_S1/S4/S7) with a CQS rating, NOT an internal
    PD — a slotting beneficiary's guarantor is always SA-treated regardless
    of any internal rating, so an internal PD on GTOR_S8 would be inert; see
    the OB_S8/GTOR_S8 comment above the constant declarations.
    """
    rows: list[dict] = [
        {
            "counterparty_reference": OB_S1,
            "entity_type": "corporate",
            "country_code": "GB",
            "annual_revenue": _LARGE_CORPORATE_REVENUE,
        },
        {
            "counterparty_reference": GTOR_S1,
            "entity_type": "institution",
            "country_code": "GB",
        },
        {
            "counterparty_reference": OB_S2,
            "entity_type": "corporate",
            "country_code": "GB",
            "annual_revenue": _LARGE_CORPORATE_REVENUE,
        },
        {
            "counterparty_reference": GTOR_S2,
            "entity_type": "individual",
            "country_code": "GB",
            "is_natural_person": True,
        },
        {
            "counterparty_reference": OB_S3,
            "entity_type": "corporate",
            "country_code": "GB",
            "annual_revenue": _LARGE_CORPORATE_REVENUE,
        },
        {
            "counterparty_reference": GTOR_S3,
            "entity_type": "sovereign",
            "country_code": "GB",
        },
        {
            # Unrated: S4's obligor is a plain Standardised loan with no
            # internal PD and no ECAI rating (100% unrated corporate RW).
            "counterparty_reference": OB_S4,
            "entity_type": "corporate",
            "country_code": "GB",
            "annual_revenue": _LARGE_CORPORATE_REVENUE,
        },
        {
            "counterparty_reference": GTOR_S4,
            "entity_type": "institution",
            "country_code": "GB",
        },
        {
            "counterparty_reference": OB_S5,
            "entity_type": "corporate",
            "country_code": "GB",
            "annual_revenue": _LARGE_CORPORATE_REVENUE,
        },
        {
            # Same class as OB_S5 (corporate) but a DIFFERENT counterparty —
            # the SAME-CLASS defect (S5) needs two distinct obligors sharing
            # one class, not a self-guarantee.
            "counterparty_reference": GTOR_S5,
            "entity_type": "corporate",
            "country_code": "GB",
            "annual_revenue": _LARGE_CORPORATE_REVENUE,
        },
        {
            "counterparty_reference": OB_S6,
            "entity_type": "corporate",
            "country_code": "GB",
            "annual_revenue": _LARGE_CORPORATE_REVENUE,
        },
        {
            # Unrated, non-GB: the plain CQS.UNRATED sovereign fallback (1.00)
            # applies — see the docstring above.
            "counterparty_reference": GTOR_S6,
            "entity_type": "sovereign",
            "country_code": "US",
        },
        {
            "counterparty_reference": OB_S7,
            "entity_type": "corporate",
            "country_code": COUNTRY_OB_S7,
            "annual_revenue": _LARGE_CORPORATE_REVENUE,
        },
        {
            # IRB-rated (internal PD, not an ECAI CQS) and non-GB, non-US —
            # the cross-border BENEFICIAL substitution. "institution", not
            # "sovereign" — see the OB_S7/GTOR_S7 comment above the constant
            # declarations for the empirical CRR/B31 regime-uniformity reason.
            "counterparty_reference": GTOR_S7,
            "entity_type": "institution",
            "country_code": COUNTRY_GTOR_S7,
        },
        {
            # Second slotting-origin obligor (after OB_S6) — see the
            # ``_specialised_lending`` join, which carries the category for
            # BOTH of this counterparty's loans (LN_S8_PLAIN, LN_S8_GTD).
            "counterparty_reference": OB_S8,
            "entity_type": "corporate",
            "country_code": "GB",
            "annual_revenue": _LARGE_CORPORATE_REVENUE,
        },
        {
            # CQS-rated (not internal-PD) — a slotting beneficiary's
            # guarantor is always SA-treated. See the OB_S8/GTOR_S8 comment
            # above the constant declarations.
            "counterparty_reference": GTOR_S8,
            "entity_type": "corporate",
            "country_code": "GB",
        },
    ]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(COUNTERPARTY_SCHEMA))


def _ratings() -> pl.DataFrame:
    """Internal PD ratings for IRB legs, external CQS ratings for SA legs.

    OB_S4 and GTOR_S6 are deliberately unrated (no row at all) — a plain
    Standardised loan and an unrated sovereign guarantor respectively. OB_S6
    carries a ``model_id``-only rating (no PD) — see ``_internal_no_pd`` and
    the ``_counterparties`` docstring.
    """
    rows: list[dict] = [
        _internal(OB_S1, pd=PD_OB_S1),
        _internal(GTOR_S1, pd=PD_GTOR_S1),
        _internal(OB_S2, pd=PD_OB_S2),
        _internal(GTOR_S2, pd=PD_GTOR_S2),
        _internal(OB_S3, pd=PD_OB_S3),
        _external(GTOR_S3, cqs=CQS_GTOR_S3),
        _external(GTOR_S4, cqs=CQS_GTOR_S4),
        _internal(OB_S5, pd=PD_OB_S5),
        _internal(GTOR_S5, pd=PD_GTOR_S5),
        _internal_no_pd(OB_S6),
        _internal(OB_S7, pd=PD_OB_S7),
        _internal(GTOR_S7, pd=PD_GTOR_S7),
        _internal_no_pd(OB_S8),
        _external(GTOR_S8, cqs=CQS_GTOR_S8),
    ]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(RATINGS_SCHEMA))


def _loans() -> pl.DataFrame:
    """The nine obligor loans (S8 contributes two) plus the two guarantors'
    own exposures.

    GTOR_S5, GTOR_S6, GTOR_S7 and GTOR_S8 get NO own loan — S5's class
    already has an origin sheet (``corporate``, from OB_S1/OB_S2/OB_S3/OB_S5
    alike), S6 is DECLINED so it never creates an inflow that would need a
    sheet pre-established for it, S7's destination class (``institution``)
    already has a native C 08.01 population from GTOR_S1's own loan
    (LN_S1_GTOR_OWN) — see the module docstring on why S7 deliberately
    reuses that sheet rather than pre-establishing a fresh one of its own —
    and S8's destination class (``corporate``) already has a native C 07.00
    population from OB_S4's own loan (see the OB_S8/GTOR_S8 constant
    declarations for the same "make it loud" reasoning).

    No ``lgd`` is supplied on any row, so every IRB leg resolves F-IRB
    (supervisory LGD) — consistent with ``reporting_irb_classes_portfolio.py``.
    LN_S6/LN_S8_PLAIN/LN_S8_GTD are plain drawn term loans like every other
    row here — slotting routing comes entirely from the ``specialised_
    lending`` join (``_specialised_lending``), not from ``product_type``.
    """
    rows: list[dict] = [
        _loan(LN_S1, OB_S1, DRAWN_S1),
        _loan(LN_S1_GTOR_OWN, GTOR_S1, DRAWN_S1_GTOR_OWN),
        _loan(LN_S2, OB_S2, DRAWN_S2),
        _loan(LN_S3, OB_S3, DRAWN_S3),
        _loan(LN_S4, OB_S4, DRAWN_S4),
        _loan(LN_S4_GTOR_OWN, GTOR_S4, DRAWN_S4_GTOR_OWN),
        _loan(LN_S5, OB_S5, DRAWN_S5),
        _loan(LN_S6, OB_S6, DRAWN_S6),
        _loan(LN_S7, OB_S7, DRAWN_S7),
        _loan(LN_S8_PLAIN, OB_S8, DRAWN_S8_PLAIN),
        _loan(LN_S8_GTD, OB_S8, DRAWN_S8_GTD),
    ]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(LOAN_SCHEMA))


def _specialised_lending() -> pl.DataFrame:
    """S6's and S8's project-finance slotting exposures — DIFFERENT
    categories ("strong" / "good") so their C 08.06 / CR10 rows stay
    independently attributable (see the OB_S8/GTOR_S8 constant
    declarations).

    ``specialised_lending`` is a per-COUNTERPARTY join (no ``loan_reference``
    column in ``SPECIALISED_LENDING_SCHEMA``), so OB_S8's single row here
    applies to BOTH of its loans (LN_S8_PLAIN, LN_S8_GTD) — one obligor, two
    facilities, one category. Mirrors ``reporting_portfolio.py``'s
    ``_specialised_lending`` exactly — the same (``sl_type``,
    ``slotting_category``, ``is_hvcre``) combination, a PROVEN pattern
    already exercised by that widely-used golden fixture.
    """
    return pl.DataFrame(
        [
            {
                "counterparty_reference": OB_S6,
                "sl_type": "project_finance",
                "slotting_category": SLOTTING_CATEGORY_S6,
                "is_hvcre": False,
            },
            {
                "counterparty_reference": OB_S8,
                "sl_type": "project_finance",
                "slotting_category": SLOTTING_CATEGORY_S8,
                "is_hvcre": False,
            },
        ],
        schema_overrides=dtypes_of(SPECIALISED_LENDING_SCHEMA),
    )


def _guarantees() -> pl.DataFrame:
    """The eight guarantee rows — one per scenario, each partial cover.

    ``protection_type`` alternates ``"guarantee"`` / ``"credit_derivative"``
    so both C 08.01 cols 0040/0050 are exercised (4 ``"guarantee"`` / 4
    ``"credit_derivative"`` with S7/S8 added — both were already exercised
    by S1-S6, so S7/S8's values are a balance choice, not a new
    requirement). ``includes_restructuring``, matched maturity/currency, and
    both unilateral flags False on every row — no eligibility gate or
    maturity-mismatch haircut should zero any leg (see the module docstring;
    confirmed empirically, not merely asserted, in the fixture-builder
    verification run). GUAR_S6's ELIGIBILITY is unaffected by any of this —
    it is fully eligible protection that the engine correctly declines to
    APPLY because it would not help (guarantor RW >= own RW), which is a
    wholly different gate (CRR Art. 213 / Art. 193(1), not Art. 201).
    """
    rows: list[dict] = [
        _guarantee(GUAR_S1, GTOR_S1, LN_S1, AMOUNT_COVERED_S1, PCT_COVERED_S1, "guarantee"),
        _guarantee(GUAR_S2, GTOR_S2, LN_S2, AMOUNT_COVERED_S2, PCT_COVERED_S2, "credit_derivative"),
        _guarantee(GUAR_S3, GTOR_S3, LN_S3, AMOUNT_COVERED_S3, PCT_COVERED_S3, "guarantee"),
        _guarantee(GUAR_S4, GTOR_S4, LN_S4, AMOUNT_COVERED_S4, PCT_COVERED_S4, "credit_derivative"),
        _guarantee(GUAR_S5, GTOR_S5, LN_S5, AMOUNT_COVERED_S5, PCT_COVERED_S5, "guarantee"),
        _guarantee(GUAR_S6, GTOR_S6, LN_S6, AMOUNT_COVERED_S6, PCT_COVERED_S6, "guarantee"),
        _guarantee(GUAR_S7, GTOR_S7, LN_S7, AMOUNT_COVERED_S7, PCT_COVERED_S7, "credit_derivative"),
        _guarantee(
            GUAR_S8, GTOR_S8, LN_S8_GTD, AMOUNT_COVERED_S8, PCT_COVERED_S8, "credit_derivative"
        ),
    ]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(GUARANTEE_SCHEMA))


# ---------------------------------------------------------------------------
# Row helpers (private)
# ---------------------------------------------------------------------------


def _loan(loan_reference: str, counterparty_reference: str, drawn_amount: float) -> dict:
    """Build one plain drawn term-loan row (unset optional columns take
    schema defaults). EAD = drawn_amount (no CCF / facility involved)."""
    return {
        "loan_reference": loan_reference,
        "counterparty_reference": counterparty_reference,
        "product_type": "term_loan",
        "drawn_amount": drawn_amount,
        "currency": "GBP",
        "value_date": _VALUE_DATE,
        "maturity_date": _MATURITY,
        "seniority": "senior",
        "has_sufficient_collateral_data": False,
    }


def _guarantee(
    guarantee_reference: str,
    guarantor_reference: str,
    beneficiary_loan_reference: str,
    amount_covered: float,
    percentage_covered: float,
    protection_type: str,
) -> dict:
    """Build one guarantee row — always partial, always fully eligible."""
    return {
        "guarantee_reference": guarantee_reference,
        "guarantor": guarantor_reference,
        "currency": "GBP",
        "maturity_date": _GUARANTEE_MATURITY,
        "amount_covered": amount_covered,
        "percentage_covered": percentage_covered,
        "beneficiary_type": "loan",
        "beneficiary_reference": beneficiary_loan_reference,
        "protection_type": protection_type,
        "includes_restructuring": True,
        "original_maturity_years": _ORIGINAL_MATURITY_YEARS,
        "guarantor_seniority": "senior",
        "is_unilaterally_cancellable": False,
        "is_unilaterally_changeable": False,
    }


def _internal(counterparty_reference: str, *, pd: float) -> dict:
    """Internal model rating row (PD + model_id — the IRB routing pair)."""
    return {
        "rating_reference": f"CSUB-RTG-{counterparty_reference}",
        "counterparty_reference": counterparty_reference,
        "rating_type": "internal",
        "pd": pd,
        "model_id": _MODEL_ID,
        "rating_date": _VALUE_DATE,
    }


def _external(counterparty_reference: str, *, cqs: int) -> dict:
    """External ECAI rating row (CQS only, no model_id — never routes IRB)."""
    return {
        "rating_reference": f"CSUB-RTG-{counterparty_reference}",
        "counterparty_reference": counterparty_reference,
        "rating_type": "external",
        "rating_agency": "S&P",
        "cqs": cqs,
        "rating_date": _VALUE_DATE,
        "is_solicited": True,
    }


def _internal_no_pd(counterparty_reference: str) -> dict:
    """Internal rating carrying only ``model_id`` (no PD) — for slotting
    routing (mirrors ``reporting_portfolio.py``'s helper of the same name):
    with no internal PD the F-IRB/A-IRB branches are unavailable, so a
    counterparty with a matching ``specialised_lending`` row falls to
    slotting (CRR Art. 153(5))."""
    return {
        "rating_reference": f"CSUB-RTG-{counterparty_reference}",
        "counterparty_reference": counterparty_reference,
        "rating_type": "internal",
        "model_id": _MODEL_ID,
        "rating_date": _VALUE_DATE,
    }
