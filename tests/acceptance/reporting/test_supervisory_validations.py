"""
Supervisory validation gate — the published rules, ratcheted against a baseline.

Pipeline position:
    reporting portfolios -> PipelineOrchestrator -> COREP + Pillar 3 bundles
        -> evaluate_all (EBA rules under CRR, BoE rules under Basel 3.1)
        -> known-breaks + known-uncovered + known-vacuous baseline
        -> rules_with_a_verdict (every rule evaluated on at least one run)
    Basel 3.1 only, from the SAME COREP bundle:
        -> build_canonical_return -> validate_return (the gateway engine, with
           the Bank's deny list as it stands on the run date)
        -> known-gateway-breaks + known-engine-disagreements baseline

Why this is not a plain "no failures" assertion: the estate currently breaks a
known set of published rules, leaves a known set of templates unchecked, and
executes a known set of rules that assert nothing. Asserting zero of any of
those would fail permanently and be switched off; asserting nothing would let a
new defect land unnoticed. So the gate is a RATCHET over a committed liability
register, applied to ALL THREE populations — and, legs (m)/(n), to the set of
rules that are evaluated at all:

  (a) no broken rule outside the baseline           — the regression gate;
  (b) no baseline rule that no longer breaks        — a fix must shrink it;
  (c) no uncovered template outside the baseline    — a new blind spot fails;
  (d) no baseline template that is now covered      — closing one must shrink it;
  (e) every entry carries a written reason          — a register, not a hash;
  (f) no rule falls to vacuous outside the baseline — a PASS -> VACUOUS fails;
  (g) no baseline vacuous rule that now asserts     — activation must shrink it;
  (h) no gateway break outside the baseline         — Basel 3.1, the Bank's reading;
  (i) no baseline gateway break that has gone       — a fix must shrink it;
  (j) no engine disagreement outside the baseline   — the two readings part company;
  (k) no baseline disagreement that has gone        — agreement must shrink it;
  (l) no banked gateway break failing in more places — its count may not rise;
  (m) no banked rule left with no verdict on any run — a PASS -> NOT_EVALUATED fails;
  (n) no rule with a verdict that the register omits — a first verdict must be banked.

And a census of the output-floor STATE each Basel 3.1 run is in, held in this
module rather than the register file:

  (m) every Basel 3.1 run has a floor state, no CRR run has one;
  (n) the runs whose floor binds are ``BINDING_FLOOR_RUNS``, both ways;
  (o) OF 02.00's reported activation is the engine's state on every run;
  (p) the row shapes each state reaches are ``FLOOR_STATE_SHAPES``, both ways.

An Error-severity break rejects the entire return at submission, so every
``ERROR`` line in the register is a blocking filing defect.

Why there is a GATEWAY leg, (h)-(l), and why it keys on (rule, portfolio):
    Legs (a)-(g) read our template frames through rwa-filer's TEMPLATE-LEVEL
    engine (``rwa_filer.validate``). The Bank's gateway does not: it runs each
    rule on the filed return the way the taxonomy's XBRL formula reads it, and
    ``rwa_filer.boe`` is our implementation of that, pinned to Arelle rule by
    rule. The two read a Bank rule differently in five measured ways (design
    record O-03): the template-level engine skips where a row, column or sheet
    is absent instead of applying each reference's default; it refuses 67 Bank
    rules on grammar; it adds up a multi-cell reference the formula tests one
    cell at a time; it cannot see one data point shown in two tables; and it
    sets the missing-value policy per rule rather than per reference. (O-03
    measured a sixth - a break at a place where none of the rule's cells is
    reported - which O-03a and O-14b removed: such a place is now
    NOT_EVALUATED in both engines.) PR #548 and ``boe_b1055`` showed the two
    disagreeing where legs (a)-(g) could not see it.

    So for every Basel 3.1 run the gateway leg files the SAME generated COREP
    the template leg read — ``scripts/filing_mapping_report.py::file_on_gateway``,
    the one definition both ratchets use — and validates it with the Bank's
    validations deny list as it stands on the run date, which is
    ``export_filing_package``'s default too. A rule the Bank deactivated is
    NOT_EVALUATED and never enters the section; a downgraded one is recorded at
    its downgraded severity. It records:

    - ``known_gateway_breaks`` — every (rule, portfolio) the gateway engine
      FAILs, ERROR and WARNING. Keyed on the PAIR, not the rule: under a
      rule-only key ``boe_b1055`` spread from two portfolios to seven and
      nothing noticed. The severity is part of the key too, so a deny-list
      downgrade of a banked ERROR is a move the legs see, not a silent edit.
      ``tests/contracts/test_gateway_break_registers_agree.py`` holds the ERROR
      pairs equal, rule for rule, to ``scripts/filing_mapping_baseline.json``'s
      ``error_rules_by_rule``, so the two ratchets move together or not at all.
      The key says WHETHER a pair breaks, not where, so leg (l) also holds each
      pair's ``by_portfolio`` unsatisfied count to may-not-rise: a banked pair
      failing in one more place fails the gate, naming the pair and the new
      count, and one failing in fewer passes with a warning so that REGEN banks
      the lower count. Without it a new defect could sit behind a banked reason
      (a ``publisher issue PI-nn`` one included) on every pair that no focused
      acceptance test pins place by place.
    - ``known_engine_disagreements`` — every (rule, portfolio) on which the two
      engines reach OPPOSITE verdicts: one FAILs while the other PASSes or holds
      vacuously. NOT_EVALUATED on either side is not a disagreement. Keyed on
      the two verdicts too, so a disagreement that flips direction is new.

    Which engine is authoritative where: the gateway engine on everything the
    canonical return carries — it is what ``export_filing_package`` blocks on.
    The template-level engine is the only reading under CRR, the only reading
    of what the canonical return does not carry (OF 08.02, C 08.04,
    OF08.05.01.01, OF 08.06 and C 34.02 as measured for O-03), and the only
    source of the vacuity legs (f)/(g), which the gateway engine has no notion
    of. Its five differences above are why a disagreement is triaged, not
    assumed to be our output's fault.

Publisher-issue labels:
    A Bank rule can itself be wrong. The release's publisher-issue register
    (``rwa_filer.boe.issues``, rendered as ``docs/rwa-filer/publisher-issues.md``)
    records each one with its evidence, and a register entry whose cause is the
    published rule says so by citing it: a reason containing ``publisher issue
    PI-nn`` (``publisher issue PI-nn, in part`` where some of the pair's places
    are the issue's case and the rest are ours, named in the same reason). A
    Basel 3.1 break on a rule an issue names as its SUBJECT, with the effect
    ``fails_correct_returns``, must either cite that issue or START with a
    rebuttal, ``not PI-nn - <our defect>``, so a limit of the Bank's rule can
    never sit here under an "our defect" reason, nor the reverse silently.
    ``tests/contracts/test_register_publisher_issues.py`` enforces both
    directions on the committed JSON (fast; it runs no pipeline).

Every set leg shares ONE set-diff (P5.41) — all but (e), which reads reasons,
and (l), which compares counts on the pairs both sides hold (a pair on one side
only is (h)'s or (i)'s):
    The arithmetic behind "new" and "gone" is ``scripts/tolerated_findings.py``
    ``::diff``, extracted from this file so that this register and the two
    DECLARED ones — ``tests/oracle/test_oracle.py::KNOWN_DISAGREEMENTS`` and
    ``tests/conformance/classification_table.toml``'s ``[[known_disagreement]]``
    — cannot drift apart on what a movement means. Four registers of the same
    shape were four places to get the direction wrong.

    The mechanism is shared; the POLICY is not, and the difference is
    deliberate. This register stays TWO-WAY: its membership is measured over
    the pipeline runs of ``RUNS``, so a fixture change legitimately grows it and
    ``REGEN_VALIDATION_BASELINE=1`` may bank that. The declared registers are
    SHRINK-ONLY, with no bulk affordance that adds an entry at all, because an
    entry there is a decision to ship a figure an independent derivation has
    shown is wrong. Each caller states which it is.

Why there is an output-floor state census, (m)-(p):
    PS1/26 Art. 92(2A) makes TREA a maximum, ``max{U-TREA; x . S-TREA +
    OF-ADJ}``, so every Basel 3.1 return is in one of two states and a published
    rule over a floored figure has a branch for each. ``boe_b0751`` /
    ``boe_b0763`` (OF 08.01 / 08.02 col 0260) broke the first time a registered
    run bound the floor, because none had before (escape log 2026-11-16) —
    LESSONS B5 in the form "registered, live cell, but the portfolio never
    enters the state". The cell and rule ratchets cannot see it, since a cell is
    live and a rule holds a verdict in both states; the cell-coverage ratchet's
    banked caveat from ``reporting/corep/c02.py::_warn_if_the_engine_floor_differs``
    sees it only indirectly — it fires on a binding run that also holds SA rows,
    is blind to an all-modelled one, and goes when P1.367 lands. UK CRR
    Art. 92(3) has no maximum, so the CRR runs carry no floor and (m) says so.

    The census costs no pipeline run: each run's ``OutputFloorSummary``, the
    OF 02.00 the template leg reads and one six-boolean select over its ledger.
    It records the ENGINE state (``portfolio_floor_binding``: strict ``>`` over
    the modelled subset) and the REPORTED one (OF 02.00 r0034 c0030: ``>=`` over
    the whole book, Annex II p.29, what ``boe_b0383`` checks), because the two
    are computed apart (P1.367, the output-floor-subset bullet). The banked
    binding set is a SET, not a count (LESSONS B8).

    What it does NOT do: put any row the binding state lacks into it. The one
    binding run holds F-IRB corporates only, so slotting, A-IRB retail,
    defaulted, LFSE and CCR rows have met every published rule with the floor
    slack. (p) holds that gap still — it cannot widen silently — and
    ``FLOOR_STATE_SHAPES`` names who owes it. Nor does a slack-state guard on
    "some run with modelled exposure" add anything (p) does not: the slack
    state's six shapes are all modelled or CCR rows. ``test_of08_binding_floor.py``
    forces the floor on three registered books, test-locally, for about eight
    named rules; that is not this census.

Why (c)/(d) matter as much as (a)/(b): ``check_supervisory_validations`` FAILS
OPEN. On a bundle it cannot read, every rule is NOT_EVALUATED, so there are no
breaks and the result is indistinguishable from a clean estate. A shrinking
break set is only evidence of progress if coverage held — so coverage is
ratcheted too, and the per-run summary keeps NOT_EVALUATED separate from PASS
rather than letting unevaluable rules flatter a headline figure.

Why (f)/(g) exist — the third way this gate used to fail open:
    A rule whose every operand is null or exactly zero is scored ``VACUOUS``:
    it reached a verdict, the verdict held, and it asserted NOTHING (see
    ``rwa_filer/validate/evaluate.py::_Context.observe`` and
    ``checker.py::_roll_up``). Vacuity is 21%–70% of executed rules depending on
    the run — 23 of 109 on ``crr/irb-classes`` at the low end, 219 of 415 on
    ``b31/rich``, 123 of 177 on ``b31/off-bs`` at the high end. Union it across
    the run matrix and 218 rules — 143 of them Error-severity — reach a verdict
    and NEVER reach a real one anywhere.

    Legs (a)–(e) are all blind to it. A defect that empties a column silently
    converts ``PASS`` -> ``VACUOUS``: the template is still emitted, so (c)/(d)
    do not move; the break set does not grow, so (a)/(b) do not move; and the
    ``VACUOUS`` count in ``summary`` was documented as informational and
    asserted only to the extent that the four status counts add up. Every leg
    stayed green while the estate stopped being checked.

    This is measured history, not a hypothetical. ``.claude/LESSONS.md`` B5
    records a recurrence dated **2026-08-08** (batch 20260808-1624) where
    C 08.01 r0253 read ``0.00`` in all six golden portfolios: the mandatory
    Tier 2 gate ran fully green under a simulated fix because the cell it was
    meant to defend was dead. Closing it activated FIVE previously-``VACUOUS``
    rules to ``PASS``, ``boe_b0752_27`` — the r0253 tie-out itself — among them.
    That is the discharge this leg exists to force, and the ``boe_b0752_*`` /
    ``boe_b0814_*`` siblings still in ``known_vacuous_rules`` are the rest of
    the same family, still asserting nothing on other columns.

    So the ``VACUOUS`` counts in ``summary`` are descriptive, but vacuity itself
    is NOT informational any more: it is ratcheted per rule, both ways, exactly
    like a break. An entry is a LIABILITY — a published rule the supervisor
    will run and we currently satisfy by arithmetic rather than by evidence.

Why the key is ``(regime, rule_id)`` and not the failing coordinate:
    Coordinates are recorded on each entry for triage, but they are NOT the key.
    ``RuleOutcome.failures`` is capped at ``MAX_RECORDED_FAILURES``, and a
    substantial minority of failing rules exceed that cap (it was 20 of 75 when
    this was measured) — so partially fixing one shifts the recorded window and
    would manufacture a spurious "new break" alongside the real "now fixed". The
    regime prefix is load-bearing in its own right: 85 rule ids appear in BOTH
    published extracts (``v09779_m`` was a live case, failing under each), so a
    key on ``rule_id`` alone silently drops half.

    ``known_vacuous_rules`` uses THE SAME key, for both of those reasons: a
    vacuous rule has no failing coordinate to key on at all, and the 85 shared
    ids would collide across regimes just the same. Sharing the key also makes
    the two populations disjoint by construction, since a rule that FAILs
    anywhere has reached a real verdict and is therefore not vacuity-only.

    What legs (f)/(g) do NOT catch. Read this before treating a green (f) as
    evidence the estate is still being checked — an earlier draft of this
    paragraph overclaimed twice and a reviewer measured both claims false.

    FIRST, the union. Membership is the union over the runs: a rule is
    vacuity-only when NO run gets a real verdict out of it. A change that empties
    a column on ONE portfolio while another still exercises the same rule leaves
    this population unmoved. Measured on the 31-run matrix (2026-11-24), 432 of
    the 679 rules with a real verdict hold it on two or more runs, so that is a
    wide surface; the other 247 (145 ERROR) hold it on exactly one, where
    darkening that run reaches leg (f) if the rule is vacuous elsewhere and leg
    (m) if it is evaluated nowhere else. It cuts both ways
    on leg (g): a listed rule only leaves the population when the change reaches
    EVERY run where it was vacuous. Measured instance — ``crr/v3332_i`` is
    vacuous on both ``rich`` and ``crm-substitution``, so darkening it on ``rich``
    keeps it in the register and (g) stays green.

    SECOND: these legs are scoped to the ``VACUOUS`` status, so ``PASS ->
    NOT_EVALUATED`` escapes them, and legs (a)-(e) as well: a darkened rule is
    not a break, not a vacuity, and does not uncover its template while the
    template has other rules. Under Basel 3.1 the gateway legs see it only where
    the gateway engine itself then FAILs the rule, because a NOT_EVALUATED side
    is no disagreement (``_opposed``); under CRR there is no gateway leg.
    Measured on the 31-run matrix (2026-11-24): dropping one emitted row
    (``C 02.00`` r0160) from ``crr/rich`` moves two ERROR rules out of ``PASS``
    into ``NOT_EVALUATED`` there — ``v3335_i``, which passes on ``rich`` alone,
    and ``v0207_m``, which has a verdict on every CRR run — and not one
    population legs (a)-(l) compare moves.

    Legs (m)/(n) close the half of that which a set can close. The register banks
    ``rules_with_a_verdict``, every rule with PASS, FAIL or VACUOUS on at least
    one run, and leg (m) fails when a banked rule has no verdict on any run: the
    row-drop above fails it naming ``v3335_i``, and
    ``test_a_rule_darkened_on_its_only_run_fails_leg_m_alone`` re-does that
    row-drop on every run of this file, asserting that (m) is the ONLY leg that
    moves. It is a SET, not a count: ``scripts/coverage_report.py --check``
    ratchets the same population as COUNTS (``never_evaluated_rules`` may not
    rise, ``union_binding_rules_{crr,b31}`` may not fall), so there one rule
    going dark while another activates nets to zero, and that script is a
    separate CI job that ``/next-items`` Tier 2 does not run.

    What (m) does NOT close is the union limit above, for the same reason (f)
    does not: ``v0207_m`` loses its ``rich`` verdict to the same row-drop and
    keeps fourteen others, so nothing here moves. What (m) does close is a wide
    surface too: 150 rules (56 ERROR) had a verdict of any kind on exactly one
    run when measured, each one darkened run away from failing leg (m), and
    before (m) from going dark with every leg green.

    Where the single-portfolio case actually goes: to the goldens, one per run.
    Six portfolios keep their own golden modules (rich, ccr, irb-classes,
    off-bs, sa-classes, netting); every other run in ``RUNS`` is frozen by
    ``test_reporting_registered_goldens.py``, from the run's own builder, config
    and prior-period config, in its own ``<portfolio>_<regime>`` directory. Its
    ``test_every_registered_run_has_a_golden`` fails while any registered run
    lacks one, so a portfolio added here owes a golden the day it is added.
    Measured 2026-11-23: zeroing C 09.01 col 0010 on the GB sheet of
    ``re-split`` alone left every leg of this gate, the re-split focused tests
    and the cell-coverage census green, and reddened exactly the two re-split
    goldens. Owed: the ``rich`` and ``irb-classes`` goldens predate the prior
    frame and freeze C 08.04 and CR8 null (that module's ``_PRIOR_FRAME_OWED``),
    and all six legacy Basel 3.1 goldens freeze Pillar 3 OV1 row 27 ("Output
    floor adjustment") null for want of the output-floor summary
    (``_FLOOR_SUMMARY_OWED``). This gate's own Pillar 3 call below withholds
    both side inputs, so no register rule sees either cell populated.

Cost, and why every run is load-bearing:
    This file is the most expensive test in the suite: one full pipeline run per
    entry of ``RUNS`` (most portfolios under both regimes, a few under one only),
    one more for each IRB-permissioned entry's prior period, and two for leg (m)'s
    probe (``crr/rich`` and its prior, generated once more). Count ``RUNS``, not
    this prose — on 2026-11-24 it held forty-eight runs, twenty-five of them Basel
    3.1 and twenty-five with a prior period. The gateway leg adds one canonical
    return and one ``validate_return`` per Basel 3.1 run and no pipeline run: the
    pack is loaded once per process and the COREP bundle is the one the template
    leg already generated.
    Timed directly (2026-11-16, 4-core box, when the matrix held fifteen Basel 3.1
    runs): 0.6 s to load the pack plus 5.4 s for the fifteen filings (0.2-1.0 s
    each) of a 39.4 s gate, about 15%. That is a standing temptation to trim the run set, so
    the justification lives here rather than only in a commit message. Each run
    is the SOLE reachability route for a family of published rules, and
    dropping one does not make those rules pass — it makes them NOT_EVALUATED,
    which is indistinguishable from passing on the error channel:

    - ``rich``             the broad book — but entirely drawn, and IRB-thin;
    - ``off-bs``           the ONLY route to the C 07.00 conversion-factor
                           columns (0160-0190) and every rule written over
                           them;
    - ``ccr``              the ONLY portfolio emitting C 34.x, and therefore
                           the only place its standing coverage hole is
                           visible at all;
    - ``sa-classes``       the SA exposure-class sheet axis;
    - ``irb-classes``      the ONLY route to the C 08.03 / C 08.05 PD-band row
                           rules and the thin C 08.xx class sheets;
    - ``crm-substitution`` the ONLY run in ``RUNS`` with a non-zero figure in
                           C 07.00 cols 0060/0090/0100, C 08.01 cols
                           0040/0050/0080 and C 08.02 col 0080, and so the
                           sole route here to every rule written over the
                           inflow columns and the C 07.00 outflow. C 08.01
                           col 0070 is the exception: ``crr/irb-shapes``
                           also books its Art. 200(1)(b) life policy as a
                           substitution outflow, -80,000.00 in cols 0060 and
                           0070 of the retail_other sheet, rows
                           0010/0020/0070. That outflow has NO matching
                           inflow on any C 08.01 col 0080 or C 07.00 col 0100
                           of the run, although Annex II C 08.01 cols
                           0070-0080 says an outflow "shall be considered as
                           an inflow into the guarantor's exposure class". It
                           is a candidate defect, and the ``irb_shapes_crr``
                           golden now freezes it, so a fix owes a
                           preserve-or-fix record. Under Basel 3.1 the same
                           policy books to cols 0170/0172 instead. C 07.00
                           col 0050 ("(-) Guarantees") reads 0.00 or null on
                           every run in ``RUNS`` (all measured on the goldens,
                           2026-11-23). Outside ``RUNS``, the property
                           corpus's ``mitigated`` run keeps C 07.00 cols
                           0050/0090/0100 live in the cell census, so for
                           those three columns the census is no guard here.
                           The guards are ``test_crm_substitution_flows.py``'s
                           absolute inflow/outflow pins and its
                           cross-template conservation test, plus the
                           ``crm_substitution_*`` goldens.
    - ``netting``          the ONLY portfolio whose on-balance-sheet netting
                           agreement spans more than one counterparty, and so
                           the only route to C 07.00 col 0035 ("(-) Adjustment
                           due to on-balance sheet netting", Basel 3.1 sheet
                           only) carrying a figure at all.
    - ``rw-ladder``        the ONLY route to the C 07.00 / OF 07.00 risk-weight
                           rows of the class weights no other book uses
                           (Basel 3.1 15/25/40/45/65/80/105/130/135%, CRR
                           250/1250%), and so to the rung identities written
                           over them.
    - ``default-populations`` the ONLY provisioned, guaranteed or non-corporate
                           defaulted standardised legs, so the only route to
                           C 07.00 / OF 07.00 row 0300, a figure in c0030 of the
                           memo rows, and (Basel 3.1) the high-risk sheet 0012.
    - ``qrre-headroom``    the ONLY portfolio with a QRRE candidate that has
                           more than one leg under a facility, or a row past
                           the Art. 147(5A)(c) / 154(4)(c) per-individual
                           ceiling — so the only route by which a MULTI-LEG or
                           PAST-THE-CAP change to the QRRE aggregate moves a
                           C 08.01 sheet. ``irb-classes``' single-leg QRRE row
                           still moves under a change that inflates one
                           facility's own contribution past the ceiling.

    Measured: ``sa-classes`` and ``irb-classes`` together move 53 CRR and 32
    Basel 3.1 rules out of NOT_EVALUATED. The ten prior-period runs exist
    because C 08.04 reports RWEA *flows* — COREP Annex II §3.3.6.1 ¶79 defines
    them against the PRIOR reference date — so without one, rows 0010-0080 are
    null by construction and the flow rules cannot be evaluated at all. Each
    prior run uses a genuinely EARLIER reference date rather than re-passing the
    current frame, so the opening balance is a real prior figure with a
    non-zero residual rather than a fiction asserting nothing moved in the
    period.

    If this must be trimmed, drop whole portfolios deliberately and record the
    rules that go dark; do not silently reduce the matrix.

A rule that cannot fail is close to no coverage at all:
    C 08.04's flow rules (``v09779_m`` and its Basel 3.1 twin) are the worked
    example. ``generate_c08_04`` puts the signed residual ``closing - opening``
    in row 0080 "Other" precisely so the statement foots, so once a prior frame
    exists ``{r0090} = {r0010}+…+{r0080}`` reduces to ``r0090 = r0090`` and can
    never fail at any figure. That is the CORRECT Annex II construction — r0080
    is the row that absorbs unexplained movement — so the pass is legitimate and
    the rule belongs in the run. But it is a STRUCTURAL pass, not evidence the
    flows are right, and it should not be read as coverage of the six
    attributable driver rows (0020-0070), which stay null. Recorded here rather
    than banked as a win.

Baseline format:
    ``tests/expected_outputs/reporting/validation_known_breaks.json`` — a JSON
    object with ``notes`` (how to read the register), ``summary`` (per-run
    outcome counts; descriptive, and the only part of the file nothing asserts
    entry-by-entry), ``known_broken_rules``, ``known_uncovered_templates``,
    ``known_vacuous_rules``, ``known_gateway_breaks``,
    ``known_engine_disagreements`` and ``rules_with_a_verdict``. The two gateway
    sections are written one entry per (rule, reason) with the portfolios it
    covers, so a rule that breaks for two causes on two portfolios is two
    entries, each with one cause. ``rules_with_a_verdict`` is ``{regime:
    [rule_id, ...]}`` with no reasons: it is the covered set, not a liability,
    and REGEN rewrites it whole.

Regenerating the baseline:
    Set ``REGEN_VALIDATION_BASELINE=1`` and run this file. Hand-written
    ``reason`` text is PRESERVED — regeneration refreshes the population and the
    recorded coordinates, never the curation. An entry nobody has written about
    gets the ``unclassified`` placeholder and must be given a real reason before
    the register is committed. In the two gateway sections a reason is kept per
    (rule, portfolio): a rule that breaks on ONE MORE portfolio arrives
    unclassified, because a spread is a new break until someone says why; where the mechanism is visible but the defect is
    not established, the honest reason is the greppable ``unattributed - needs
    investigation``, not a guess. A break reason that is not wholly a publisher
    issue's - ours, in part ours, or unattributed - also carries ``OWNER: P<n>.<n>``
    naming an open plan bullet (``tests/contracts/test_register_owners.py``). Never
    bulk-regen to make a red gate green: a new break is a new filing defect until
    someone has said otherwise in writing.
    The same applies to a new ``known_vacuous_rules`` entry: a rule that has
    stopped asserting anything is a check we have LOST, so it is banked only with
    a written account of what emptied it.

    CHECK FOR STALE REASONS after every regeneration. Preserving curation is
    right up until the thing a reason CITES gets fixed, and then it rots
    silently: five entries once carried "…see crr/v4756_m" after ``v4756_m`` had
    left the register entirely. Grep each surviving reason for rule-id patterns
    (``v\\d{4,5}_[a-z]``, ``boe_b\\d{4}``) and check the ids still exist here.
    Some references are deliberate — ``boe_b0265`` cites ``boe_b0252`` and
    ``v09782_m`` cites ``v09783_m`` precisely BECAUSE those rules pass for us — so
    the check is a prompt to look, not a rule. Where a cited rule has been fixed,
    RE-MEASURE the entry rather than editing its prose: the surrounding defect
    has usually changed shape too.

References:
- tests/acceptance/reporting/test_reporting_golden.py — the run-and-generate pattern
- src/rwa_calc/reporting/filing/ — the adapter; packages/rwa-filer/src/rwa_filer/validate/ — the evaluator
- COREP Annex II (CRR); PRA PS1/26 Annex II (Basel 3.1)
"""

from __future__ import annotations

import dataclasses
import json
import os
import warnings
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import date
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any, NamedTuple

import polars as pl
import pytest
from scripts.tolerated_findings import diff
from tests.acceptance.reporting.test_reporting_golden import _b31_config, _crr_config
from tests.fixtures.facility_share_portfolio import (
    build_facility_share_bundle,
    facility_share_config,
    facility_share_prior_config,
)
from tests.fixtures.reporting_ccr_portfolio import build_reporting_ccr_bundle
from tests.fixtures.reporting_crm_substitution_portfolio import (
    build_reporting_crm_substitution_bundle,
)
from tests.fixtures.reporting_crr_irb_mdb_portfolio import build_reporting_crr_irb_mdb_bundle
from tests.fixtures.reporting_declined_guarantee_portfolio import (
    build_reporting_declined_guarantee_bundle,
)
from tests.fixtures.reporting_default_populations_portfolio import (
    build_reporting_default_populations_bundle,
)
from tests.fixtures.reporting_equity_transitional_portfolio import (
    build_reporting_equity_transitional_bundle,
)
from tests.fixtures.reporting_funded_protection_portfolio import (
    build_reporting_art199_bundle,
)
from tests.fixtures.reporting_ig_election_portfolio import (
    build_reporting_ig_election_bundle,
    ig_election_config,
    ig_election_prior_config,
)
from tests.fixtures.reporting_intragroup_portfolio import (
    INTRAGROUP_DATE,
    build_reporting_intragroup_bundle,
    intragroup_config,
)
from tests.fixtures.reporting_irb_classes_portfolio import build_reporting_irb_classes_bundle
from tests.fixtures.reporting_irb_shapes_portfolio import build_reporting_irb_shapes_bundle
from tests.fixtures.reporting_netting_mismatch_portfolio import build_netting_mismatch_bundle
from tests.fixtures.reporting_netting_portfolio import build_reporting_netting_bundle
from tests.fixtures.reporting_offbs_portfolio import build_reporting_offbs_bundle
from tests.fixtures.reporting_over_collateralised_portfolio import (
    build_over_collateralised_bundle,
)
from tests.fixtures.reporting_portfolio import build_reporting_bundle
from tests.fixtures.reporting_qrre_headroom_portfolio import build_reporting_qrre_headroom_bundle
from tests.fixtures.reporting_qrre_mof_portfolio import build_reporting_qrre_mof_bundle
from tests.fixtures.reporting_re_split_portfolio import build_reporting_re_split_bundle
from tests.fixtures.reporting_row_scope_portfolio import build_reporting_row_scope_bundle
from tests.fixtures.reporting_rw_ladder_portfolio import (
    build_reporting_rw_ladder_bundle,
    rw_ladder_config,
)
from tests.fixtures.reporting_sa_classes_portfolio import build_reporting_sa_classes_bundle
from tests.fixtures.reporting_slotting_maturity_portfolio import (
    REPORTING_DATE as SLOTTING_MATURITY_DATE,
)
from tests.fixtures.reporting_slotting_maturity_portfolio import (
    build_reporting_slotting_maturity_bundle,
    slotting_maturity_config,
    slotting_maturity_prior_config,
)

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import ApproachType, ExposureClass, PermissionMode
from rwa_calc.engine.aggregator._schemas import SA_CCR_APPROACH
from rwa_calc.engine.pipeline import PipelineOrchestrator
from rwa_calc.reporting.corep.generator import COREPGenerator
from rwa_calc.reporting.filing.checks import evaluate_all
from rwa_calc.reporting.pillar3.generator import Pillar3Generator
from rwa_filer.boe.engine import STATUS_FAIL as GATEWAY_FAIL
from rwa_filer.boe.engine import STATUS_PASS as GATEWAY_PASS
from rwa_filer.validate.evaluate import (
    STATUS_FAIL,
    STATUS_NOT_EVALUATED,
    STATUS_PASS,
    STATUS_VACUOUS,
)

if TYPE_CHECKING:
    from rwa_calc.contracts.bundles import OutputFloorSummary, RawDataBundle
    from rwa_calc.reporting.corep.generator import COREPTemplateBundle
    from rwa_calc.reporting.pillar3.generator import Pillar3TemplateBundle
    from rwa_filer.boe.engine import RuleResult
    from rwa_filer.validate.checker import RuleOutcome, ValidationReport

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASELINE_PATH = (
    Path(__file__).parent.parent.parent
    / "expected_outputs"
    / "reporting"
    / "validation_known_breaks.json"
)
REGEN = os.environ.get("REGEN_VALIDATION_BASELINE") == "1"

#: Placeholder written for an entry nobody has triaged. Distinct from
#: ``unattributed - needs investigation``, which IS a written reason: it records
#: that the mechanism is visible but the defect is not yet established.
UNCLASSIFIED = "unclassified - describe the defect this entry corresponds to"

#: Coordinates recorded per broken rule, for triage. Purely informational — the
#: ratchet keys on the rule, so this may be refreshed freely.
MAX_RECORDED_COORDINATES = 5

RULE_KEY_FIELDS = ("regime", "rule_id")
TEMPLATE_KEY_FIELDS = ("regime", "portfolio", "template")

#: The regime the gateway leg runs under: PRA001 is the Basel 3.1 return, so a
#: CRR run has nothing to file. Written on every gateway entry for the reader.
GATEWAY_REGIME = "b31"
GATEWAY_FRAMEWORK = "BASEL_3_1"

#: Cells quoted per gateway break, from the first unsatisfied evaluation. For
#: triage only — the ratchet keys on (rule, portfolio).
MAX_RECORDED_CELLS = 4

#: Sample cells recorded per vacuous rule. A vacuous rule has NO failing
#: coordinate — that is the whole point of it — so the tables it addresses and
#: the count of coordinates it held over vacuously are the only triage handles
#: the evaluator can give, and they are recorded instead.
MAX_RECORDED_TABLES = 5

#: The register section holding every rule that reaches a verdict on at least
#: one run of ``RUNS``, as ``{regime: [rule_id, ...]}``. Legs (m)/(n) ratchet it.
EVALUATED_SECTION = "rules_with_a_verdict"

#: What counts as a verdict for ``EVALUATED_SECTION``. VACUOUS is one — the rule
#: ran and held, at ``0 = 0`` — so the only status that is NO verdict is
#: NOT_EVALUATED, and the section's complement is the never-evaluated pool.
VERDICT_STATUSES = frozenset({STATUS_PASS, STATUS_FAIL, STATUS_VACUOUS})

#: Said by legs (m) and (n) when the register has no verdict set to compare with:
#: an absent section would otherwise make (m) pass with nothing banked to lose.
MISSING_EVALUATED_SECTION = (
    f"the register holds no {EVALUATED_SECTION} section, so leg (m) has nothing to hold and "
    "would pass whatever went dark. Bank it: REGEN_VALIDATION_BASELINE=1 uv run pytest "
    "tests/acceptance/reporting/test_supervisory_validations.py -n 0"
)

#: Leg (m)'s observed-red probe: one run, and one emitted row whose removal darkens
#: a rule that has its only verdict on that run. Measured 2026-11-24 on the 31-run
#: matrix: dropping C 02.00 r0160 from crr/rich moves v3335_i (ERROR, PASS on rich
#: alone) and v0207_m (ERROR, a verdict on every CRR run) to NOT_EVALUATED there.
PROBE_RUN = ("crr", "rich")
PROBE_ROW = "0160"

#: Header written into the register on every regeneration, so the file explains
#: how to read itself to someone who never saw this module. Emitted from here
#: rather than hand-added to the JSON, which a regeneration would discard.
REGISTER_NOTES: dict[str, str] = {
    "what_this_is": (
        "Known supervisory validation breaks, coverage holes and VACUOUS rules of the "
        "template-level engine, and the gateway engine's breaks and the two engines' "
        "disagreements on each filed Basel 3.1 return, ratcheted by "
        "tests/acceptance/reporting/test_supervisory_validations.py. An entry is a LIABILITY, "
        "not a waiver: an ERROR-severity break rejects the entire return at submission."
    ),
    "reading_the_two_engines": (
        "Two engines read the Bank's rules here. known_broken_rules, known_uncovered_templates "
        "and known_vacuous_rules come from rwa-filer's TEMPLATE-LEVEL engine (rwa_filer.validate) "
        "reading our template frames, under both regimes. known_gateway_breaks comes from the "
        "GATEWAY engine (rwa_filer.boe, pinned to Arelle rule by rule) reading the canonical "
        "return filed from the same Basel 3.1 COREP, with the Bank's validations deny list as it "
        "stands on the run date: it is what export_filing_package blocks on and what the Bank's "
        "gateway runs, so on anything the canonical return carries it is the authority, and an "
        "ERROR there is a rejected return. A rule the deny list deactivates is not evaluated and "
        "never appears; a downgraded one appears at WARNING. known_engine_disagreements lists "
        "every (rule, portfolio) on which one engine breaks a rule the other holds. The "
        "template-level engine differs from the gateway in five measured ways (design record "
        "O-03): it skips where a row, column or sheet is absent instead of applying each "
        "reference's default; it refuses 67 Bank rules on grammar (isNull, if/then, and/or, "
        "dimensional filters); it adds up a multi-cell reference the formula tests one cell at a "
        "time; it cannot see one data point shown in two tables; and it sets the missing-value "
        "policy per rule rather than per reference. O-03 measured a sixth, a break at a place "
        "where none of the rule's cells is reported; it is gone - since O-03a (Bank rules) and "
        "O-14b (EBA rules) such a place is NOT_EVALUATED (nothing_reported) unless the extract "
        "marks the rule 'Always execute', as the XBRL formula skips it. So a break only the "
        "gateway shows is usually one the template-level engine "
        "cannot see (each gateway entry's by_portfolio.template_level says why), and a "
        "disagreement is triaged before it is blamed on our output. The template-level engine "
        "remains the only reading under CRR, the only one of what the canonical return does not "
        "carry (OF 08.02, C 08.04, OF08.05.01.01, OF 08.06, C 34.02), and the only source of the "
        "vacuity register. Both gateway sections are keyed per (rule, portfolio), so a rule that "
        "breaks on one more portfolio is a new entry; known_gateway_breaks is keyed on the "
        "severity too, so a break the deny list moves to another severity is a new entry and "
        "its reason is written again. Each known_gateway_breaks pair's by_portfolio "
        "unsatisfied count may not rise: a banked pair that fails in more places fails the "
        "gate, naming the pair and the new count, and one that fails in fewer passes with a "
        "warning so that a regeneration banks the lower count as the new ceiling (the reason "
        "is kept, so read it against the new places). The ERROR half of known_gateway_breaks "
        "equals scripts/filing_mapping_baseline.json error_rules_by_rule rule for rule "
        "(tests/contracts/test_gateway_break_registers_agree.py): re-bank the two together."
    ),
    "reading_publisher_issue_labels": (
        "A Bank rule can itself be wrong. rwa-filer's publisher-issue register "
        "(rwa_filer.boe.issues, release 4.1.1; shared as docs/rwa-filer/publisher-issues.md) "
        "holds each known case with its evidence, and a Basel 3.1 entry here says in its reason "
        "whether that is its cause. 'publisher issue PI-nn: ...' means the published rule is the "
        "cause: a return that follows the instructions breaks it, so the fix is the Bank's and "
        "our figures stay as they are; PI-nn names the entry's rule as its SUBJECT. A reason that "
        "STARTS 'not PI-nn - ...' says the issue names this rule but this break is not that "
        "issue, and what follows says whose it is: ours or our engine's, fixed here, or rarely "
        "another issue's, cited in the same reason (boe_b0737: not PI-08, publisher issue "
        "PI-24); PI-nn names the rule as its subject (the issue would otherwise explain the "
        "break) or as a control (the issue's evidence is that a correct return satisfies the "
        "rule). On a break, a cited issue's effect is fails_correct_returns: an issue saying a "
        "rule passes wrong returns or never runs cannot be why it fails. A (rule, portfolio) "
        "pair whose places have two causes - some the issue's case, the rest ours - has one "
        "reason, so it reads 'publisher issue PI-nn, in part: <the issue's places> ...; <the "
        "rest> our defect, OWNER: P<n>.<n> ...': the citation keeps the Bank's share findable, and "
        "naming ours in the same reason keeps it from hiding behind the citation. Every Basel "
        "3.1 break on a rule that a fails_correct_returns issue names as its subject carries "
        "one of the labels - open or fixed in a later release alike, since this register is "
        "release 4.1.1's - and no reason may call its break a limit of the published rule "
        "without citing the issue: tests/contracts/test_register_publisher_issues.py enforces "
        "all of it on this file. To read the labels: grep -n 'publisher issue PI-' lists the "
        "Bank's share (whole, or ', in part'); grep -n 'reason.: .not PI-' lists the breaks on a "
        "rule an issue names that are not that issue (a reason sits after the reason key in "
        "the JSON, so a bare '^not PI-' matches nothing). An entry with neither label is "
        "one of two kinds: a break on a rule that no fails_correct_returns issue names as its "
        "subject (ours, or 'unattributed - needs investigation', either with its OWNER - see "
        "reading_an_owner), or an "
        "entry the requirement does not cover - a vacuous rule (known_vacuous_rules is not a "
        "break, so a rule an issue names may sit there unlabelled), or a break on a rule an "
        "issue names only as related or contradicting, about whose breaks the issue claims "
        "nothing. CRR entries are EBA rules and carry no PI label. A label never changes a "
        "verdict: an ERROR "
        "labelled with an issue still rejects the return at the gateway until the Bank changes "
        "or deactivates the rule."
    ),
    "reading_an_owner": (
        "A break of ours names who fixes it. Every reason in known_broken_rules, "
        "known_gateway_breaks and known_engine_disagreements that is not wholly a publisher "
        "issue's - one that says 'our defect', cites an issue only 'in part', or cites none in "
        "full ('unattributed - needs investigation', a 'not PI-nn - ' rebuttal that cites no "
        "other issue, and every CRR entry, whose EBA rule no issue covers) - carries 'OWNER: "
        "P<n>.<n>' after its label, naming the IMPLEMENTATION_PLAN.md bullet that owns the fix "
        "('our defect, OWNER: P<n>.<n>: ...'). 'plan item P<n>.<n>' is prose, not an owner: "
        "reasons cite closed bullets as history. The trigger is who the cause is, not whether "
        "the reason says 'capital': of the four reasons that once parked a capital defect with "
        "no owner, two said so and two pointed at it with '(see boe_b0283)'. Every OWNER here, "
        "in a reason or a note, names a bullet the plan holds open (any status box but [x]; "
        "closed bullets are pruned, so a missing one is closed), so the change that closes or "
        "prunes an "
        "owning bullet removes the entries it fixed, re-owns the ones it did not, or reopens "
        "the bullet. tests/contracts/test_register_owners.py enforces both halves on this file "
        "and the plan; scripts/check_parked_registers.py holds the oracle and classification "
        "registers to the same open-owner rule. grep -n 'OWNER: P' lists every owned entry."
    ),
    "what_a_vacuity_entry_MEANS": (
        "known_vacuous_rules lists rules that REACH a verdict on at least one registered run and "
        "reach it only VACUOUSLY - every operand was null or exactly zero, so the comparison held "
        "at 0 = 0 and asserted nothing about our figures. It is not a break and not a coverage "
        "hole; it is a check we are not getting. Membership is the union over portfolios: a rule "
        "PASSing or FAILing anywhere is NOT here, which also makes this list disjoint from "
        "known_broken_rules. It is ratcheted BOTH ways, exactly like a break - a rule that falls "
        "to vacuous outside this list fails the gate (the PASS -> VACUOUS regression, which moves "
        "neither the break set nor template coverage and was invisible before), and a listed rule "
        "that stops being vacuous on every run must be REMOVED from the list."
    ),
    "what_the_vacuity_ratchet_does_NOT_catch": (
        "Two limits, both measured, both stated because a green leg is otherwise read as more than"
        " it is. (1) UNION: a change that empties a column on one portfolio while another still "
        "gets a real verdict out of the same rule moves nothing here, and 432 of the 679 rules "
        "with a real verdict held it on two or more runs when measured on the 31-run matrix "
        "(2026-11-24). Same masking on the removal leg: crr/v3332_i is vacuous on both rich and "
        "crm-substitution, so darkening it on rich leaves the entry standing. (2) STATUS SCOPE: "
        "these legs see VACUOUS only, so PASS -> NOT_EVALUATED escapes them - dropping one emitted"
        " row (C 02.00 r0160) from crr/rich moves two ERROR rules from PASS to NOT_EVALUATED "
        "there, v3335_i and v0207_m, and no vacuity, break or coverage leg moves. That half is "
        "held by rules_with_a_verdict (see what_rules_with_a_verdict_MEANS), but for a rule's LAST"
        " verdict only: v3335_i passes on crr/rich alone, so it leaves that section and the gate "
        "fails naming it; v0207_m still has a verdict on fourteen other CRR runs, so it moves "
        "nothing anywhere in this register."
    ),
    "what_rules_with_a_verdict_MEANS": (
        "rules_with_a_verdict lists, per regime, every rule id the template-level engine brings "
        "to a verdict - PASS, FAIL or VACUOUS - on at least one registered run. It is the "
        "COVERED set, not a liability, so its entries carry no reason. It is ratcheted both "
        "ways. A listed rule that reaches no verdict on any run fails the gate, naming the rule "
        "and why each run left it NOT_EVALUATED: that is the PASS -> NOT_EVALUATED regression "
        "no other section sees (a row, column or sheet no longer emitted, a sheet map or binding "
        "that stopped addressing it, a run dropped from RUNS), and a VACUOUS-only rule going "
        "dark fails here and in the vacuity removal leg together. A rule that reaches a verdict "
        "and is not listed must be added, so the section cannot go stale under the first leg. "
        "It holds the LAST verdict only: a rule falling from verdicts on two runs to one moves "
        "nothing here (limit (1) of what_the_vacuity_ratchet_does_NOT_catch). Membership also "
        "moves with the rule set, because the template-level rules are loaded with the Bank's "
        "deny list as it stands on the day the gate runs: a deny-list entry coming into force, "
        "or an extract or taxonomy refresh, removes or adds entries, and those are re-banked "
        "deliberately with REGEN_VALIDATION_BASELINE=1 and said so in the commit. The enforced "
        "rules outside this section are the ones scripts/coverage_report.py counts as "
        "never_evaluated_rules over the same RUNS; that script ratchets only the COUNT, so a "
        "rule going dark while another activates nets out there and not here."
    ),
    "how_to_discharge_a_vacuity_entry": (
        "Make one cell the rule addresses carry a real figure on a registered portfolio, then "
        "DELETE the entry - the gate will fail until you do, which is the design. The worked "
        "example is the 2026-08-08 B5 recurrence (.claude/LESSONS.md): C 08.01 r0253 read 0.00 in "
        "all six goldens, so Tier 2 was structurally incapable of seeing a change to it. Closing "
        "it needed a TWO-LEG fixture - a live cell that SURVIVES the change plus one that MOVES, "
        "because a single moving row leaves the cell at 0.00 afterwards - and activated five "
        "previously-VACUOUS rules to PASS, boe_b0752_27 (the r0253 tie-out) among them. Do NOT "
        "discharge an entry by deleting the rule, narrowing a portfolio, or making the cell "
        "structurally absent: absence is NOT_EVALUATED, which is worse than vacuity, not better. "
        "Made absent on EVERY run where the rule was vacuous, it fails the vacuity removal leg "
        "and the rules_with_a_verdict leg together, and the second names it as a lost verdict; "
        "made absent on only some of them, per what_the_vacuity_ratchet_does_NOT_catch, it "
        "reddens no leg at all, so nothing here will stop you doing it."
    ),
    "reading_a_vacuity_reason": (
        "The mechanism sentence names WHICH limb the measured evidence supports. 'emitted but "
        "unreported (null)' means the cells exist in the layout and carry no figure, so the "
        "rule's treat-missing-as-zero policy coalesces them to 0.0 - the LESSONS B1/B5 dead-cell "
        "signature, and the limb most likely to be hiding a defect. 'emitted and exactly 0.00' "
        "means the cells ARE populated and the figure is genuinely zero - usually a portfolio "
        "artefact (no exposure of the kind the column measures) but equally consistent with a "
        "column nothing ever writes to. Neither limb settles the root cause, which is why most "
        "entries are prefixed 'unattributed - needs investigation'. The exception is the "
        "'structural' prefix: see the next note."
    ),
    "structural_vacuity_of_prohibition_rules": (
        "A rule of the form '{ref} = empty' asks whether a cell was REPORTED, and holds precisely "
        "by our reporting nothing there. rwa_filer/validate/evaluate.py::_evaluate_emptiness "
        "returns VACUOUS for the holding case, so PASS is UNREACHABLE for this family and vacuity "
        "is the passing verdict, not a lost check. Those entries are prefixed 'structural' and "
        "need no investigation. Their only other outcome is FAIL (we reported a figure the "
        "publisher forbids), which lands in known_broken_rules - so removing them from here on "
        "activation is coherent, not a loophole."
    ),
    "how_to_read_a_reason": (
        "Each entry names the DEFECT, not the symptom. A reason beginning 'unattributed - "
        "needs investigation' means the mechanism is written out but the cause is not "
        "established - it is a lead, not a shrug."
    ),
    "caution_on_unattributed": (
        "'Unattributed' can mean the question was framed too narrowly, not only that the "
        "evidence is thin. Worked example: boe_b0378 was recorded as 'c0060 is a signed "
        "outflow column, so of-which <= total inverts' - a real-looking question whose answer "
        "was neither limb offered, because the total should never have been negative at all "
        "(the carrier was uncapped, upstream of the sign question). Re-derive the framing "
        "before trusting an unattributed entry's framing."
    ),
    "caution_on_arithmetic_coincidence": (
        "Do not read an arithmetic coincidence as evidence of a mechanism. boe_b0752_22/24 "
        "were once attributed to a class-level figure being 'broadcast' onto every PD-grade "
        "row, on the evidence that the grade sum was exactly 7x the total across 7 grades. "
        "That is equally consistent with a genuine per-grade average whose inputs coincide - "
        "which is what it was. The decisive evidence was float dust (1672.9999999999995 on "
        "one row of seven): a broadcast constant would be bit-identical."
    ),
    "caution_on_plan_doc_definitions": (
        "A plan document naming a column as the DEFINITION of a basis is not evidence the "
        "column implements it. Worked example: docs/plans/phase7-declarative-reporting.md's "
        "F3 decision (the Pillar 3 CR4/CR5 tranche) cites 'C 07.00 col 0200 basis' as what "
        "'post-substitution' MEANS - it assumed col 0200 already carried that basis, not that "
        "it should. That assumption was false at the time and broke v0308_m/boe_b0471/v8726_m/"
        "boe_b0556: C 07.00's own col 0200 summed EAD over the ORIGIN population (the F4 build "
        "never extended substitution-awareness to it), while CR4/CR5 (reporting/pillar3/cr4.py, "
        "cr5.py) keyed the post-substitution `reporting_class` they cite the same definition "
        "for - so two parts of the estate that cite one shared basis were inconsistent. "
        "RESOLVED: C 07.00 col 0200/0220 (and the C 08.01 / C 09.02 cousins) were rebound to "
        "the post-substitution population, col 0200 now reads Sum(ead_col) over that basis, and "
        "the four rules were removed from this register. Retained as the lesson: verify a "
        "definition is IMPLEMENTED before citing it as evidence a related gap is a deliberate "
        "decision rather than a build shortfall."
    ),
    "pattern_boe_summation_templates": (
        "The BoE summation rules do not distinguish ADDITIVE columns from AVERAGED ones. "
        "'r0070 = sum(grade rows)' is applied across all ~36 columns of OF 08.01/08.02, "
        "including exposure-weighted averages, where it cannot hold unless there is exactly "
        "one grade row. Same shape as boe_b0779 on OF 08.07 c0050 (publisher issue PI-23). "
        "Recognise it before re-deriving it again. (This note once also counted the CRR C 08.06 "
        "risk-weight column as an instance; it is not one: column 0070 is not a data point, the "
        "EBA's rules never reach it, and only our binding evaluated it - design record O-14.) "
        "PUBLISHER "
        "CONFIRMATION (BoE taxonomy v4.1.1, Aug 2026): of the 35 boe_b0752_* members the BoE "
        "withdrew exactly the four on averaged columns - _1 (c0010 PD), _22/_23 (c0230/c0240 "
        "LGD), _24 (c0250 maturity) - and rewrote the weighted restatements boe_b0755-0758 into "
        "the per-grade paired form sum(avg * exposure), marking them not-in-XBRL."
    ),
    "pattern_empty_subrow_vs_negated_column": (
        "An inequality between an 'of which' sub-row and its parent inverts when the parent "
        "is a genuinely negative Annex II Sec.1.3 '(-)' deduction column and the sub-row's own "
        "subset is empty: our empty-subset convention renders the sub-row ALL-NULL, the "
        "evaluator coalesces that null to 0.0 for the comparison, and 0 <= a negative number "
        "reads false however correct that negative figure is. See the caution on unattributed "
        "entries above before assuming the parent's negative figure is itself the bug, as it "
        "genuinely was in the boe_b0378 worked example there. This note once named a "
        "'zero-exposure ratio family' as the same shape; that family was not the publisher's: "
        "the OF 08.07 share rules (boe_b0778, and its CRR twin v09796_m) broke on empty roll-out "
        "rows only because the template-level engine read a share nobody reported as 0.0 - the "
        "XBRL formula skips such a place, and since O-03a / O-14b the template-level engine "
        "does too (design record O-03) - and the CRR C 08.06 total rows only because our "
        "binding evaluated a column that "
        "is not a data point (design record O-14). PUBLISHER "
        "CONFIRMATION (BoE taxonomy v4.1.1, Aug 2026): boe_b0378/boe_b0379 were each split into "
        "a _1 rule (of-which <= total on the positive columns) and a _2 rule (total <= of-which "
        "on the '(-)' deduction columns), and both _2 rules PASS on real coordinates on "
        "crm-substitution (5 and 3) where the unsplit rules failed."
    ),
    # Hand-written into the JSON on 2026-08-xx and dropped by the next REGEN because
    # it lived only there; moved here (verbatim) on 2026-09-05 so regeneration keeps it.
    "pattern_non_additive_columns_in_summation_rules": (
        "The BoE summation rules are COLUMN-AGNOSTIC: 'total row = sum(breakdown rows)' is "
        "applied across every column of the table, including columns that are not additive "
        "across those rows. This is the same family as notes.pattern_boe_summation_templates "
        "but a STRICTER form, because it cannot be satisfied by any portfolio rather than only "
        "by a single-row one. Two column kinds are affected on OF 08.01: c0300 = "
        "Count(counterparty_reference, distinct=True) and c0250 = WeightedAvg(irb_maturity_m, "
        "weight=ead). A DISTINCT COUNT counts an obligor once on the total row and once in EACH "
        "breakdown row it appears in, so the row sum exceeds the total whenever one obligor "
        "holds legs on both balance-sheet sides. Measured on reporting/irb-shapes/b31, C 08.01 "
        "corporate: c0300 total = 3 distinct obligors, on-BS row = 3, off-BS row = 1 -> row sum "
        "4 vs total 3. c0250 total = 1673.0, on-BS = 1673.0, off-BS = 1673.0 -> row sum 3346 vs "
        "total 1673. Our figures are correct on their own definitions in both cases. This "
        "surfaced only when the irb-shapes portfolio arrived because it is the FIRST portfolio "
        "in the estate where a single obligor spans both the on- and off-balance-sheet rows, "
        "which is inherent to covering IRB off-balance-sheet exposure at all. BoE taxonomy "
        "v4.1.1 (Aug 2026) withdrew the rule this was measured on, boe_b0744, together with its "
        "IRB-axis twin boe_b0745; the EBA restatement v0338_m still binds the CRR template. Live "
        "members in v4.1.1, each with its evidence in the publisher-issue register: boe_b0742 "
        "across the conversion-factor rows (PI-07), boe_b0748 across the AIRB class sheets "
        "(PI-31; on our returns it broke only because we reported a maturity on a retail sheet, "
        "which design record O-10 removed) and obligor counts across exposure-type rows (PI-08)."
    ),
    "pattern_standardised_equity_transitional_below_the_row_weight": (
        "PUBLISHER ISSUE PI-01, not our defect (LESSONS C5). PS1/26 Annex II p.95 puts equity "
        "under the Credit Risk: General Provisions rules 4.1-4.10 transitional on the row of its "
        "Article 133 weight - 'reported against the risk weights set out in Article 133 [...] "
        "disregarding the transitional provisions. However, the RWEA shall still reflect the "
        "transitional provisions' - and p.96 names rows 0250 / 0261. Rules 4.2 / 4.3 assign a "
        "firm without IRB permission 160/190/220% and 220/280/340% in 2027/2028/2029, every one "
        "BELOW the row weight. So on b31/equity-transitional (the first registered book with such "
        "equity) a correct return breaks boe_b1016 / boe_b1031 (ERROR, Total sheet: RWEA >= 2.5x "
        "/ 4x exposure value on rows 0250 / 0261) and boe_b0491 / boe_b0506 (WARNING, class "
        "sheets incl. 0016: RWEA = 2.5x / 4x); the boe_b0491 label ('RWEA shall only exceed 250% "
        "of exposure value if an Equities Transitional Approach is being applied') shows the "
        "rules expected the transitional to RAISE RWEA only. Arelle agrees with rwa_filer.boe on "
        "all four. As published, boe_b0710_2 (ERROR, rows 0371-0374: c0150 = the sum of the "
        "off-balance-sheet conversion-factor columns 0160-0190) would fail there too - an equity "
        "holding is on-balance-sheet, so a filled memorandum row has c0150 and nothing to break "
        "it down into (publisher issue PI-22) - but the Bank's validations deny list deactivated "
        "the whole boe_b0710 family from 19 October 2026 (known issue 22), so neither engine "
        "evaluates it and it is in no section of this register. The only placement that passes "
        "the four is row 0280 'Other risk weights', which contradicts p.95-96 and fails the "
        "Bank's own boe_b0458 on sheet 0016. Do NOT move figures to satisfy any of the four; the "
        "fix belongs to the publisher."
    ),
}


#: The reporting date of every STANDARDISED run, per framework. A portfolio whose
#: maturities are stated relative to the reporting date is built with the same one.
_SA_REPORTING_DATE: dict[str, date] = {"CRR": date(2025, 12, 31), "BASEL_3_1": date(2027, 6, 1)}


def _sa_config(framework: str) -> CalculationConfig:
    """STANDARDISED config, matching the off-BS and CCR goldens.

    C 07.00 is the SA template and its CCF-bucket columns are defined over the
    Art. 111 / PS1/26 Table A1 schedule; an F-IRB conversion factor has no bucket
    on this template to land in.
    """
    if framework == "CRR":
        return CalculationConfig.crr(
            reporting_date=_SA_REPORTING_DATE[framework],
            permission_mode=PermissionMode.STANDARDISED,
        )
    return CalculationConfig.basel_3_1(
        reporting_date=_SA_REPORTING_DATE[framework], permission_mode=PermissionMode.STANDARDISED
    )


def _irb_config(framework: str) -> CalculationConfig:
    """IRB config, matching the IRB-classes goldens.

    ``enforce_retail_granularity=False`` on the Basel 3.1 arm, exactly as the rich
    portfolio does (the production default since RE-04). Electing the optional
    0.2%-of-portfolio test (BCBS CRE20.66, not a PS1/26 limb) would fail every
    natural-person row of a compact oracle portfolio as regulatory retail, and the
    QRRE sheet would vanish — silently undoing the C 08.xx sheet-axis coverage
    this portfolio exists for.

    Deliberately not sharing ``test_reporting_golden``'s helpers even though the
    two are currently identical: a change made for the rich portfolio must not
    silently re-point these runs at a different estate than their goldens.
    """
    if framework == "CRR":
        return CalculationConfig.crr(
            reporting_date=date(2025, 12, 31), permission_mode=PermissionMode.IRB
        )
    return CalculationConfig.basel_3_1(
        reporting_date=date(2027, 6, 1),
        permission_mode=PermissionMode.IRB,
        enforce_retail_granularity=False,
    )


def _prior_config(framework: str) -> CalculationConfig:
    """The same IRB config at an EARLIER reference date, for C 08.04's opening balance.

    C 08.04 reports RWEA *flows* — COREP Annex II §3.3.6.1 ¶79 defines them as the
    change between the reference date and the PRIOR reference date — so without a
    prior frame rows 0010-0080 are null by construction and the flow identity
    cannot be evaluated at all. Supplying one is a harness obligation, not a
    template fix.

    A genuinely earlier date rather than the same frame re-passed: maturities
    differ, so the opening balance is a real prior figure and the residual is
    non-zero, rather than a fiction asserting nothing moved in the period.
    """
    if framework == "CRR":
        return CalculationConfig.crr(
            reporting_date=date(2025, 6, 30), permission_mode=PermissionMode.IRB
        )
    return CalculationConfig.basel_3_1(
        reporting_date=date(2027, 1, 1),
        permission_mode=PermissionMode.IRB,
        enforce_retail_granularity=False,
    )


class GateInput(NamedTuple):
    """One run of the gate: a portfolio through one regime.

    ``build_prior_config`` is set only on the runs that emit C 08.04 — the
    IRB-permission ones. The SA-only portfolios emit no IRB template, so a prior
    frame there would buy nothing and cost a pipeline run.
    """

    regime: str
    framework: str
    portfolio: str
    build_bundle: Callable[[], RawDataBundle]
    build_config: Callable[[], CalculationConfig]
    build_prior_config: Callable[[], CalculationConfig] | None = None


#: The runs, each the sole reachability route for a family of published
#: rules. See "Cost, and why every run is load-bearing" in the module docstring
#: before trimming this list — a dropped run does not make its rules pass, it
#: makes them NOT_EVALUATED, which reads the same on the error channel.
#:
#: This comment used to state a count: "sixteen", stale from the day ``art199`` and
#: ``irb-shapes`` were registered, then "twenty" while the tuple reached
#: thirty-one. It states none now. Count the tuple, not the prose.
#:
#: The last four were added with the real-estate carrier-conservation batch. They
#: are registered here rather than left as standalone acceptance fixtures because
#: LESSONS B5 requires it without qualification: a fixture that exercises a
#: previously-dead column must enter the gated population, or the batch
#: demonstrates the trap while reproducing it. Between them they light eight
#: columns this register previously never evaluated — C 07.00 col 0070 (Art. 222
#: Simple Method), the C 07.00 residential-mortgage sheet, Pillar 3 CR5 rows
#: 9f/9g, C 08.01 cols 0200/0210 and CR7-A cols e/f (Art. 199 receivables and
#: other-physical collateral). ``scripts/check_template_cell_coverage.py`` reads
#: this tuple verbatim, so registration also moves them inside the cell-coverage
#: ratchet with no edit to that script.
#:
#: Registration also owes the run a golden. ``test_reporting_registered_goldens.py``
#: reads this tuple too and freezes every run whose portfolio has no golden module
#: of its own, from the entry's own builder and configs; its completeness test is
#: red until the new run's directory is banked (``REGEN_REGISTERED_GOLDENS=
#: <regime>/<portfolio>``, never a bulk regeneration).
RUNS: tuple[GateInput, ...] = (
    GateInput(
        "crr", "CRR", "rich", build_reporting_bundle, _crr_config, lambda: _prior_config("CRR")
    ),
    GateInput(
        "b31",
        "BASEL_3_1",
        "rich",
        build_reporting_bundle,
        _b31_config,
        lambda: _prior_config("BASEL_3_1"),
    ),
    GateInput("crr", "CRR", "off-bs", build_reporting_offbs_bundle, lambda: _sa_config("CRR")),
    GateInput(
        "b31", "BASEL_3_1", "off-bs", build_reporting_offbs_bundle, lambda: _sa_config("BASEL_3_1")
    ),
    GateInput("crr", "CRR", "ccr", build_reporting_ccr_bundle, lambda: _sa_config("CRR")),
    GateInput(
        "b31", "BASEL_3_1", "ccr", build_reporting_ccr_bundle, lambda: _sa_config("BASEL_3_1")
    ),
    GateInput(
        "crr", "CRR", "sa-classes", build_reporting_sa_classes_bundle, lambda: _sa_config("CRR")
    ),
    GateInput(
        "b31",
        "BASEL_3_1",
        "sa-classes",
        build_reporting_sa_classes_bundle,
        lambda: _sa_config("BASEL_3_1"),
    ),
    GateInput(
        "crr",
        "CRR",
        "irb-classes",
        build_reporting_irb_classes_bundle,
        lambda: _irb_config("CRR"),
        lambda: _prior_config("CRR"),
    ),
    GateInput(
        "b31",
        "BASEL_3_1",
        "irb-classes",
        build_reporting_irb_classes_bundle,
        lambda: _irb_config("BASEL_3_1"),
        lambda: _prior_config("BASEL_3_1"),
    ),
    GateInput(
        "crr",
        "CRR",
        "crm-substitution",
        build_reporting_crm_substitution_bundle,
        lambda: _irb_config("CRR"),
        lambda: _prior_config("CRR"),
    ),
    GateInput(
        "b31",
        "BASEL_3_1",
        "crm-substitution",
        build_reporting_crm_substitution_bundle,
        lambda: _irb_config("BASEL_3_1"),
        lambda: _prior_config("BASEL_3_1"),
    ),
    # RE loan-split: SA-bound by construction (the splitter passes IRB and
    # slotting legs through untouched), so no IRB permission and no prior frame.
    GateInput("crr", "CRR", "re-split", build_reporting_re_split_bundle, lambda: _sa_config("CRR")),
    GateInput(
        "b31",
        "BASEL_3_1",
        "re-split",
        build_reporting_re_split_bundle,
        lambda: _sa_config("BASEL_3_1"),
    ),
    # DELIBERATELY NOT REGISTERED: the ``fcsm`` portfolio
    # (tests/fixtures/reporting_funded_protection_portfolio.py). It exists, works,
    # and its acceptance test passes — but registering it here needs a config
    # electing the Art. 222 Financial Collateral SIMPLE Method, because the
    # Art. 191A election is not a parameter of ``_sa_config`` and that factory
    # defaults to ``comprehensive``. Registered against ``_sa_config`` the fixture
    # is in the gate while the one feature it exists to exercise is silenced:
    # C 07.00 col 0070 reads 0.00 under ``comprehensive`` and non-zero under
    # ``SIMPLE``, on the identical bundle.
    #
    # Registered CORRECTLY it exposes SIX breaks, TWO of them ERROR-severity
    # (boe_b0471 and v0308_m, both 4,000,000 vs 2,800,000) — which reject a
    # submission. Those are PRE-EXISTING on the Art. 222 path, not caused by the
    # carrier-conservation fix: on the unfixed engine the same rules break at
    # 4,450,000 / 3,800,000 vs 7,500,000 over 14 and 4 cells, and the fix reduces
    # them to 3 and 2 cells and clears v1659_m outright. It improves them
    # substantially and does not resolve them.
    #
    # One of the six was a REPORTING defect, fixed 2026-11-13: boe_b0555 (Basel
    # 3.1, {c0130} <= {c0140}) — C 07.00 col 0140 reported the Simple-Method
    # collateral's whole market value as a "volatility and maturity adjustment"
    # under a col 0130 of zero. Re-measured after that fix it exposes FIVE beyond
    # the estate-wide register entries: v0308_m (ERROR), v8726_m and e4895_n under
    # CRR, boe_b0471 (ERROR) and boe_b0556 under Basel 3.1. The col 0130 / 0140
    # behaviour of this book is asserted directly, without registration, by
    # tests/acceptance/reporting/test_c07_collateral_columns.py.
    #
    # Banking two submission-rejecting breaks is a regulatory-posture decision
    # that deserves its own review rather than riding on a carrier fix, so this
    # registration and the residual Art. 222 defect are filed together as one
    # Tier 1 item with the measured before/after above. Registering it is a
    # one-line change plus an operator-gated baseline regeneration.
    #
    # Note this is LESSONS B5 in a THIRD form: B5 began as "unregistered
    # portfolio", recurred as "registered portfolio, dead cell", and this is
    # "registered portfolio, wrong config, dead cell". Registration is necessary;
    # so is a live column; neither is sufficient if the config silences the
    # feature.
    # Art. 199 receivables / other-physical collateral — C 08.01 cols 0200/0210
    # and CR7-A cols e/f. IRB-only (Art. 199 is additional eligibility for firms
    # using own LGD estimates), so it takes an IRB permission and a prior frame
    # like the other IRB runs.
    GateInput(
        "crr",
        "CRR",
        "art199",
        build_reporting_art199_bundle,
        lambda: _irb_config("CRR"),
        lambda: _prior_config("CRR"),
    ),
    GateInput(
        "b31",
        "BASEL_3_1",
        "art199",
        build_reporting_art199_bundle,
        lambda: _irb_config("BASEL_3_1"),
        lambda: _prior_config("BASEL_3_1"),
    ),
    # IRB exposure SHAPES — the off-balance-sheet, large-financial-sector-entity,
    # defaulted-RWEA and Art. 200(1)(b) protection axes. IRB-permissioned with a
    # prior frame, like the other IRB runs.
    #
    # It is registered here for the reason LESSONS B5 states without
    # qualification, and the four clusters it reaches were dead for four DIFFERENT
    # reasons, only three of which were "no fixture":
    #   - no IRB obligor in the estate had an off-balance-sheet leg at all;
    #   - no obligor anywhere set ``apply_fi_scalar``;
    #   - no slotting obligor had an off-BS leg;
    #   - and the defaulted-RWEA cells were dead DESPITE a defaulted IRB obligor
    #     existing, because that row's RWEA is exactly 0.00 by construction. See
    #     the portfolio docstring — the baseline's stated reason for those three
    #     columns is wrong and this run is what corrects it.
    GateInput(
        "crr",
        "CRR",
        "irb-shapes",
        build_reporting_irb_shapes_bundle,
        lambda: _irb_config("CRR"),
        lambda: _prior_config("CRR"),
    ),
    GateInput(
        "b31",
        "BASEL_3_1",
        "irb-shapes",
        build_reporting_irb_shapes_bundle,
        lambda: _irb_config("BASEL_3_1"),
        lambda: _prior_config("BASEL_3_1"),
    ),
    # On-balance-sheet netting across a spanning agreement — LESSONS B5. C 07.00
    # col 0035 "(-) Adjustment due to on-balance sheet netting" was DEAD in every
    # registered run (``NO_FIXTURE``: no fixture supplies a netting agreement),
    # and this portfolio is what lights it. Its GROUP agreement is also the only
    # exercise anywhere in the estate of CROSS-counterparty netting: the three
    # other fixture files that set ``netting_agreement_reference`` at all put
    # every leg of their agreement under ONE counterparty, which nets identically
    # whichever perimeter key is in force.
    #
    # SA-only (five unrated corporates, no IRB obligor), so ``_sa_config`` and no
    # prior frame — same shape as the ``off-bs`` and ``sa-classes`` runs.
    GateInput("crr", "CRR", "netting", build_reporting_netting_bundle, lambda: _sa_config("CRR")),
    GateInput(
        "b31",
        "BASEL_3_1",
        "netting",
        build_reporting_netting_bundle,
        lambda: _sa_config("BASEL_3_1"),
    ),
    # Netting WITH a mismatch, beside genuine collateral — LESSONS B5 again, for
    # the cells the ``netting`` pair above cannot tell apart. Every leg there is in
    # one currency and matures on one date and the portfolio has no collateral
    # table, so a netted deposit's ADJUSTED value equals its allocation and
    # "financial collateral" and "netting" are the same money on every row. Until
    # 2026-11-13 OF 07.00 col 0130 was non-zero under Basel 3.1 on that portfolio
    # alone — and only because the deposit was deducted twice (escape log,
    # 2026-09-05). With the double count removed col 0130 is zero there, and
    # ``boe_b0555`` ({c0130} <= {c0140}) would be vacuous on every run. Here a
    # Basel 3.1 SA exposure carries GENUINE financial collateral in col 0130 and a
    # live col 0140, a deposit whose maturity mismatch makes col 0035 differ from
    # the allocation, and a loan with collateral and no netting.
    #
    # The builder takes the reporting date because its maturities are stated
    # relative to it, so each run binds its own with ``functools.partial`` (which
    # keeps the builder's name for the registration check). SA-only, no prior
    # frame. It introduced NO new supervisory break when registered — measured
    # then, every rule it broke was already an estate-wide register entry; read
    # the register, not this comment, for what each of them is now.
    GateInput(
        "crr",
        "CRR",
        "netting-mismatch",
        partial(build_netting_mismatch_bundle, _SA_REPORTING_DATE["CRR"]),
        lambda: _sa_config("CRR"),
    ),
    GateInput(
        "b31",
        "BASEL_3_1",
        "netting-mismatch",
        partial(build_netting_mismatch_bundle, _SA_REPORTING_DATE["BASEL_3_1"]),
        lambda: _sa_config("BASEL_3_1"),
    ),
    # Over-collateralised SA loans beside ordinary ones — LESSONS B5. No other
    # portfolio holds an SA exposure whose collateral EXCEEDS it, so C 07.00 /
    # OF 07.00 col 0130 summed every pledge whole and floored only the cell, and
    # one loan's unused collateral came off every other loan on the sheet: col
    # 0150 below col 0200 by the excess, in BOTH regimes (``boe_b0471`` /
    # ``boe_b0556``; the CRR form also through a deposit netted against a smaller
    # loan). The portfolio holds a leg the per-row cap must leave alone beside
    # the legs it moves, and an over-collateralised pledge with a maturity
    # mismatch, so col 0140 is live. Dates relative to the reporting date, so
    # ``functools.partial`` as above. SA-only, no prior frame.
    GateInput(
        "crr",
        "CRR",
        "over-collateralised",
        partial(build_over_collateralised_bundle, _SA_REPORTING_DATE["CRR"]),
        lambda: _sa_config("CRR"),
    ),
    GateInput(
        "b31",
        "BASEL_3_1",
        "over-collateralised",
        partial(build_over_collateralised_bundle, _SA_REPORTING_DATE["BASEL_3_1"]),
        lambda: _sa_config("BASEL_3_1"),
    ),
    # Facility share — a shared facility whose undrawn headroom is allocated to
    # one of three members by the firm-policy riskiest-member rule (FS-1). This
    # is the FIRST portfolio in the estate with a facility share at all: the
    # design's own scan of the generated fixtures found ZERO facilities with more
    # than one distinct child counterparty, which means every reporting cell the
    # allocation path can populate has been dead since the path was written
    # (LESSONS B5).
    #
    # BOTH variants of BOTH regimes, four runs. The pair differs in exactly one
    # input — the non-member anchor obligor's PD — and that single input decides
    # whether the Basel 3.1 output floor BINDS. That is the two-leg pattern B5
    # asks for on the C 07.00 50% risk-weight band row of the corporates sheet:
    # the solo facility's undrawn and a drawn loan sit in that row in EVERY cell
    # of the matrix, while the share's undrawn moves in and out of it as the
    # allocation moves between a standardised and a modelled member. A change
    # that ZEROED the row is therefore distinguishable from one that moved a row
    # out of it.
    #
    # ``crr/facility-share-nonbinding`` is NOT a duplicate of its binding twin
    # even though the CRR allocation is variant-invariant (the floor Feature is
    # off): the anchor's PD moves its C 08.03 PD band, so the two runs light
    # different rows of the IRB templates.
    #
    # These use the PORTFOLIO's OWN config helpers rather than ``_irb_config``,
    # and the difference is load-bearing. ``_irb_config`` passes
    # ``enforce_retail_granularity=False`` on its Basel 3.1 arm so a compact
    # oracle portfolio's natural-person rows stay retail; THIS portfolio has no
    # retail obligor at all, so the optional 0.2% granularity test decides nothing
    # here and the production default must stand. Cloning ``_irb_config`` would put
    # the portfolio inside the gate against a config that softens a feature its
    # own assertions describe — LESSONS B5's third form, registered with the
    # wrong config.
    #
    # All four are ``PermissionMode.IRB`` and therefore all four take a prior
    # frame, without which C 08.04's movement rows are null by construction and
    # every published rule over them stays NOT_EVALUATED — the fail-open shape.
    GateInput(
        "crr",
        "CRR",
        "facility-share-binding",
        lambda: build_facility_share_bundle("binding"),
        lambda: facility_share_config("CRR"),
        lambda: facility_share_prior_config("CRR"),
    ),
    GateInput(
        "crr",
        "CRR",
        "facility-share-nonbinding",
        lambda: build_facility_share_bundle("nonbinding"),
        lambda: facility_share_config("CRR"),
        lambda: facility_share_prior_config("CRR"),
    ),
    GateInput(
        "b31",
        "BASEL_3_1",
        "facility-share-binding",
        lambda: build_facility_share_bundle("binding"),
        lambda: facility_share_config("BASEL_3_1"),
        lambda: facility_share_prior_config("BASEL_3_1"),
    ),
    GateInput(
        "b31",
        "BASEL_3_1",
        "facility-share-nonbinding",
        lambda: build_facility_share_bundle("nonbinding"),
        lambda: facility_share_config("BASEL_3_1"),
        lambda: facility_share_prior_config("BASEL_3_1"),
    ),
    # Row-level exposure-class scope — the first portfolio in the estate that can
    # VIOLATE one. C 07.00 row 0040 is scoped by Annex II to exposure class (i)
    # ("Only reported in exposure class 'Secured by mortgages on immovable
    # property'") and the engine carries that as a sheet term; on the fourteen
    # runs above, stripping the term changes NOTHING, because the RE splitter puts
    # every residential-property-secured leg on the real-estate sheet and leaves
    # the corporate residual with ``property_type`` NULL. Measured: the three
    # suites that would be expected to see it — this register, the Art. 112 class
    # axis and the RE-split coverage file — score 61 passed / 2 xfailed in BOTH
    # states, with the mutation confirming it applied
    # (``tests/mutations/mutate_row_0040_is_not_sheet_scoped``).
    #
    # So this is LESSONS B5's FOURTH form, and the first that is not about a dead
    # cell: row 0040 column 0010 is LIVE on ``crr/rich`` and ``crr/re-split``, so
    # neither the cell-coverage census nor ``RUNS`` registration of an existing
    # portfolio could have caught it. What was dead is the row's NEGATIVE space —
    # the (sheet, row) pairs where it must publish nothing — and ``{r0040} =
    # empty`` can only be evaluated where something could have been reported.
    # ``v7477_m`` / ``v7478_m`` sit in the known-breaks register as VACUOUS on all
    # fourteen runs for exactly that reason.
    #
    # SA-only and no prior frame, like ``off-bs`` / ``sa-classes`` / ``netting``:
    # the portfolio supplies no model permissions at all, so no permission mode
    # could route a leg to IRB and leave the SA template empty. It introduced NO
    # new supervisory break when registered — measured then, every rule it broke
    # was already in the register as an estate-wide pattern entry; read the
    # register, not this comment, for what each of them is now.
    GateInput(
        "crr", "CRR", "row-scope", build_reporting_row_scope_bundle, lambda: _sa_config("CRR")
    ),
    GateInput(
        "b31",
        "BASEL_3_1",
        "row-scope",
        build_reporting_row_scope_bundle,
        lambda: _sa_config("BASEL_3_1"),
    ),
    # Class (p) equity of a firm WITHOUT IRB permission in 2027 — LESSONS B5. The
    # first registered book whose equity takes the PS1/26 Credit Risk: General
    # Provisions rule 4.2 / 4.3 weights (160% / 220%) instead of its Article 133
    # weight, so the first in which OF 07.00 rows 0250 / 0261 carry a
    # transitional RWEA (Annex II p.95: reported against the Article 133 row,
    # "the RWEA shall still reflect the transitional provisions"), row 0280 must
    # stay empty on sheet 0016 (``boe_b0458``), and memorandum rows 0371 / 0372
    # are populated. Every earlier run held no direct equity or held it under an
    # IRB permission, so ``boe_b0710_2`` sat VACUOUS and rows 0371-0374 were null
    # estate-wide. Two legs move (listed; unlisted under five years) and two
    # must not (Art. 133(5) subordinated debt; an Art. 133(6)(c) holding). Five
    # more pair the Art. 133 weight chain's edges (P1.207 / P1.393): speculative
    # flags that do and do not survive the Glossary test, young
    # government-supported equity, and a higher-risk Art. 133(6)(c) holding.
    #
    # Basel 3.1 only: CRR has no transitional. SA-only, no prior frame. A
    # CORRECT return of this book breaks four Bank rules the register banks as
    # rule limits, never figures to bend — see REGISTER_NOTES
    # ``pattern_standardised_equity_transitional_below_the_row_weight``.
    GateInput(
        "b31",
        "BASEL_3_1",
        "equity-transitional",
        build_reporting_equity_transitional_bundle,
        lambda: _sa_config("BASEL_3_1"),
    ),
    # The risk-weight ladder — LESSONS B5 on the row (y) axis of C 07.00 / OF
    # 07.00. Each rows 0140-0280 rung carries an identity, RWEA = exposure value x
    # the row's weight, and a rung no run reaches holds that identity at 0 = 0.
    # Before this book, every run above left these rungs dark: Basel 3.1 15%,
    # 25%, 40%, 45%, 65%, 80%, 105%, 130% and 135%, and CRR 250% and 1250%. The
    # class weights behind them (SCRA grade A, unrated covered bonds, the
    # Art. 122(6) corporate split, project-finance phases, the QRRE transactor,
    # Art. 124G whole-loan bands, an Art. 48(4) holding, a CIU on the fallback)
    # appear in no other book. One leg per rung, each unsplit and at exactly its
    # rung's weight.
    #
    # It uses the PORTFOLIO's config, not ``_sa_config``, and the difference is
    # load-bearing: ``rw_ladder_config`` elects Art. 122(6) under Basel 3.1.
    # Without the election both corporate legs take the flat 100% and the 65% /
    # 135% rows go dark: B5's third form, registered with the wrong config.
    # SA-only, no prior frame. Measured when registered: it adds no broken rule
    # outside the register in either regime. The legs it leaves out (70% life
    # insurance, 110%, currency mismatch, 4%, the class-sheet twins) and why are
    # in the portfolio docstring.
    GateInput(
        "crr", "CRR", "rw-ladder", build_reporting_rw_ladder_bundle, lambda: rw_ladder_config("CRR")
    ),
    GateInput(
        "b31",
        "BASEL_3_1",
        "rw-ladder",
        build_reporting_rw_ladder_bundle,
        lambda: rw_ladder_config("BASEL_3_1"),
    ),
    # A CRR IRB non-named multilateral development bank — LESSONS B5 (P1.366). The
    # first registered book holding one: CRR Art. 147(4)(c) puts it in the IRB
    # INSTITUTIONS class, and while no portfolio here held one the reporting
    # projection published its Art. 112 SA label ``mdb`` on every IRB template —
    # a C 08.01-08.05 ``mdb`` sheet no sheet code addresses, C 09.02 row 0020
    # short of row 0150 (``v6052_m``, ERROR), C 02.00 rows 0250 / 0310 stranding
    # the MDB RWEA outside rows 0270 / 0330 — with every gate green. Two-leg
    # (a genuine institution beside the MDBs), with a mandatory A-IRB MDB leg
    # (row 0330), an IRB-guarantor slice that must stay in its guarantor's class,
    # and an SA MDB that must stay on C 07.00's ``mdb`` sheet.
    #
    # CRR only, IRB-permissioned with a prior frame: under PS1/26 Art. 147(3)(f) +
    # 147A(1)(a) every MDB is Standardised, so the Basel 3.1 arm has no case and is
    # asserted as a negative control in
    # tests/acceptance/reporting/test_p1_366_crr_irb_mdb_institution_rows.py
    # rather than registered — the same one-regime shape as ``equity-transitional``.
    # An SA config would silence the classifier Feature that creates the
    # population (LESSONS B5, third form).
    GateInput(
        "crr",
        "CRR",
        "irb-mdb",
        build_reporting_crr_irb_mdb_bundle,
        lambda: _irb_config("CRR"),
        lambda: _prior_config("CRR"),
    ),
    # A DECLINED SA-routed guarantee on an IRB off-balance-sheet leg — LESSONS B5,
    # P1.398. The CRM stage puts the covered undrawn amount of such a leg on the SA
    # conversion factor before the IRB stage decides whether to recognise the
    # guarantee, and a declined guarantee must leave the leg on its own IRB
    # exposure value (CRR Art. 166(8)-(10), PS1/26 Art. 166A-166D). Measured over
    # every run above before this one was registered: ZERO IRB legs with an
    # SA-routed guarantor and an off-balance-sheet amount, in either regime, so no
    # register cell could see C 08.01 / OF 08.01 col 0110 or RWEA move. Three
    # declined obligors (an F-IRB commitment that moves under CRR only, an A-IRB
    # own-CCF commitment that moves in both, a CRR short-term trade LC that moves
    # DOWN) and one recognised guarantee whose SA factor must SURVIVE (the two-leg
    # rule). IRB permission and a prior frame, like the other IRB runs.
    GateInput(
        "crr",
        "CRR",
        "declined-guarantee",
        build_reporting_declined_guarantee_bundle,
        lambda: _irb_config("CRR"),
        lambda: _prior_config("CRR"),
    ),
    GateInput(
        "b31",
        "BASEL_3_1",
        "declined-guarantee",
        build_reporting_declined_guarantee_bundle,
        lambda: _irb_config("BASEL_3_1"),
        lambda: _prior_config("BASEL_3_1"),
    ),
    # Short-dated slotting legs — LESSONS B5. Until P1.204 no registered run held a
    # slotting leg with less than 2.5 years to maturity in EITHER regime, so the
    # C 08.06 / OF 08.06 short-maturity rows (0010, 0030, 0050, ..., 0110) and the
    # CR10 short rows (1, 3, 5, ..., 11) were dead estate-wide, and P1.204's re-key
    # of those rows on the band a leg is weighted in (PS1/26 Art. 153(5)(d): column
    # A / C only on the firm's election) was invisible to this register and both
    # ratchets. THREE runs because the band has three states: CRR (Table 1's
    # short row is mandatory), Basel 3.1 without the election (short Strong / Good
    # on the column B / D rows, short Satisfactory still on its short row) and
    # Basel 3.1 with it. Two legs move between rows across the states and two must
    # not (see the portfolio docstring), so an emptied row is distinguishable from
    # a moved leg. Its own config helpers, not ``_irb_config``: the book has no
    # retail obligor and the election is not a parameter of that helper; IRB
    # permission, so each run takes a prior frame for C 08.04.
    GateInput(
        "crr",
        "CRR",
        "slotting-maturity",
        partial(build_reporting_slotting_maturity_bundle, SLOTTING_MATURITY_DATE["CRR"]),
        lambda: slotting_maturity_config("CRR"),
        lambda: slotting_maturity_prior_config("CRR"),
    ),
    GateInput(
        "b31",
        "BASEL_3_1",
        "slotting-maturity",
        partial(build_reporting_slotting_maturity_bundle, SLOTTING_MATURITY_DATE["BASEL_3_1"]),
        lambda: slotting_maturity_config("BASEL_3_1"),
        lambda: slotting_maturity_prior_config("BASEL_3_1"),
    ),
    GateInput(
        "b31",
        "BASEL_3_1",
        "slotting-maturity-elected",
        partial(build_reporting_slotting_maturity_bundle, SLOTTING_MATURITY_DATE["BASEL_3_1"]),
        lambda: slotting_maturity_config("BASEL_3_1", elected=True),
        lambda: slotting_maturity_prior_config("BASEL_3_1", elected=True),
    ),
    # Defaulted standardised populations — LESSONS B5, P5.80. Until this book the
    # matrix's ONE defaulted SA leg was ``rich``'s unprovisioned, unguaranteed
    # corporate at 150%, so C 07.00 / OF 07.00 row 0320 carried that one leg, row
    # 0300 was null estate-wide, c0030 on both was never a figure (``boe_b0733_1``
    # and its CRR twin ``v2040_s`` VACUOUS everywhere), no non-corporate memo sheet
    # was reached, and no registered run emitted the Basel 3.1 high-risk sheet
    # (``boe_b0264`` and every sheet-0012 rule unevaluated). This book holds
    # provisioned defaults either side of the Art. 127(1) 20% threshold on the
    # CGCB / RGLA / PSE / institution / retail sheets, a guaranteed default (the
    # ``63c3b5c`` memorandum composition), a real-estate-origin default at 100%
    # under Art. 127(3) despite a 5% provision (Basel 3.1: on the Total only, known
    # issue #27) and, under Basel 3.1 only, a defaulted high-risk leg beside a
    # performing one and a guaranteed Art. 124F loan split (the ``rw_parts``
    # substituted route). The guaranteed default's protector is a
    # CQS 2 institution, at a non-zero weight in both regimes, so the RWEA crossing
    # to it is a figure (LESSONS C2). Registering it added NO Error-severity break;
    # its one new rule break is ``boe_b0350`` (WARNING), publisher issue PI-28 — read
    # the register, not this comment, for what each is now.
    #
    # The builder takes the framework: CRR has no high-risk class and no loan split,
    # so its book leaves those legs out (the fixture's docstring). It does hold the
    # real-estate-origin default, which CRR Art. 127(3) weights at exactly 100% (the
    # loan is secured whole within Art. 125's 80%). ``functools.partial`` keeps the
    # builder's name for the registration check. Under CRR the memo rows are still
    # keyed on the APPLIED class (the open CRR half of P1.377), so the CRR run lights
    # the "in default" sheet and the Total only. SA-only, no prior frame.
    GateInput(
        "crr",
        "CRR",
        "default-populations",
        partial(build_reporting_default_populations_bundle, "CRR"),
        lambda: _sa_config("CRR"),
    ),
    GateInput(
        "b31",
        "BASEL_3_1",
        "default-populations",
        partial(build_reporting_default_populations_bundle, "BASEL_3_1"),
        lambda: _sa_config("BASEL_3_1"),
    ),
    # The PS1/26 Art. 122(8)(b) output-floor election WITHOUT the Art. 122(6) SA
    # permission (P1.475) — LESSONS B5. The first registered book with an IRB leg
    # assessed investment grade: the only other book assessing an obligor
    # investment grade, ``rw-ladder``, is SA-only, so OF 08.01 row 0200 "Of
    # which: investment grade" was dead on every run. Two unrated F-IRB legs (one assessed IG, one not: row 0190 holds
    # both, row 0200 only the first), two IG-assessed F-IRB legs whose weight
    # another rule sets (an Art. 122(11) SME, an Art. 133(5) subordinated loan:
    # row 0200 must leave both out), and an IG-assessed SA leg that must stay at
    # the Art. 122(5) 100%. It takes its OWN config — the election is not a
    # parameter of ``_irb_config``, and registered against it the book would be
    # in the gate with the feature it exists for switched off (B5's third form).
    # IRB-permissioned, so it takes a prior frame. Basel 3.1 only: CRR Art. 122
    # has no investment-grade approach.
    GateInput(
        "b31",
        "BASEL_3_1",
        "ig-election",
        build_reporting_ig_election_bundle,
        ig_election_config,
        ig_election_prior_config,
    ),
    # The QRRE per-individual aggregate (CRR Art. 154(4)(c) / PS1/26 Art.
    # 147(5A)(c)) — LESSONS B5, fourth form. ``irb-classes`` keeps the QRRE sheets
    # live, but its one QRRE row is a single leg drawn to its limit, so with the
    # P1.320 one-limit-per-facility dedupe reverted (or over-applied as a per-
    # individual ``max``, copied as the ``attributes.py`` line-count divide, or
    # keyed on the first ROW of a facility) no exposure in any run above changes
    # class — measured on all thirty-six, rebased 2026-11-24, under each of the
    # four ``tests/mutations/mutate_qrre_aggregate_*`` plugins. This
    # portfolio holds a mover with a headroom leg, a survivor, a pair of
    # facilities past the cap together, and two facilities whose legs differ in
    # candidacy (one with the candidate leg first, a multi-option root with it
    # second); ``test_qrre_headroom_reporting.py`` asserts the sheet each lands
    # on. A-IRB retail, so ``_irb_config`` (whose Basel 3.1 arm keeps the
    # optional retail granularity test off, without which the QRRE sheet
    # vanishes) and a prior frame for C 08.04.
    GateInput(
        "crr",
        "CRR",
        "qrre-headroom",
        build_reporting_qrre_headroom_bundle,
        lambda: _irb_config("CRR"),
        lambda: _prior_config("CRR"),
    ),
    GateInput(
        "b31",
        "BASEL_3_1",
        "qrre-headroom",
        build_reporting_qrre_headroom_bundle,
        lambda: _irb_config("BASEL_3_1"),
        lambda: _prior_config("BASEL_3_1"),
    ),
    # Qualifying revolving retail under MULTI-OPTION facilities — LESSONS B5,
    # P1.355 (the P5.54 shape). The estate's only QRRE leg before this book was a
    # single facility drawn to its limit (``irb-classes``): no headroom leg and no
    # umbrella, so the per-individual aggregate (CRR Art. 154(4)(c) / PS1/26
    # Art. 147(5A)(c)) could not move a reported cell — neither P1.320's
    # leg-multiplication fix nor P1.355's umbrella cap. Here a fully drawn
    # umbrella's two loans move from the other-retail to the QRRE sheet of
    # C 08.01 / OF 08.01 under the cap, while a headroom-bearing QRRE obligor and
    # two other-retail owners of one shared umbrella survive on their sheets (the
    # two-leg rule; the shared owners also go red under a cap pooled across an
    # umbrella's owners). ``_irb_config`` is the right config here, not a
    # softening: the book is retail-only and too thin for the optional 0.2%
    # granularity test, exactly like ``irb-classes``. IRB permission, so each run
    # takes a prior frame for C 08.04.
    GateInput(
        "crr",
        "CRR",
        "qrre-mof",
        build_reporting_qrre_mof_bundle,
        lambda: _irb_config("CRR"),
        lambda: _prior_config("CRR"),
    ),
    GateInput(
        "b31",
        "BASEL_3_1",
        "qrre-mof",
        build_reporting_qrre_mof_bundle,
        lambda: _irb_config("BASEL_3_1"),
        lambda: _prior_config("BASEL_3_1"),
    ),
    # A core-UK-group member's INDIVIDUAL return — LESSONS B5 (P1.364). The first
    # registered run that sets ``reporting_entity`` / ``reporting_basis`` at all:
    # the CRR / PS1/26 Art. 113(6) intragroup 0% fires only on a scoped
    # individual-basis run, so until this run every cell the permission writes was
    # dead estate-wide. It lights row 0140 (0%) of the C 07.00 / OF 07.00
    # institutions and corporates sheets (intragroup loans) and that row's column
    # 0210 "of which: arising from CCR" (an intragroup SA-CCR netting set on both
    # sheets and an intragroup SFT on the institutions sheet — P1.364 extended the
    # permission to counterparty credit risk), beside external controls at 100%
    # and a subordinated intragroup loan that the own-funds carve-out keeps at its
    # class weight (CRR) / the Art. 133(5) 150% (Basel 3.1). The Bank's PI-05
    # rules close those 0% cells, so a CORRECT Basel 3.1 return of this book
    # breaks boe_b0440 / boe_b0440_1 (institutions) and boe_b0441 / boe_b0441_1
    # (corporates) at the gateway as WARNINGs: publisher issue PI-05, never
    # figures to bend (Annex II paras 66-68 and 126).
    #
    # It is also the first registered book holding an SFT at all, so it is the
    # first run to populate row 0090 ("securities financing transactions netting
    # sets"): measured when registered, it brings CRR v0314_m and Basel 3.1
    # boe_b0531 / boe_b0531_1 / boe_b0892 from VACUOUS-only to PASS, and CRR
    # v6072_i / v6078_i / v6079_i / v6096_i (row 0090 col 0200 = col 0210) to a
    # first verdict.
    #
    # Its OWN config, not ``_sa_config``, and the difference is load-bearing:
    # ``_sa_config`` leaves the run unscoped, and every leg would take its full
    # weight (B5's third form, registered with the wrong config). SA-only, no
    # prior frame; dates relative to the reporting date, bound per regime with
    # ``functools.partial``.
    GateInput(
        "crr",
        "CRR",
        "intragroup",
        partial(build_reporting_intragroup_bundle, INTRAGROUP_DATE["CRR"]),
        lambda: intragroup_config("CRR"),
    ),
    GateInput(
        "b31",
        "BASEL_3_1",
        "intragroup",
        partial(build_reporting_intragroup_bundle, INTRAGROUP_DATE["BASEL_3_1"]),
        lambda: intragroup_config("BASEL_3_1"),
    ),
)


# ---------------------------------------------------------------------------
# The output-floor state census, banked over RUNS
# ---------------------------------------------------------------------------
# See "Why there is an output-floor state census" in the module docstring. Both
# constants are held two-way by legs (n) and (p): a run or a shape that joins or
# leaves a state fails until the constant is edited, with the reason, in the
# same change.

#: The Basel 3.1 runs of ``RUNS`` whose engine output floor binds — a SET, never a
#: count (LESSONS B8), so one run starting to bind while another stops is two
#: findings rather than a net zero. The facility-share pair differ in one input,
#: the non-member anchor obligor's PD, and that input decides the state
#: (``tests/fixtures/facility_share_portfolio.py``).
BINDING_FLOOR_RUNS: frozenset[str] = frozenset({"b31/facility-share-binding"})

_MODELLED_APPROACHES = (
    ApproachType.FIRB.value,
    ApproachType.AIRB.value,
    ApproachType.SLOTTING.value,
)
_RETAIL_CLASSES = (
    ExposureClass.RETAIL_MORTGAGE.value,
    ExposureClass.RETAIL_QRRE.value,
    ExposureClass.RETAIL_OTHER.value,
)

#: The row shapes of the floored book the census looks for, each a predicate on
#: the sealed ledger. A binding floor's shortfall is spread over the
#: floor-eligible rows (``engine/aggregator/_floor.py``: IRB, slotting and the
#: CCR-routed standardised rows, PS1/26 Art. 92(3A)); the last five are the
#: shapes the escape log (2026-11-16) found no registered run had put in the
#: binding state. ``defaulted`` and ``lfse`` count on modelled rows only: a
#: defaulted or financial-sector STANDARDISED leg is not in the floored book.
#: ``lfse`` reads ``cp_apply_fi_scalar``, the carrier OF 08.01's
#: large-financial-sector-entity rows read (``reporting/corep/c08.py``); ``ccr``
#: is ``SA_CCR_APPROACH``, which tags SA-CCR derivatives and FCCM SFTs alike.
FLOOR_SHAPES: dict[str, pl.Expr] = {
    "foundation_irb": pl.col("approach_applied") == ApproachType.FIRB.value,
    "advanced_irb_retail": (pl.col("approach_applied") == ApproachType.AIRB.value)
    & pl.col("exposure_class").is_in(_RETAIL_CLASSES),
    "slotting": pl.col("approach_applied") == ApproachType.SLOTTING.value,
    "defaulted": pl.col("approach_applied").is_in(_MODELLED_APPROACHES) & pl.col("is_defaulted"),
    "lfse": pl.col("approach_applied").is_in(_MODELLED_APPROACHES) & pl.col("cp_apply_fi_scalar"),
    "ccr": pl.col("approach_applied") == SA_CCR_APPROACH,
}

#: The ``FLOOR_SHAPES`` each floor state reaches across ``RUNS``.
#:
#: The binding state OWES five of the six. Its one run holds three F-IRB
#: corporate legs and nothing else (``facility_share_portfolio.py``: no retail,
#: slotting, CCR, defaulted or financial-sector obligor), so every published rule
#: over a slotting, A-IRB retail, defaulted, LFSE or CCR row has been evaluated
#: only with the floor slack — the shape of the ``boe_b0751`` / ``boe_b0763``
#: escape. Owed under the P5.64 residual (its Part B: register a Basel 3.1 book
#: whose floor binds and which holds them), sequenced after P1.367 — the
#: output-floor-subset bullet, plan line 204, not its namesake (P6.56) — because
#: that fix changes which runs bind. Registering it grows this entry and re-banks
#: the register, the coverage, cell-coverage, filing-mapping and referee
#: baselines in one change.
FLOOR_STATE_SHAPES: dict[str, frozenset[str]] = {
    "binding": frozenset({"foundation_irb"}),
    "not binding": frozenset(FLOOR_SHAPES),
}

#: Where OF 02.00 reports the floor's state (PS1/26 Annex II p.29): row 0034
#: "Output floor activated", column 0030 only. Literal, from the instruction, so
#: the census does not inherit a mis-mapped row from ``c02_rows`` (LESSONS B3).
_ACTIVATED_ROW = "0034"
_ACTIVATED_COLUMN = "0030"


# ---------------------------------------------------------------------------
# Register records
# ---------------------------------------------------------------------------


class RuleKey(NamedTuple):
    """A broken rule. Regime-qualified: 85 rule ids appear in both extracts."""

    regime: str
    rule_id: str

    def describe(self) -> str:
        """Compact human address for an assertion message."""
        return f"{self.regime}/{self.rule_id}"


class TemplateKey(NamedTuple):
    """A template that went out unchecked, on one portfolio under one regime."""

    regime: str
    portfolio: str
    template: str

    def describe(self) -> str:
        """Compact human address for an assertion message."""
        return f"{self.regime}/{self.portfolio}: {self.template}"


class RuleFact(NamedTuple):
    """What the current run says about one broken rule."""

    severity: str
    label: str
    expression: str
    failing_coordinates: int
    coordinates: tuple[str, ...]
    portfolios: tuple[str, ...]
    lhs: float | None
    rhs: float | None

    def figures(self) -> str:
        """The two figures that disagree, formatted for a failure message."""
        left = "n/a" if self.lhs is None else f"{self.lhs:,.4f}"
        right = "n/a" if self.rhs is None else f"{self.rhs:,.4f}"
        return f"left = {left} vs right = {right}"


class VacuityFact(NamedTuple):
    """What the current run says about one rule that only ever held vacuously.

    There is no ``lhs``/``rhs`` and no failing coordinate to record: the rule
    held, at ``0 = 0``, on every coordinate it reached. ``tables`` and
    ``vacuous_coordinates`` are what triage has to work with — which templates to
    go and look at, and how many cells said nothing.
    """

    severity: str
    label: str
    expression: str
    tables: tuple[str, ...]
    vacuous_coordinates: int
    portfolios: tuple[str, ...]

    def figures(self) -> str:
        """The scale of the silence, formatted for a failure message."""
        return (
            f"held vacuously on {self.vacuous_coordinates} coordinate(s) "
            f"across {len(set(self.portfolios))} portfolio(s)"
        )


class GatewayKey(NamedTuple):
    """A Basel 3.1 rule the gateway engine breaks on one portfolio's filed return.

    Keyed on the PAIR, not the rule: a rule that starts breaking on one more
    portfolio is a new break (``boe_b1055`` went from two portfolios to seven
    under a rule-only key, unseen). And on the severity the gateway runs it at:
    a banked ERROR the Bank downgrades (or a WARNING it upgrades) is a new break
    and the old one gone, because a reason written for "rejects the return" is
    wrong for one that does not, and the filing-mapping ratchet, which counts
    Error breaks only, would see a downgrade merely as a fix.
    """

    rule_id: str
    portfolio: str
    severity: str

    def describe(self) -> str:
        """Compact human address for an assertion message."""
        return f"{GATEWAY_REGIME}/{self.portfolio}: {self.rule_id} [{self.severity}]"


class GatewayFact(NamedTuple):
    """What the gateway engine says about one broken (rule, portfolio).

    ``severity`` is as the gateway runs the rule on the run date: a rule the
    Bank's deny list downgraded is a WARNING here. ``template_level`` is the
    template-level engine's verdict on the same rule and return, so a reader
    sees at once whether legs (a)-(g) can see the break at all.
    """

    severity: str
    satisfied: int
    unsatisfied: int
    place: str
    cells: tuple[str, ...]
    template_level: str

    def figures(self) -> str:
        """Where and what, formatted for a failure message."""
        return (
            f"{self.unsatisfied} unsatisfied / {self.satisfied} satisfied; first at "
            f"{self.place or '(no place)'}: {' | '.join(self.cells)}"
        )

    def record(self) -> dict[str, Any]:
        """The per-portfolio facts as the register file holds them."""
        return {
            "satisfied": self.satisfied,
            "unsatisfied": self.unsatisfied,
            "template_level": self.template_level,
            "place": self.place,
        }


class DisagreementKey(NamedTuple):
    """A (rule, portfolio) on which the two engines reach opposite verdicts.

    The verdicts are part of the key, so a disagreement that changes direction
    is a new entry and the old one is gone.
    """

    rule_id: str
    portfolio: str
    template_level: str
    gateway: str

    def describe(self) -> str:
        """Compact human address for an assertion message."""
        return (
            f"{GATEWAY_REGIME}/{self.portfolio}: {self.rule_id} "
            f"(template-level {self.template_level}, gateway {self.gateway})"
        )


class DisagreementFact(NamedTuple):
    """The figures behind a disagreement, for triage."""

    severity: str
    template_detail: str
    gateway_detail: str


class FloorState(NamedTuple):
    """One run's output-floor state, as the engine holds it and as OF 02.00 reports it.

    ``engine_binding`` is ``OutputFloorSummary.portfolio_floor_binding``: the
    floor threshold strictly above U-TREA, both over the floor-eligible subset
    (``engine/aggregator/_floor.py``). ``reported_activated`` is OF 02.00 row
    0034 column 0030 — Yes when row 0010 column 0030 is "equal to or greater
    than" column 0010, over the whole book (PS1/26 Annex II p.29) — and None
    where the return states nothing. The two definitions differ (P1.367, the
    output-floor-subset bullet), which is why both are recorded and leg (o)
    holds them equal. ``u_trea`` and ``floor_threshold`` are the engine's, kept
    for the failure message; ``shapes`` names the ``FLOOR_SHAPES`` the run holds.
    """

    engine_binding: bool
    reported_activated: bool | None
    u_trea: float
    floor_threshold: float
    shapes: frozenset[str]

    @property
    def state(self) -> str:
        """The engine's state, under the name ``FLOOR_STATE_SHAPES`` banks it by."""
        return "binding" if self.engine_binding else "not binding"

    def describe(self) -> str:
        """Both states, the engine's two figures and the shapes, for a failure message."""
        reported = {True: "Yes", False: "No", None: "nothing"}[self.reported_activated]
        return (
            f"engine {self.state} (U-TREA {self.u_trea:,.2f}, floor "
            f"{self.floor_threshold:,.2f}); OF 02.00 r0034 reports {reported}; "
            f"shapes: {', '.join(sorted(self.shapes)) or 'none'}"
        )


class RunVerdicts(NamedTuple):
    """One run of ``RUNS`` as the gate judged it — what ``_fold_runs`` adds up.

    ``report`` is the template-level engine's verdict on every enforced rule;
    ``gateway`` and ``disagreements`` are the gateway leg's findings on the same
    return (empty under CRR, which files nothing). ``floor`` is the run's
    output-floor state, None where the run carried no ``OutputFloorSummary``.
    Kept on ``GateRun`` so that a test can re-judge ONE run from a mutated bundle
    and fold the matrix again without re-running the rest of it — which is how
    leg (m) is watched failing on a real row-drop (``test_a_rule_darkened_on_its_only_run_fails_leg_m_alone``).
    """

    regime: str
    portfolio: str
    report: ValidationReport
    gateway: dict[GatewayKey, GatewayFact]
    disagreements: dict[DisagreementKey, DisagreementFact]
    floor: FloorState | None = None


class GateRun(NamedTuple):
    """Everything the runs of ``RUNS`` produced (count the tuple, not this line).

    ``summary`` is per-run outcome counts, kept descriptive: nothing asserts an
    individual count, only that the four statuses are all reported and account
    for the enforced population. Vacuity used to live ONLY there, which is why it
    was invisible — the ratcheted population is ``vacuous``, at rule granularity.

    ``gateway`` and ``disagreements`` are the Basel 3.1 gateway leg, keyed per
    (rule, portfolio): see "Why there is a GATEWAY leg" in the module docstring.

    ``evaluated`` is every rule that reaches a verdict (``VERDICT_STATUSES``) on
    at least one run — the set legs (m)/(n) ratchet. ``runs`` is the per-run
    record it and every other field were folded from.

    ``floors`` is the output-floor state census, keyed ``regime/portfolio`` over
    every run that carried an ``OutputFloorSummary``; ``unfloored`` names the runs
    that carried none. See "Why there is an output-floor state census".
    """

    broken: dict[RuleKey, RuleFact]
    uncovered: dict[TemplateKey, int]
    summary: dict[str, dict[str, int]]
    vacuous: dict[RuleKey, VacuityFact]
    gateway: dict[GatewayKey, GatewayFact]
    disagreements: dict[DisagreementKey, DisagreementFact]
    evaluated: frozenset[RuleKey]
    runs: tuple[RunVerdicts, ...]
    floors: dict[str, FloorState]
    unfloored: tuple[str, ...]


# ---------------------------------------------------------------------------
# Running the estate
# ---------------------------------------------------------------------------


def _run_gate() -> GateRun:
    """Evaluate every enforced rule over every portfolio/regime combination."""
    return _fold_runs(tuple(_judge_run(run, *_generate_run(run)) for run in RUNS))


def _generate_run(
    run: GateInput,
) -> tuple[COREPTemplateBundle, Pillar3TemplateBundle, FloorState | None]:
    """One run's COREP and Pillar 3 bundles, generated as production generates them.

    The third element is the run's output-floor state (``_floor_state``), read from
    the same pipeline result and the OF 02.00 just generated, or None where the run
    carried no ``OutputFloorSummary`` (every CRR run).
    """
    result = PipelineOrchestrator().run_with_data(run.build_bundle(), run.build_config())
    prior = (
        PipelineOrchestrator().run_with_data(run.build_bundle(), run.build_prior_config())
        if run.build_prior_config is not None
        else None
    )
    corep = COREPGenerator().generate_from_lazyframe(
        result.results,
        framework=run.framework,
        # As production generates it: OF 02.00 takes OF-ADJ from the run's summary.
        output_floor_summary=result.output_floor_summary,
        previous_period_results=None if prior is None else prior.results,
    )
    pillar3 = Pillar3Generator().generate_from_lazyframe(result.results, framework=run.framework)
    floor = (
        None
        if result.output_floor_summary is None
        else _floor_state(result.output_floor_summary, corep.c_02_00, result.results)
    )
    return corep, pillar3, floor


def _judge_run(
    run: GateInput,
    corep: COREPTemplateBundle,
    pillar3: Pillar3TemplateBundle,
    floor: FloorState | None = None,
) -> RunVerdicts:
    """Both engines' verdicts on one run's bundles — the gateway's under Basel 3.1 only.

    ``floor`` is carried through unjudged: the floor-state legs read it from the fold.
    """
    report = evaluate_all(corep, pillar3, run.framework)
    if run.framework != GATEWAY_FRAMEWORK:
        return RunVerdicts(run.regime, run.portfolio, report, {}, {}, floor)
    breaks, opposed = _gateway_leg(run.portfolio, corep, report)
    return RunVerdicts(run.regime, run.portfolio, report, breaks, opposed, floor)


def _fold_runs(runs: Sequence[RunVerdicts]) -> GateRun:
    """Add the per-run verdicts up into the populations the legs compare.

    ``broken`` is the union over portfolios, keyed by rule: a rule breaking on
    more than one portfolio is ONE defect, and the portfolios it was seen on are
    recorded on the entry.

    ``uncovered`` is per run, because whether a template was checked depends on
    which portfolio emitted it — C 34.x exists only on the CCR portfolio.

    ``summary`` keeps PASS, FAIL, VACUOUS and NOT_EVALUATED apart. Conflating the
    last two with PASS is how a coverage hole hides.

    ``gateway`` and ``disagreements`` come from ``_gateway_leg`` on each Basel 3.1
    run, keyed per (rule, portfolio) — never unioned, because a rule reaching one
    more portfolio is the event they exist to catch.

    ``vacuous`` is the union too, and is the set of rules that reached a verdict
    ONLY vacuously — vacuous on at least one run and never PASS or FAIL on any.
    A rule vacuous here and passing there is still being checked somewhere, so it
    is not a lost check; a rule that only ever holds at ``0 = 0`` is. That is why
    ``real_verdict`` is accumulated across every run before the filter is applied,
    rather than deciding membership run by run.

    ``evaluated`` is the union of every verdict, VACUOUS included: a rule is out
    of it only when NO run evaluates it. A ``PASS -> NOT_EVALUATED`` move shows in
    another population only if it leaves the rule vacuous-only (``vacuous``) or
    its template with no rule executed (``uncovered``); when it takes the rule's
    LAST verdict, it always shows here, and a move that does not take the last
    verdict shows here not at all.

    ``floors`` / ``unfloored`` are per run, from the run's own summary and the
    OF 02.00 the template leg reads — no pipeline run of their own: ``_generate_run`` reads them and ``_judge_run`` carries them on each run's ``RunVerdicts``.
    """
    broken: dict[RuleKey, RuleFact] = {}
    uncovered: dict[TemplateKey, int] = {}
    summary: dict[str, dict[str, int]] = {}
    vacuous: dict[RuleKey, VacuityFact] = {}
    real_verdict: set[RuleKey] = set()
    gateway: dict[GatewayKey, GatewayFact] = {}
    disagreements: dict[DisagreementKey, DisagreementFact] = {}
    floors: dict[str, FloorState] = {}
    unfloored: list[str] = []
    for regime, portfolio, report, breaks, opposed, floor in runs:
        gateway.update(breaks)
        disagreements.update(opposed)
        if floor is None:
            unfloored.append(f"{regime}/{portfolio}")
        else:
            floors[f"{regime}/{portfolio}"] = floor
        summary[f"{regime}/{portfolio}"] = {
            **report.status_counts(),
            "rules_enforced": report.rules_enforced,
            "rules_executed": report.rules_executed,
            "templates_emitted": len(report.templates_emitted),
            "templates_covered": len(report.templates_covered),
        }
        for template in report.templates_uncovered:
            uncovered[TemplateKey(regime, portfolio, template)] = report.rules_executed

        for outcome in report.by_status(STATUS_PASS):
            real_verdict.add(RuleKey(regime, outcome.rule_id))

        for outcome in report.by_status(STATUS_VACUOUS):
            key = RuleKey(regime, outcome.rule_id)
            held = vacuous.get(key)
            if held is not None:
                vacuous[key] = held._replace(
                    portfolios=(*held.portfolios, portfolio),
                    vacuous_coordinates=max(held.vacuous_coordinates, outcome.vacuous),
                )
                continue
            vacuous[key] = VacuityFact(
                severity=outcome.severity,
                label=outcome.label or "",
                expression=outcome.expression or "",
                tables=outcome.tables[:MAX_RECORDED_TABLES],
                vacuous_coordinates=outcome.vacuous,
                portfolios=(portfolio,),
            )

        for outcome in report.by_status(STATUS_FAIL):
            key = RuleKey(regime, outcome.rule_id)
            real_verdict.add(key)
            seen = broken.get(key)
            if seen is not None:
                broken[key] = seen._replace(
                    portfolios=(*seen.portfolios, portfolio),
                    failing_coordinates=max(seen.failing_coordinates, outcome.failed),
                )
                continue
            first = outcome.failures[0]
            broken[key] = RuleFact(
                severity=outcome.severity,
                label=outcome.label or "",
                expression=outcome.expression or "",
                failing_coordinates=outcome.failed,
                coordinates=outcome.coordinates[:MAX_RECORDED_COORDINATES],
                portfolios=(portfolio,),
                lhs=first.lhs,
                rhs=first.rhs,
            )
    return GateRun(
        broken=broken,
        uncovered=uncovered,
        summary=summary,
        vacuous={key: fact for key, fact in vacuous.items() if key not in real_verdict},
        gateway=gateway,
        disagreements=disagreements,
        evaluated=_rules_with_a_verdict(runs),
        runs=tuple(runs),
        floors=floors,
        unfloored=tuple(unfloored),
    )


def _rules_with_a_verdict(runs: Iterable[RunVerdicts]) -> frozenset[RuleKey]:
    """Every rule some run brings to PASS, FAIL or VACUOUS — the set legs (m)/(n) hold."""
    return frozenset(
        RuleKey(run.regime, outcome.rule_id)
        for run in runs
        for outcome in run.report.outcomes
        if outcome.status in VERDICT_STATUSES
    )


def _gateway_leg(
    portfolio: str, corep: COREPTemplateBundle, report: ValidationReport
) -> tuple[dict[GatewayKey, GatewayFact], dict[DisagreementKey, DisagreementFact]]:
    """File ``corep`` as the gateway would and compare its verdicts with ``report``'s.

    ``corep`` is the bundle the template leg read, prior frame and all, so the
    two engines judge one return. Every gateway FAIL is recorded, ERROR and
    WARNING; a rule the Bank's deny list deactivates is NOT_EVALUATED there and
    so never recorded. A disagreement is a rule one engine breaks while the other
    holds it (``_opposed``).
    """
    # Imported here, not at the top: scripts/filing_mapping_report.py imports
    # RUNS from this module, so a module-level import would be a cycle. The
    # helper is the filing-mapping ratchet's own, so both ratchets file the same
    # return (same header, same pack, same deny-list date).
    from scripts.filing_mapping_report import file_on_gateway

    _mapping, validation = file_on_gateway(corep)
    assert validation.report is not None, (
        "no PRA001 rule book is packaged: the gateway leg would check nothing and read as clean"
    )
    template = {outcome.rule_id: outcome for outcome in report.outcomes}
    return _gateway_findings(portfolio, validation.report.results, template)


def _gateway_findings(
    portfolio: str,
    results: Iterable[RuleResult],
    template: Mapping[str, RuleOutcome],
) -> tuple[dict[GatewayKey, GatewayFact], dict[DisagreementKey, DisagreementFact]]:
    """The gateway's results on one return, as register keys and facts.

    ``results`` are as the gateway runs the rules (after the deny list), so a
    downgraded rule's break carries WARNING here; ``template`` is the
    template-level engine's outcome per rule on the same return. Separate from
    ``_gateway_leg`` so a synthetic result (a downgraded rule, which no packaged
    PRA001 deny list holds today) can be fed through the recording path
    without a pipeline run.
    """
    breaks: dict[GatewayKey, GatewayFact] = {}
    opposed: dict[DisagreementKey, DisagreementFact] = {}
    for result in results:
        outcome = template.get(result.rule_id)
        template_status = outcome.status if outcome is not None else STATUS_NOT_EVALUATED
        if result.status == GATEWAY_FAIL:
            first = result.failures[0] if result.failures else None
            breaks[GatewayKey(result.rule_id, portfolio, result.severity)] = GatewayFact(
                severity=result.severity,
                satisfied=result.satisfied,
                unsatisfied=result.unsatisfied,
                place=first.place if first is not None else "",
                cells=first.cells[:MAX_RECORDED_CELLS] if first is not None else (),
                template_level=_template_verdict(outcome),
            )
        if _opposed(template_status, result.status):
            key = DisagreementKey(result.rule_id, portfolio, template_status, result.status)
            opposed[key] = DisagreementFact(
                severity=result.severity,
                template_detail=_template_verdict(outcome),
                gateway_detail=_gateway_verdict(result),
            )
    return breaks, opposed


def _opposed(template_status: str, gateway_status: str) -> bool:
    """Whether the two engines reach OPPOSITE verdicts on one rule and return.

    One breaks it while the other holds it — a template-level VACUOUS holds too,
    at ``0 = 0``. A rule either engine does not evaluate is no disagreement: an
    absence of verdict is not a verdict.
    """
    if gateway_status == GATEWAY_FAIL:
        return template_status in (STATUS_PASS, STATUS_VACUOUS)
    if gateway_status == GATEWAY_PASS:
        return template_status == STATUS_FAIL
    return False


def _template_verdict(outcome: RuleOutcome | None) -> str:
    """The template-level verdict in words: status, and why where it reached none."""
    if outcome is None:
        return f"{STATUS_NOT_EVALUATED} (not in the template-level rule set)"
    if outcome.status == STATUS_NOT_EVALUATED:
        return f"{STATUS_NOT_EVALUATED} ({outcome.reason})" if outcome.reason else outcome.status
    if outcome.status == STATUS_FAIL:
        return f"{STATUS_FAIL} ({outcome.failed} failing coordinate(s))"
    return outcome.status


def _gateway_verdict(result: RuleResult) -> str:
    """The gateway verdict in words: status and the formula's counts."""
    return f"{result.status} ({result.unsatisfied} unsatisfied / {result.satisfied} satisfied)"


def _floor_state(
    summary: OutputFloorSummary, c_02_00: pl.DataFrame | None, results: pl.LazyFrame
) -> FloorState:
    """One run's floor state, from its summary, its OF 02.00 and its sealed ledger."""
    return FloorState(
        engine_binding=summary.portfolio_floor_binding,
        reported_activated=_reported_activation(c_02_00),
        u_trea=summary.u_trea,
        floor_threshold=summary.floor_threshold,
        shapes=_modelled_shapes(results),
    )


def _reported_activation(c_02_00: pl.DataFrame | None) -> bool | None:
    """OF 02.00 row 0034 column 0030 as Yes / No, or None where nothing is reported.

    An absent template, row, column or value is None, never False: an empty
    cell is not a "No" (LESSONS B4), and reading it as one would let a return
    that states nothing agree with every run whose floor is slack.
    """
    if c_02_00 is None or _ACTIVATED_COLUMN not in c_02_00.columns:
        return None
    values = (
        c_02_00.filter(pl.col("row_ref") == _ACTIVATED_ROW)[_ACTIVATED_COLUMN]
        .drop_nulls()
        .to_list()
    )
    if not values:
        return None
    (value,) = values
    return bool(value)


def _modelled_shapes(results: pl.LazyFrame) -> frozenset[str]:
    """The ``FLOOR_SHAPES`` at least one row of ``results`` holds.

    Every predicate names its carrier with ``pl.col``, so a carrier the ledger no
    longer seals raises ``ColumnNotFoundError`` rather than reading as a shape
    never reached (LESSONS B1). The one collect selects six booleans.
    """
    held = (
        results.select(
            **{name: shape.fill_null(value=False).any() for name, shape in FLOOR_SHAPES.items()}
        )
        .collect()
        .row(0, named=True)
    )
    return frozenset(name for name, present in held.items() if present)


@pytest.fixture(scope="module")
def gate_run() -> GateRun:
    """The runs of ``RUNS`` (and the gateway leg on its Basel 3.1 ones), executed once.

    ``--dist=loadfile`` pins this file to one worker, so the pipeline runs happen
    once per session rather than once per test.
    """
    return _run_gate()


# ---------------------------------------------------------------------------
# Baseline read / write
# ---------------------------------------------------------------------------


class Baseline(NamedTuple):
    """The committed register, as five ``{key: reason}`` maps and one of counts.

    Named rather than a bare tuple because a positional unpack
    (``_, baseline = _read_baseline()``) silently reads the wrong population the
    moment another is added — which is what the gateway leg just did.

    ``unsatisfied`` is each banked gateway pair's ``by_portfolio`` unsatisfied
    count, which leg (l) holds to may-not-rise. A pair whose entry carries no
    count (a synthetic payload) has none here.

    ``evaluated`` is the ``rules_with_a_verdict`` section, legs (m)/(n): a SET,
    not a reason map, because it is the covered population rather than a
    liability. Empty when the section is absent, which both legs refuse.
    """

    rules: dict[RuleKey, str]
    templates: dict[TemplateKey, str]
    vacuous: dict[RuleKey, str]
    gateway: dict[GatewayKey, str]
    disagreements: dict[DisagreementKey, str]
    unsatisfied: dict[GatewayKey, int]
    evaluated: frozenset[RuleKey]


def _read_baseline() -> Baseline:
    """Load the committed register: five reason maps, the gateway counts, the verdict set."""
    if not BASELINE_PATH.exists():
        return Baseline({}, {}, {}, {}, {}, {}, frozenset())
    return _baseline_from(json.loads(BASELINE_PATH.read_text(encoding="utf-8")))


def _baseline_from(payload: Mapping[str, Any]) -> Baseline:
    """The ``{key: reason}`` maps of a register's content, its gateway counts and verdict set.

    The two gateway sections hold one entry per (rule, reason) with the
    portfolios it covers; each is exploded back into its (rule, portfolio)
    pairs here, because the pair is what the legs compare.

    Raises:
        ValueError: if one key appears twice in a section. REGEN never writes
            that, but a hand edit of one entry's reason can, and a plain dict
            would keep the last reason and drop the other unseen. In
            ``rules_with_a_verdict`` a repeated id loses nothing, but it is still
            a hand edit REGEN would not have made, so it is refused alike.
    """
    rules = _keyed_reasons(
        "known_broken_rules",
        (
            (RuleKey(*(entry[field] for field in RULE_KEY_FIELDS)), entry["reason"])
            for entry in payload.get("known_broken_rules", [])
        ),
    )
    templates = _keyed_reasons(
        "known_uncovered_templates",
        (
            (TemplateKey(*(entry[field] for field in TEMPLATE_KEY_FIELDS)), entry["reason"])
            for entry in payload.get("known_uncovered_templates", [])
        ),
    )
    vacuous = _keyed_reasons(
        "known_vacuous_rules",
        (
            (RuleKey(*(entry[field] for field in RULE_KEY_FIELDS)), entry["reason"])
            for entry in payload.get("known_vacuous_rules", [])
        ),
    )
    gateway = _keyed_reasons(
        "known_gateway_breaks",
        (
            (GatewayKey(entry["rule_id"], portfolio, entry["severity"]), entry["reason"])
            for entry in payload.get("known_gateway_breaks", [])
            for portfolio in entry["portfolios"]
        ),
    )
    disagreements = _keyed_reasons(
        "known_engine_disagreements",
        (
            (
                DisagreementKey(
                    entry["rule_id"], portfolio, entry["template_level"], entry["gateway"]
                ),
                entry["reason"],
            )
            for entry in payload.get("known_engine_disagreements", [])
            for portfolio in entry["portfolios"]
        ),
    )
    unsatisfied = {
        GatewayKey(entry["rule_id"], portfolio, entry["severity"]): facts["unsatisfied"]
        for entry in payload.get("known_gateway_breaks", [])
        for portfolio, facts in entry.get("by_portfolio", {}).items()
    }
    evaluated = _rule_set(EVALUATED_SECTION, payload.get(EVALUATED_SECTION, {}))
    return Baseline(rules, templates, vacuous, gateway, disagreements, unsatisfied, evaluated)


def _keyed_reasons[K: tuple[str, ...]](
    section: str, pairs: Iterable[tuple[K, str]]
) -> dict[K, str]:
    """``{key: reason}`` for one register section, refusing a key held twice."""
    reasons: dict[K, str] = {}
    held_twice: list[str] = []
    for key, reason in pairs:
        if key in reasons:
            held_twice.append(f"  {key!r}: {reasons[key]!r} and {reason!r}")
        reasons[key] = reason
    if held_twice:
        detail = "\n".join(held_twice)
        raise ValueError(
            f"{section} holds {len(held_twice)} key(s) in more than one entry, so one reason "
            f"would silently replace the other; give each key one entry:\n{detail}"
        )
    return reasons


def _rule_set(section: str, by_regime: Mapping[str, Sequence[str]]) -> frozenset[RuleKey]:
    """A ``{regime: [rule_id, ...]}`` section as a set of ``RuleKey``, refusing a repeat."""
    counts = Counter(
        RuleKey(regime, rule_id) for regime, rule_ids in by_regime.items() for rule_id in rule_ids
    )
    held_twice = sorted(key.describe() for key, count in counts.items() if count > 1)
    if held_twice:
        raise ValueError(
            f"{section} lists {len(held_twice)} rule(s) more than once, which REGEN never "
            "writes; list each once:\n  " + "\n  ".join(held_twice)
        )
    return frozenset(counts)


def _write_baseline(run: GateRun) -> None:
    """Rewrite the register, PRESERVING every hand-written reason that still applies.

    Only the reason is curated. Severity, coordinates, portfolios and the summary
    are facts about the current estate and are always refreshed. In the two
    gateway sections the reason is kept per (rule, portfolio), so a rule that
    starts breaking on one more portfolio arrives ``unclassified``.
    ``rules_with_a_verdict`` carries no reason and is rewritten whole, last, so a
    re-bank that moves it is a run of ``+`` / ``-`` rule-id lines at the end of
    the diff.
    """
    existing = _read_baseline()
    payload = {
        "notes": REGISTER_NOTES,
        "summary": run.summary,
        "known_broken_rules": [
            {
                "regime": key.regime,
                "rule_id": key.rule_id,
                "severity": fact.severity,
                "reason": existing.rules.get(key, UNCLASSIFIED),
                "portfolios": sorted(set(fact.portfolios)),
                "failing_coordinates": fact.failing_coordinates,
                "coordinates": list(fact.coordinates),
                "expression": fact.expression,
            }
            for key, fact in sorted(run.broken.items())
        ],
        "known_uncovered_templates": [
            {
                "regime": key.regime,
                "portfolio": key.portfolio,
                "template": key.template,
                "reason": existing.templates.get(key, UNCLASSIFIED),
                "rules_executed_on_this_run": executed,
            }
            for key, executed in sorted(run.uncovered.items())
        ],
        "known_vacuous_rules": [
            {
                "regime": key.regime,
                "rule_id": key.rule_id,
                "severity": fact.severity,
                "reason": existing.vacuous.get(key, UNCLASSIFIED),
                "portfolios": sorted(set(fact.portfolios)),
                "vacuous_coordinates": fact.vacuous_coordinates,
                "tables": list(fact.tables),
                "expression": fact.expression,
            }
            for key, fact in sorted(run.vacuous.items())
        ],
        "known_gateway_breaks": _gateway_entries(run.gateway, existing.gateway),
        "known_engine_disagreements": _disagreement_entries(
            run.disagreements, existing.disagreements
        ),
        EVALUATED_SECTION: _rule_set_entries(run.evaluated),
    }
    BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
    BASELINE_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _rule_set_entries(keys: Iterable[RuleKey]) -> dict[str, list[str]]:
    """A set of ``RuleKey`` as the register holds it: ``{regime: [rule_id, ...]}``, sorted."""
    by_regime: dict[str, list[str]] = {}
    for key in sorted(keys):
        by_regime.setdefault(key.regime, []).append(key.rule_id)
    return by_regime


def _gateway_entries(
    measured: Mapping[GatewayKey, GatewayFact], reasons: Mapping[GatewayKey, str]
) -> list[dict[str, Any]]:
    """``known_gateway_breaks``: one entry per (rule, severity, reason), with its portfolios.

    Grouping by reason as well as rule keeps each reason to ONE cause: a rule
    that breaks for one reason on two portfolios and another on a third is two
    entries, and when the third is fixed its entry goes without touching the
    other's text. Severity is part of the key (``GatewayKey``), so a pair whose
    severity changed arrives ``unclassified`` in an entry of its own.
    """
    grouped: dict[tuple[str, str, str], list[GatewayKey]] = {}
    for key in sorted(measured):
        group = (key.rule_id, key.severity, reasons.get(key, UNCLASSIFIED))
        grouped.setdefault(group, []).append(key)
    entries: list[dict[str, Any]] = []
    for (rule_id, severity, reason), keys in sorted(grouped.items()):
        first = measured[keys[0]]
        entries.append(
            {
                "regime": GATEWAY_REGIME,
                "rule_id": rule_id,
                "severity": severity,
                "reason": reason,
                "portfolios": [key.portfolio for key in keys],
                "by_portfolio": {key.portfolio: measured[key].record() for key in keys},
                "example": f"{keys[0].portfolio}: {first.place} :: {' | '.join(first.cells)}",
            }
        )
    return entries


def _disagreement_entries(
    measured: Mapping[DisagreementKey, DisagreementFact], reasons: Mapping[DisagreementKey, str]
) -> list[dict[str, Any]]:
    """``known_engine_disagreements``: one entry per (rule, verdicts, reason)."""
    grouped: dict[tuple[str, str, str, str], list[DisagreementKey]] = {}
    for key in sorted(measured):
        group = (key.rule_id, key.template_level, key.gateway, reasons.get(key, UNCLASSIFIED))
        grouped.setdefault(group, []).append(key)
    return [
        {
            "regime": GATEWAY_REGIME,
            "rule_id": rule_id,
            "template_level": template_level,
            "gateway": gateway,
            "severity": measured[keys[0]].severity,
            "reason": reason,
            "portfolios": [key.portfolio for key in keys],
            "by_portfolio": {
                key.portfolio: {
                    "template_level": measured[key].template_detail,
                    "gateway": measured[key].gateway_detail,
                }
                for key in keys
            },
        }
        for (rule_id, template_level, gateway, reason), keys in sorted(grouped.items())
    ]


# ---------------------------------------------------------------------------
# The vacuity ratchet, as two named predicates
# ---------------------------------------------------------------------------
# Extracted rather than inlined like legs (a)-(d), for one reason: a gate nobody
# has watched fail is not a gate, and watching THIS one fail through the tests
# costs the whole run matrix plus a fixture change. Named functions over plain
# dicts can be driven with a synthetic measured-vs-baseline pair in seconds, so
# both directions are demonstrable on demand instead of argued from the code.
#
# Every set leg routes its set arithmetic through ONE mechanism —
# `scripts/tolerated_findings.py::diff`, extracted under P5.41 so this register
# and the two declared ones (`KNOWN_DISAGREEMENTS`,
# `classification_table.toml`'s `[[known_disagreement]]`) cannot drift apart on
# what "new" and "gone" mean. `diff` is deliberately direction-NEUTRAL: it
# reports both sides and each caller decides which is a failure. This register
# stays two-way — an increase may be banked with REGEN_VALIDATION_BASELINE=1,
# because its membership is MEASURED over the pipeline runs of RUNS and a fixture
# change legitimately moves it. The declared registers are shrink-only, because
# an entry there is a decision to ship a number the oracle has independently
# shown is wrong. Same arithmetic, different policy, stated in each caller.


def _rules_newly_vacuous(
    measured: dict[RuleKey, VacuityFact], baseline: dict[RuleKey, str]
) -> tuple[RuleKey, ...]:
    """Rules that now hold only vacuously and the register does not admit to."""
    return diff(measured, baseline).added


def _rules_no_longer_vacuous(
    measured: dict[RuleKey, VacuityFact], baseline: dict[RuleKey, str]
) -> tuple[RuleKey, ...]:
    """Register entries whose rule has started reaching a real verdict again."""
    return diff(measured, baseline).removed


# ---------------------------------------------------------------------------
# The verdict-set ratchet, as two named predicates
# ---------------------------------------------------------------------------
# The sibling of the vacuity pair, for the move it cannot see: a rule that stops
# being evaluated ANYWHERE. Named for the same reason, so that
# tests/contracts/test_register_verdict_set.py can drive both directions with
# synthetic sets in milliseconds. Mind the direction, which is the opposite of
# the sibling it sits under: leg (f) fails on what JOINS its measured population
# (`.added`), leg (m) on what LEAVES this one (`.removed`).


def _rules_newly_unevaluated(
    measured: Iterable[RuleKey], baseline: Iterable[RuleKey]
) -> tuple[RuleKey, ...]:
    """Banked rules that now reach no verdict on any run - leg (m) fails on these."""
    return diff(measured, baseline).removed


def _rules_newly_evaluated(
    measured: Iterable[RuleKey], baseline: Iterable[RuleKey]
) -> tuple[RuleKey, ...]:
    """Rules that reach a verdict on some run and are not banked - leg (n) fails on these."""
    return diff(measured, baseline).added


def _outcome_index(runs: Iterable[RunVerdicts]) -> dict[RuleKey, dict[str, RuleOutcome]]:
    """Each rule's template-level outcome on every run that enforces it, by portfolio."""
    index: dict[RuleKey, dict[str, RuleOutcome]] = {}
    for run in runs:
        for outcome in run.report.outcomes:
            index.setdefault(RuleKey(run.regime, outcome.rule_id), {})[run.portfolio] = outcome
    return index


def _statuses(verdicts: RunVerdicts) -> dict[str, str]:
    """One run's template-level status per rule id."""
    return {outcome.rule_id: outcome.status for outcome in verdicts.report.outcomes}


def _describe_unevaluated(
    keys: Sequence[RuleKey], index: Mapping[RuleKey, Mapping[str, RuleOutcome]]
) -> str:
    """Format leg (m)'s findings: each rule, and why each run left it NOT_EVALUATED."""
    lines: list[str] = []
    for key in keys:
        outcomes = index.get(key, {})
        if not outcomes:
            lines.append(
                f"  {key.describe()}  no longer in the enforced rule set on any run (a deny-list "
                "entry now in force, or an extract or taxonomy refresh)"
            )
            continue
        first = next(iter(outcomes.values()))
        why: dict[str, list[str]] = {}
        for portfolio, outcome in outcomes.items():
            why.setdefault(outcome.reason or "no reason recorded", []).append(portfolio)
        lines.append(
            f"  {key.describe()}  [{first.severity}] NOT_EVALUATED on all "
            f"{len(outcomes)} run(s) of its regime\n"
            f"      rule: {first.expression or ''}\n"
            f"      why:  "
            + "; ".join(f"{reason} on {', '.join(ports)}" for reason, ports in sorted(why.items()))
            + (f"\n      {first.label}" if first.label else "")
        )
    return "\n".join(lines)


def _describe_evaluated(
    keys: Sequence[RuleKey], index: Mapping[RuleKey, Mapping[str, RuleOutcome]]
) -> str:
    """Format leg (n)'s findings: each rule, and the verdict it reaches on which runs."""
    lines: list[str] = []
    for key in keys:
        outcomes = index[key]
        verdicts: dict[str, list[str]] = {}
        for portfolio, outcome in outcomes.items():
            if outcome.status in VERDICT_STATUSES:
                verdicts.setdefault(outcome.status, []).append(portfolio)
        severity = next(iter(outcomes.values())).severity
        lines.append(
            f"  {key.describe()}  [{severity}] "
            + "; ".join(
                f"{status} on {', '.join(ports)}" for status, ports in sorted(verdicts.items())
            )
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# The gateway legs, as six named predicates
# ---------------------------------------------------------------------------
# Named for the same reason as the vacuity pair: watching legs (h)-(l) fail
# through the tests costs the whole run matrix and a fixture change, while these
# can be driven with a synthetic measured-vs-baseline pair in milliseconds —
# tests/contracts/test_gateway_break_registers_agree.py does exactly that,
# including the boe_b1055 shape (one more portfolio for a banked rule) and a
# banked pair failing in one more place (leg (l)).


def _gateway_breaks_added(
    measured: Mapping[GatewayKey, object], baseline: Mapping[GatewayKey, str]
) -> tuple[GatewayKey, ...]:
    """(rule, portfolio) pairs the gateway breaks that the register does not admit to."""
    return diff(measured, baseline).added


def _gateway_breaks_removed(
    measured: Mapping[GatewayKey, object], baseline: Mapping[GatewayKey, str]
) -> tuple[GatewayKey, ...]:
    """Banked (rule, portfolio) pairs the gateway no longer breaks."""
    return diff(measured, baseline).removed


class CountMove(NamedTuple):
    """A banked gateway pair whose unsatisfied count moved: leg (l)'s finding."""

    key: GatewayKey
    banked: int
    measured: int

    def describe(self) -> str:
        """The pair and both counts, for an assertion message or a report."""
        return f"{self.key.describe()}: {self.banked} -> {self.measured} unsatisfied"


def _gateway_counts_risen(
    measured: Mapping[GatewayKey, int], banked: Mapping[GatewayKey, int]
) -> tuple[CountMove, ...]:
    """Banked pairs that now fail in MORE places than the register holds - leg (l) fails."""
    return tuple(move for move in _count_moves(measured, banked) if move.measured > move.banked)


def _gateway_counts_fallen(
    measured: Mapping[GatewayKey, int], banked: Mapping[GatewayKey, int]
) -> tuple[CountMove, ...]:
    """Banked pairs that now fail in FEWER places - leg (l) passes and reports them."""
    return tuple(move for move in _count_moves(measured, banked) if move.measured < move.banked)


def _count_moves(
    measured: Mapping[GatewayKey, int], banked: Mapping[GatewayKey, int]
) -> tuple[CountMove, ...]:
    """Every pair held on both sides whose count differs; a pair on one side is (h)/(i)'s."""
    return tuple(
        CountMove(key, banked[key], measured[key])
        for key in sorted(set(measured) & set(banked))
        if measured[key] != banked[key]
    )


def _disagreements_added(
    measured: Mapping[DisagreementKey, object], baseline: Mapping[DisagreementKey, str]
) -> tuple[DisagreementKey, ...]:
    """Opposite verdicts the register does not admit to."""
    return diff(measured, baseline).added


def _disagreements_removed(
    measured: Mapping[DisagreementKey, object], baseline: Mapping[DisagreementKey, str]
) -> tuple[DisagreementKey, ...]:
    """Banked disagreements the two engines no longer have."""
    return diff(measured, baseline).removed


# ---------------------------------------------------------------------------
# The output-floor state census, as three named predicates
# ---------------------------------------------------------------------------
# Named for the same reason as the gateway predicates: legs (n)-(p) cost the
# whole run matrix to watch fail, while these take a synthetic state map —
# tests/contracts/test_output_floor_state_census.py drives each failure mode.


def _binding_runs(floors: Mapping[str, FloorState]) -> frozenset[str]:
    """The runs whose ENGINE floor binds; the reported state is leg (o)'s business."""
    return frozenset(run for run, state in floors.items() if state.engine_binding)


def _activation_disagreements(floors: Mapping[str, FloorState]) -> tuple[str, ...]:
    """Runs whose OF 02.00 activation is not the engine's state, or is not reported."""
    return tuple(
        sorted(
            run
            for run, state in floors.items()
            if state.reported_activated is None or state.reported_activated != state.engine_binding
        )
    )


def _shapes_by_state(floors: Mapping[str, FloorState]) -> dict[str, frozenset[str]]:
    """The union of the runs' shapes per floor state; a state no run reaches is empty."""
    by_state: dict[str, set[str]] = {name: set() for name in FLOOR_STATE_SHAPES}
    for state in floors.values():
        by_state[state.state].update(state.shapes)
    return {name: frozenset(shapes) for name, shapes in by_state.items()}


def _describe_vacuity(keys: Sequence[RuleKey], facts: dict[RuleKey, VacuityFact]) -> str:
    """Format vacuity findings for an assertion message."""
    return "\n".join(
        f"  {key.describe()}  [{facts[key].severity}] {facts[key].figures()}\n"
        f"      rule: {facts[key].expression}\n"
        f"      on:   {', '.join(facts[key].tables)} "
        f"(portfolios: {', '.join(sorted(set(facts[key].portfolios)))})\n"
        f"      {facts[key].label}"
        for key in keys
    )


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------


def test_no_supervisory_validation_break_outside_the_baseline(gate_run: GateRun) -> None:
    """Every published rule the estate breaks is one already recorded as known.

    Arrange: three reporting portfolios through both regimes.
    Act:     evaluate every currently-enforced published rule over the templates.
    Assert:  the broken rules are a subset of the committed register.
    """
    if REGEN:
        _write_baseline(gate_run)
        pytest.skip(f"REGEN_VALIDATION_BASELINE=1 - rewrote {BASELINE_PATH.name}")

    # Arrange
    assert BASELINE_PATH.exists(), (
        f"No validation baseline at {BASELINE_PATH}. Capture it first: "
        "REGEN_VALIDATION_BASELINE=1 uv run pytest "
        "tests/acceptance/reporting/test_supervisory_validations.py"
    )
    baseline = _read_baseline().rules

    # Act
    new_breaks = diff(gate_run.broken, baseline).added

    # Assert
    blocking = [key for key in new_breaks if gate_run.broken[key].severity == "ERROR"]
    detail = "\n".join(
        f"  {key.describe()}  [{gate_run.broken[key].severity}] "
        f"{gate_run.broken[key].figures()} on {gate_run.broken[key].failing_coordinates} cell(s)\n"
        f"      rule: {gate_run.broken[key].expression}\n"
        f"      at:   {', '.join(gate_run.broken[key].coordinates)}\n"
        f"      {gate_run.broken[key].label}"
        for key in new_breaks
    )
    assert not new_breaks, (
        f"{len(new_breaks)} NEW supervisory validation break(s), "
        f"{len(blocking)} of them Error-severity (an Error-severity break rejects "
        f"the whole submission):\n{detail}\n"
        "Fix the defect. Only if the break is accepted, add it to "
        f"{BASELINE_PATH.name} with a written reason."
    )


def test_no_baseline_break_has_been_fixed_without_being_removed(gate_run: GateRun) -> None:
    """The register may only shrink deliberately — a silent fix must be recorded.

    Arrange: the committed register plus the breaks the current estate produces.
    Act:     find register entries that no longer break.
    Assert:  there are none; a fix must remove its own baseline entry.
    """
    if REGEN:
        pytest.skip("REGEN_VALIDATION_BASELINE=1 - baseline rewritten by the companion test")

    # Arrange
    baseline = _read_baseline().rules

    # Act
    stale = diff(gate_run.broken, baseline).removed

    # Assert
    detail = "\n".join(f"  {key.describe()}\n      was: {baseline[key]}" for key in stale)
    assert not stale, (
        f"{len(stale)} baseline break(s) no longer break - this is now FIXED. "
        f"Remove the entry from {BASELINE_PATH.name}:\n{detail}"
    )


def test_no_template_goes_unchecked_outside_the_baseline(gate_run: GateRun) -> None:
    """A NEW coverage hole fails the gate — the fail-open guard.

    ``check_supervisory_validations`` returns no findings for a template no rule
    reached, which is indistinguishable from a template that passed. Without this
    assertion a change that stopped the evaluator seeing a template would make
    the break set SHRINK and read as progress.

    Arrange: three portfolios through both regimes.
    Act:     collect every emitted template no executed rule named.
    Assert:  each is one the register already admits to.
    """
    if REGEN:
        pytest.skip("REGEN_VALIDATION_BASELINE=1 - baseline rewritten by the companion test")

    # Arrange
    baseline = _read_baseline().templates

    # Act
    new_holes = diff(gate_run.uncovered, baseline).added

    # Assert
    detail = "\n".join(
        f"  {key.describe()} ({gate_run.uncovered[key]} rule(s) executed on that run)"
        for key in new_holes
    )
    assert not new_holes, (
        f"{len(new_holes)} template(s) went unchecked that the register does not admit to. "
        "An absent break on these is NOT evidence the return is valid:\n" + detail
    )


def test_no_baseline_coverage_hole_has_been_closed_without_being_removed(gate_run: GateRun) -> None:
    """Closing a coverage hole must shrink the register deliberately.

    Arrange: the committed register plus the current coverage.
    Act:     find recorded holes that are now covered.
    Assert:  there are none.
    """
    if REGEN:
        pytest.skip("REGEN_VALIDATION_BASELINE=1 - baseline rewritten by the companion test")

    # Arrange
    baseline = _read_baseline().templates

    # Act
    closed = diff(gate_run.uncovered, baseline).removed

    # Assert
    detail = "\n".join(f"  {key.describe()}\n      was: {baseline[key]}" for key in closed)
    assert not closed, (
        f"{len(closed)} recorded coverage hole(s) are now COVERED. "
        f"Remove the entry from {BASELINE_PATH.name}:\n{detail}"
    )


def test_every_baseline_entry_carries_a_written_reason() -> None:
    """The register is a liability list, not a hash — each line explains itself.

    ``unattributed - needs investigation`` is an acceptable written reason: it
    records that the mechanism is visible but the defect is not established. What
    is not acceptable is the capture placeholder, which records nothing.

    All FIVE populations are checked. A vacuity entry without a reason is the
    worst to leave lying around: it looks like a passing rule. A gateway entry
    without one is an Error the Bank rejects the return for, with no account of
    whose it is. ``rules_with_a_verdict`` is not a sixth: it is the covered set,
    not a liability, and carries no reasons.

    Arrange: the committed register.
    Act:     find entries still carrying the capture placeholder.
    Assert:  there are none.
    """
    if REGEN:
        pytest.skip("REGEN_VALIDATION_BASELINE=1 - reasons are written by hand after capture")

    # Arrange
    baseline = _read_baseline()

    # Act
    untriaged = sorted(
        key.describe() for key, reason in baseline.rules.items() if reason == UNCLASSIFIED
    )
    untriaged += sorted(
        key.describe() for key, reason in baseline.templates.items() if reason == UNCLASSIFIED
    )
    untriaged += sorted(
        f"{key.describe()} (vacuous)"
        for key, reason in baseline.vacuous.items()
        if reason == UNCLASSIFIED
    )
    untriaged += sorted(
        f"{key.describe()} (gateway)"
        for key, reason in baseline.gateway.items()
        if reason == UNCLASSIFIED
    )
    untriaged += sorted(
        f"{key.describe()} (disagreement)"
        for key, reason in baseline.disagreements.items()
        if reason == UNCLASSIFIED
    )

    # Assert
    assert not untriaged, (
        f"{len(untriaged)} baseline entry/entries were captured but never triaged. "
        f"Replace the placeholder in {BASELINE_PATH.name} with what defect each "
        "entry corresponds to:\n  " + "\n  ".join(untriaged)
    )


def test_no_rule_falls_to_vacuous_outside_the_baseline(gate_run: GateRun) -> None:
    """A rule that stops asserting anything fails the gate — leg (f).

    This is the PASS -> VACUOUS regression no other leg can see: the template is
    still emitted (so coverage is unmoved), the rule still holds (so the break set
    is unmoved), and before this assertion existed the only trace was a count in
    ``summary`` that nothing compared against anything.

    Arrange: the committed register plus the rules the current estate only ever
             holds vacuously.
    Act:     find vacuity-only rules the register does not admit to.
    Assert:  there are none.
    """
    if REGEN:
        pytest.skip("REGEN_VALIDATION_BASELINE=1 - baseline rewritten by the companion test")

    # Arrange
    baseline = _read_baseline().vacuous

    # Act
    fallen = _rules_newly_vacuous(gate_run.vacuous, baseline)

    # Assert
    blocking = [key for key in fallen if gate_run.vacuous[key].severity == "ERROR"]
    assert not fallen, (
        f"{len(fallen)} published rule(s) now hold ONLY VACUOUSLY, {len(blocking)} of them "
        "Error-severity. Every operand was null or exactly zero, so the rule asserts nothing "
        "about our figures while still reporting a green outcome:\n"
        f"{_describe_vacuity(fallen, gate_run.vacuous)}\n"
        "TWO provenances reach this state and the gate cannot tell them apart - it holds no "
        "prior status - so establish which before acting:\n"
        "  PASS -> VACUOUS is a REGRESSION. Something emptied cells this rule was checking. "
        "This is exactly how a defect that empties a column passes this gate (LESSONS B5, "
        "recurrence 2026-08-08). Find what emptied them; do not bank it.\n"
        "  NOT_EVALUATED -> VACUOUS is an IMPROVEMENT. A cell that was structurally absent is "
        "now emitted (as null or zero), so a rule from the never-evaluated pool has started "
        "reaching a verdict. Bank it: add the entry with a written reason saying so.\n"
        f"Either way the entry belongs in {BASELINE_PATH.name} under known_vacuous_rules only "
        "once the vacuity is accepted in writing."
    )


def test_no_baseline_vacuous_rule_asserts_again_without_being_removed(gate_run: GateRun) -> None:
    """A rule that starts asserting something must shrink the register — leg (g).

    The mirror of leg (f), and the leg that makes progress visible: when a fixture
    finally puts a real figure in a dead cell, the rule reaches PASS or FAIL and
    its entry becomes a lie. The gate fails until the entry is deleted, exactly as
    a fixed break must be removed from ``known_broken_rules``.

    Read the failure before banking it: leaving this population is not always
    progress. A rule also leaves by becoming NOT_EVALUATED on every run where it
    was vacuous — a cell that stopped being emitted, a portfolio dropped from
    ``RUNS`` — and that estate is WORSE, not better. PASS or FAIL is the
    discharge; absence is a regression wearing the same shirt. Where the rule
    was vacuous on every run that evaluated it, leg (m) fails alongside this one
    and names it as a lost verdict, which tells the two apart.

    Do not read the converse into that, though. This leg does NOT catch a rule
    going dark: it fires only when the rule leaves the population ENTIRELY, which
    takes a change reaching every run where it was vacuous. A rule darkened on one
    run and still vacuous on another stays listed and this leg stays green —
    measured on ``crr/v3332_i`` (vacuous on ``rich`` and ``crm-substitution``).
    See "What legs (f)/(g) do NOT catch" in the module docstring.

    Arrange: the committed register plus the current vacuity population.
    Act:     find register entries that now reach a real verdict.
    Assert:  there are none.
    """
    if REGEN:
        pytest.skip("REGEN_VALIDATION_BASELINE=1 - baseline rewritten by the companion test")

    # Arrange
    baseline = _read_baseline().vacuous

    # Act
    activated = _rules_no_longer_vacuous(gate_run.vacuous, baseline)

    # Assert
    detail = "\n".join(f"  {key.describe()}\n      was: {baseline[key]}" for key in activated)
    assert not activated, (
        f"{len(activated)} baseline vacuous rule(s) left the vacuity population. If they now PASS "
        "or FAIL they are being CHECKED again - bank it and remove the entry from "
        f"{BASELINE_PATH.name}. If they went NOT_EVALUATED instead, the cell or the run went away "
        f"and the estate got WORSE - fix that instead of deleting the entry:\n{detail}"
    )


def test_no_gateway_break_outside_the_baseline(gate_run: GateRun) -> None:
    """Every rule the Bank's gateway would break is one already recorded — leg (h).

    The gateway engine (``rwa_filer.boe``, pinned to Arelle) on the canonical
    return filed from each Basel 3.1 run, with the Bank's deny list in force on
    the run date. Keyed on (rule, portfolio, severity): a banked rule breaking on
    one more portfolio is a new break, and so is a banked break the Bank's deny
    list moves to another severity (leg (i) then reports the old one gone).

    Arrange: the committed register plus the gateway breaks of the Basel 3.1
             returns (one per Basel 3.1 run of ``RUNS``).
    Act:     find (rule, portfolio) pairs the register does not admit to.
    Assert:  there are none.
    """
    if REGEN:
        pytest.skip("REGEN_VALIDATION_BASELINE=1 - baseline rewritten by the companion test")

    # Arrange
    baseline = _read_baseline().gateway

    # Act
    new_breaks = _gateway_breaks_added(gate_run.gateway, baseline)

    # Assert
    blocking = [key for key in new_breaks if key.severity == "ERROR"]
    detail = "\n".join(
        f"  {key.describe()}  {gate_run.gateway[key].figures()}\n"
        f"      template-level engine: {gate_run.gateway[key].template_level}"
        for key in new_breaks
    )
    assert not new_breaks, (
        f"{len(new_breaks)} NEW gateway break(s) on a filed Basel 3.1 return, {len(blocking)} "
        "of them Error-severity (the Bank rejects the return for those):\n"
        f"{detail}\nFix the defect. Only if the break is accepted, add it to "
        f"{BASELINE_PATH.name} under known_gateway_breaks with a written reason - citing "
        "the publisher issue (PI-nn) if the published rule is the cause."
    )


def test_no_baseline_gateway_break_has_been_fixed_without_being_removed(gate_run: GateRun) -> None:
    """A gateway break that has gone must leave the register deliberately — leg (i).

    Read the failure before deleting: a pair also leaves when the rule stops
    being evaluated at all (a template no longer filed, a table the canonical
    return no longer places, a rule the Bank deactivates), and when the Bank
    changes its severity — the pair is then in leg (h) at the new severity, and
    its reason must be rewritten for it. The gateway engine's NOT_EVALUATED
    reason says which.

    Arrange: the committed register plus the current gateway breaks.
    Act:     find banked (rule, portfolio) pairs that no longer break.
    Assert:  there are none.
    """
    if REGEN:
        pytest.skip("REGEN_VALIDATION_BASELINE=1 - baseline rewritten by the companion test")

    # Arrange
    baseline = _read_baseline().gateway

    # Act
    gone = _gateway_breaks_removed(gate_run.gateway, baseline)

    # Assert
    detail = "\n".join(f"  {key.describe()}\n      was: {baseline[key]}" for key in gone)
    assert not gone, (
        f"{len(gone)} banked gateway break(s) no longer break at the banked severity. "
        f"Remove each from known_gateway_breaks in {BASELINE_PATH.name} (a pair the deny "
        "list moved to another severity is in leg (h) too: re-write its reason) - and, for "
        "an Error, re-bank scripts/filing_mapping_baseline.json in the same change:\n"
        f"{detail}"
    )


def test_no_banked_gateway_break_fails_in_more_places(gate_run: GateRun) -> None:
    """A banked pair's unsatisfied count may not rise — leg (l).

    Legs (h)/(i) compare the SET of (rule, portfolio, severity) pairs, so a pair
    already banked could fail in any number of new places — a new defect of
    ours behind a reason written for the old ones, a ``publisher issue PI-nn``
    label among them — and neither leg would move. This leg holds each banked
    pair's ``by_portfolio`` unsatisfied count: a rise fails, naming the pair and
    the new count. A fall passes, because fewer failing places is progress, and
    is reported as a warning so that ``REGEN_VALIDATION_BASELINE=1`` banks the
    lower count (which then becomes the new ceiling); the reasons are preserved
    as for every other section, so read the reason against the new places.

    Arrange: the committed register's banked counts plus the current gateway breaks.
    Act:     compare the counts on the pairs both hold.
    Assert:  none has risen; any that fell is reported.
    """
    if REGEN:
        pytest.skip("REGEN_VALIDATION_BASELINE=1 - baseline rewritten by the companion test")

    # Arrange
    baseline = _read_baseline()
    measured = {key: fact.unsatisfied for key, fact in gate_run.gateway.items()}

    # Act
    risen = _gateway_counts_risen(measured, baseline.unsatisfied)
    fallen = _gateway_counts_fallen(measured, baseline.unsatisfied)

    # Assert
    if fallen:
        warnings.warn(
            f"{len(fallen)} banked gateway break(s) now fail in fewer places; bank the lower "
            "count with REGEN_VALIDATION_BASELINE=1 so it becomes the ceiling:\n  "
            + "\n  ".join(move.describe() for move in fallen),
            stacklevel=1,
        )
    detail = "\n".join(
        f"  {move.describe()}\n      now {gate_run.gateway[move.key].figures()}\n"
        f"      reason: {baseline.gateway[move.key]}"
        for move in risen
    )
    assert not risen, (
        f"{len(risen)} banked gateway break(s) fail in MORE places than "
        f"{BASELINE_PATH.name} holds - a new defect can sit behind a banked reason:\n"
        f"{detail}\nFix the new places. Only if the reason still accounts for every one, "
        "re-bank the count with REGEN_VALIDATION_BASELINE=1."
    )


def test_the_two_engines_disagree_nowhere_the_register_does_not_say(gate_run: GateRun) -> None:
    """A new disagreement between the template-level and the gateway engine fails — leg (j).

    One engine breaking a rule the other holds, on the same return, is exactly
    the shape of ``boe_b0778``: a false Error break the template-level engine
    reported on every Basel 3.1 return, banked under a reason that blamed the
    Bank's rule, while the gateway's own reading never broke it.

    Arrange: the committed register plus both engines' verdicts on each return.
    Act:     find opposite verdicts the register does not admit to.
    Assert:  there are none.
    """
    if REGEN:
        pytest.skip("REGEN_VALIDATION_BASELINE=1 - baseline rewritten by the companion test")

    # Arrange
    baseline = _read_baseline().disagreements

    # Act
    new = _disagreements_added(gate_run.disagreements, baseline)

    # Assert
    detail = "\n".join(
        f"  {key.describe()}\n"
        f"      template-level: {gate_run.disagreements[key].template_detail}\n"
        f"      gateway:        {gate_run.disagreements[key].gateway_detail}"
        for key in new
    )
    assert not new, (
        f"{len(new)} NEW disagreement(s) between the two engines. Establish which reading is "
        "right before anything else - the gateway engine is pinned to Arelle, the "
        "template-level engine has five known differences (module docstring):\n"
        f"{detail}\nOnly once explained, add each to known_engine_disagreements in "
        f"{BASELINE_PATH.name} with a written reason."
    )


def test_no_baseline_disagreement_has_gone_without_being_removed(gate_run: GateRun) -> None:
    """Two engines that have come to agree must shrink the register — leg (k).

    Arrange: the committed register plus both engines' verdicts.
    Act:     find banked disagreements the engines no longer have.
    Assert:  there are none.
    """
    if REGEN:
        pytest.skip("REGEN_VALIDATION_BASELINE=1 - baseline rewritten by the companion test")

    # Arrange
    baseline = _read_baseline().disagreements

    # Act
    gone = _disagreements_removed(gate_run.disagreements, baseline)

    # Assert
    detail = "\n".join(f"  {key.describe()}\n      was: {baseline[key]}" for key in gone)
    assert not gone, (
        f"{len(gone)} banked disagreement(s) between the two engines are gone. Remove each "
        f"from known_engine_disagreements in {BASELINE_PATH.name}:\n{detail}"
    )


def test_no_banked_rule_loses_its_last_verdict(gate_run: GateRun) -> None:
    """A rule the register lists as evaluated and that no run now evaluates fails — leg (m).

    This is the ``PASS -> NOT_EVALUATED`` regression legs (a)-(g) cannot see: a
    darkened rule is not a break, not a vacuity and does not uncover its
    template while the template still has other rules. The gateway legs see it
    only where the gateway engine itself then FAILs the rule, since they count a
    NOT_EVALUATED side as no disagreement. Measured on the 31-run matrix
    (2026-11-24): dropping C 02.00 r0160 from ``crr/rich`` darkens ``v3335_i``
    (ERROR), which passes on that run alone, and of all fourteen legs only this
    one fails — ``test_a_rule_darkened_on_its_only_run_fails_leg_m_alone``
    reproduces it on every run of this file.

    It holds a rule's LAST verdict only. ``v0207_m``, darkened on ``crr/rich`` by
    the same row-drop, keeps a verdict on the other fourteen CRR runs and passes
    here; see "What legs (f)/(g) do NOT catch" in the module docstring.

    Arrange: the committed register's verdict set plus the rules the current
             estate brings to a verdict on some run.
    Act:     find banked rules that no run now evaluates.
    Assert:  there are none.
    """
    if REGEN:
        pytest.skip("REGEN_VALIDATION_BASELINE=1 - baseline rewritten by the companion test")

    # Arrange
    baseline = _read_baseline().evaluated
    assert baseline, MISSING_EVALUATED_SECTION

    # Act
    dark = _rules_newly_unevaluated(gate_run.evaluated, baseline)

    # Assert
    index = _outcome_index(gate_run.runs)
    blocking = [
        key
        for key in dark
        if any(outcome.severity == "ERROR" for outcome in index.get(key, {}).values())
    ]
    assert not dark, (
        f"{len(dark)} rule(s) listed under {EVALUATED_SECTION} reach NO verdict on any run, "
        f"{len(blocking)} of them Error-severity. Each was checked somewhere at the last bank "
        "and is now checked nowhere, and no other leg can see that:\n"
        f"{_describe_unevaluated(dark, index)}\n"
        "Find what stopped it being evaluated - a row, column or sheet no longer emitted, a "
        "sheet map or binding that no longer addresses it, a run dropped from RUNS - and "
        "restore it. Only if the loss is deliberate (the Bank deactivated the rule, an "
        "extract refresh retired it) re-bank with REGEN_VALIDATION_BASELINE=1 and say so in "
        "the commit."
    )


def test_no_rule_reaches_a_verdict_without_being_banked(gate_run: GateRun) -> None:
    """A rule some run now evaluates that the register does not list fails — leg (n).

    The mirror of leg (m), and what keeps it honest: a rule that first reaches a
    verdict after the last bank is not in the set, so leg (m) could not see it
    go dark again. The move is normally progress — a fixture lit a cell, a
    binding began to address a table, a refreshed extract added a rule — so the
    remedy is to bank it, not to undo it.

    Arrange: the committed register's verdict set plus the current verdicts.
    Act:     find rules with a verdict somewhere that the register does not list.
    Assert:  there are none.
    """
    if REGEN:
        pytest.skip("REGEN_VALIDATION_BASELINE=1 - baseline rewritten by the companion test")

    # Arrange
    baseline = _read_baseline().evaluated
    assert baseline, MISSING_EVALUATED_SECTION

    # Act
    gained = _rules_newly_evaluated(gate_run.evaluated, baseline)

    # Assert
    assert not gained, (
        f"{len(gained)} rule(s) reach a verdict that {EVALUATED_SECTION} in "
        f"{BASELINE_PATH.name} does not list:\n"
        f"{_describe_evaluated(gained, _outcome_index(gate_run.runs))}\n"
        "Bank them with REGEN_VALIDATION_BASELINE=1 so leg (m) holds these verdicts too. A "
        "rule reaching only VACUOUS is also new under known_vacuous_rules and needs its "
        "written reason there."
    )


def test_a_rule_darkened_on_its_only_run_fails_leg_m_alone(gate_run: GateRun) -> None:
    """Leg (m) watched failing on a real row-drop, with every other leg blind to it.

    A leg nobody has watched fail is a claim, not a gate (LESSONS C12). This
    drops ONE emitted row from ONE run's COREP bundle — the case the module
    docstring measured — re-judges only that run, folds the matrix again, and
    compares every population a leg reads. It asserts both halves: the rules
    whose only verdict was on that run leave the verdict set (so (m) fires,
    naming them), and nothing legs (a)-(l) compare moves (so without (m) the
    darkening is invisible, which is why (m) is not redundant).

    Two adequacy checks come first, each a reason this test could pass while
    proving nothing: the re-generated run must reproduce the gate's own verdicts
    (or a difference is not the row-drop's), and the drop must darken at least
    one rule whose only verdict was there (or (m) has nothing to catch).

    Arrange: the probe run re-generated, checked against the gate, then the probe
             row dropped from its C 02.00.
    Act:     re-judge that run and fold the matrix again with it in place.
    Assert:  exactly the rules whose last verdict was on that run leave the
             verdict set, and every population of legs (a)-(l) is unchanged.
    """
    if REGEN:
        pytest.skip("REGEN_VALIDATION_BASELINE=1 - baseline rewritten by the companion test")

    # Arrange
    regime, portfolio = PROBE_RUN
    run = next(item for item in RUNS if (item.regime, item.portfolio) == PROBE_RUN)
    stored = next(item for item in gate_run.runs if (item.regime, item.portfolio) == PROBE_RUN)
    corep, pillar3, floor = _generate_run(run)
    assert _statuses(_judge_run(run, corep, pillar3, floor)) == _statuses(stored), (
        f"re-generating {regime}/{portfolio} did not reproduce the gate's verdicts, so a "
        "change below could not be attributed to the dropped row"
    )
    c_02_00 = corep.c_02_00
    assert c_02_00 is not None and c_02_00.filter(pl.col("row_ref") == PROBE_ROW).height == 1, (
        f"{regime}/{portfolio} emits no C 02.00 r{PROBE_ROW} to drop - the probe is vacuous"
    )
    dropped = dataclasses.replace(corep, c_02_00=c_02_00.filter(pl.col("row_ref") != PROBE_ROW))
    index = _outcome_index(gate_run.runs)

    # Act
    probe = _judge_run(run, dropped, pillar3, floor)
    mutated = _fold_runs(tuple(probe if item is stored else item for item in gate_run.runs))
    dark = _rules_newly_unevaluated(mutated.evaluated, gate_run.evaluated)

    # Assert
    before, after = _statuses(stored), _statuses(probe)
    darkened_here = {
        RuleKey(regime, rule_id)
        for rule_id, status in before.items()
        if status in VERDICT_STATUSES and after.get(rule_id) == STATUS_NOT_EVALUATED
    }
    last_verdict_here = {
        key
        for key in darkened_here
        if {name for name, outcome in index[key].items() if outcome.status in VERDICT_STATUSES}
        == {portfolio}
    }
    assert last_verdict_here, (
        f"dropping C 02.00 r{PROBE_ROW} from {regime}/{portfolio} darkens "
        f"{sorted(key.describe() for key in darkened_here)} there, none of which had its only "
        "verdict on that run, so leg (m) has nothing to catch and this test proves nothing. "
        "If a fixture now gives them a verdict elsewhere, that is progress: re-point "
        "PROBE_RUN / PROBE_ROW at a row whose rules are evaluated on one run only."
    )
    assert dark == tuple(sorted(last_verdict_here)), (
        f"leg (m) would name {[key.describe() for key in dark]}, not the rules whose last "
        f"verdict the row-drop removed: {sorted(key.describe() for key in last_verdict_here)}"
    )
    moved = [
        name
        for name, original, changed in (
            ("(a)/(b) known_broken_rules", set(gate_run.broken), set(mutated.broken)),
            ("(c)/(d) known_uncovered_templates", set(gate_run.uncovered), set(mutated.uncovered)),
            ("(f)/(g) known_vacuous_rules", set(gate_run.vacuous), set(mutated.vacuous)),
            ("(h)/(i) known_gateway_breaks", set(gate_run.gateway), set(mutated.gateway)),
            (
                "(j)/(k) known_engine_disagreements",
                set(gate_run.disagreements),
                set(mutated.disagreements),
            ),
            (
                "(l) gateway unsatisfied counts",
                {(key, fact.unsatisfied) for key, fact in gate_run.gateway.items()},
                {(key, fact.unsatisfied) for key, fact in mutated.gateway.items()},
            ),
        )
        if original != changed
    ]
    assert not moved, (
        f"the row-drop also moved {moved}, so this no longer shows that leg (m) is the only "
        "leg that sees a rule losing its last verdict"
    )


def test_the_summary_keeps_unevaluable_rules_apart_from_passes(gate_run: GateRun) -> None:
    """A rule that cannot be evaluated is not a rule that passes.

    Conflating the two is precisely how a coverage hole hides, so every status is
    recorded separately and no headline figure can be flattered by rules that
    never ran.

    This asserts the SHAPE of the summary, not its figures — the counts move with
    every fixture change. It is deliberately NOT the vacuity gate: keeping the
    ``VACUOUS`` column in the summary was all this file used to do about vacuity,
    and four counts adding up to ``rules_enforced`` is satisfied just as neatly
    after a rule falls out of ``PASS`` into ``VACUOUS`` (or ``NOT_EVALUATED``) as
    before. Legs (f)/(g) ratchet the vacuous rules themselves, and legs (m)/(n)
    the set of rules evaluated at all.

    Arrange: the runs of ``RUNS``.
    Act:     read the per-run summary.
    Assert:  all four outcome statuses are reported for every run, and together
             they account for exactly the enforced population.
    """
    # Arrange
    statuses = (STATUS_PASS, STATUS_FAIL, STATUS_VACUOUS, STATUS_NOT_EVALUATED)

    # Act / Assert
    for run_key, counts in gate_run.summary.items():
        assert set(statuses) <= set(counts), f"{run_key}: summary drops an outcome status"
        assert sum(counts[status] for status in statuses) == counts["rules_enforced"], (
            f"{run_key}: outcome counts do not account for the enforced population"
        )


# ---------------------------------------------------------------------------
# The output-floor state census
# ---------------------------------------------------------------------------


def test_the_floor_census_sees_every_basel_3_1_run_and_no_crr_run(gate_run: GateRun) -> None:
    """Leg (m): every Basel 3.1 run carries a floor state; no CRR run carries one.

    A Basel 3.1 run with no ``OutputFloorSummary`` would sit outside legs (n)-(p)
    without a word — the census failing open. Under CRR there is no floor to
    record: Art. 92(3) sums points (a) to (f) with no maximum, and the CRR pack's
    ``output_floor`` Feature is off, so a CRR run that carried a summary would be
    a regime leak.

    Arrange: the runs of ``RUNS``, split by framework.
    Act:     read which runs the census recorded a floor state for.
    Assert:  exactly the Basel 3.1 runs; the CRR runs are exactly the unfloored.
    """
    # Arrange
    basel_3_1 = {f"{run.regime}/{run.portfolio}" for run in RUNS if run.framework == "BASEL_3_1"}
    crr = {f"{run.regime}/{run.portfolio}" for run in RUNS if run.framework == "CRR"}

    # Act
    floored = set(gate_run.floors)
    unfloored = set(gate_run.unfloored)

    # Assert
    assert floored == basel_3_1, (
        "the output-floor census does not see every Basel 3.1 run: no floor state for "
        f"{sorted(basel_3_1 - floored)}; a floor state on a non-Basel 3.1 run for "
        f"{sorted(floored - basel_3_1)}"
    )
    assert unfloored == crr, f"runs with no OutputFloorSummary: {sorted(unfloored)}"


def test_the_output_floor_binds_on_exactly_the_banked_runs(gate_run: GateRun) -> None:
    """Leg (n): the binding set is ``BINDING_FLOOR_RUNS``, two-way, as a set.

    PS1/26 Art. 92(2A) puts every return in one of two states, and a published
    rule over a floored figure has a branch for each. A run leaving the binding
    state takes every rule's binding branch out of the estate (``boe_b0751`` /
    ``boe_b0763`` were never evaluated there until a run first bound); a run
    entering it is a capital move to explain. Either way the constant is edited
    in the same change, with the reason.

    Arrange: the census over every Basel 3.1 run.
    Act:     set-diff the runs whose engine floor binds against the banked set.
    Assert:  nothing gained, nothing lost.
    """
    # Arrange
    floors = gate_run.floors

    # Act
    moves = diff(_binding_runs(floors), BINDING_FLOOR_RUNS)

    # Assert
    detail = "\n".join(
        f"  {verb} {run}: {floors[run].describe() if run in floors else 'not in RUNS'}"
        for verb, runs in (("now binds:", moves.added), ("no longer binds:", moves.removed))
        for run in runs
    )
    assert not moves.added and not moves.removed, (
        f"the Basel 3.1 runs whose output floor binds have moved from "
        f"{sorted(BINDING_FLOOR_RUNS)}:\n{detail}\n"
        "If the move is intended, edit BINDING_FLOOR_RUNS (and FLOOR_STATE_SHAPES if the "
        "shapes moved too) and say why in the same change. A banked run that no longer "
        "binds takes every published rule's binding branch out of the estate."
    )


def test_the_reported_floor_activation_agrees_with_the_engine(gate_run: GateRun) -> None:
    """Leg (o): OF 02.00 row 0034 says Yes exactly where the engine floor binds.

    The two are computed apart. The engine floors the modelled subset with a
    strict ``>`` (``engine/aggregator/_floor.py``); Annex II p.29 activates the
    floor when row 0010 column 0030 is "equal to or greater than" column 0010,
    over the whole book, and ``boe_b0383`` holds the return to that. Where they
    part, the return files a state the engine did not apply, or the reverse —
    the output-floor-subset defect (P1.367, plan line 204) showing on a
    registered book. None of the registered runs shows it today.

    Arrange: the census over every Basel 3.1 run.
    Act:     list the runs whose reported activation is not the engine's state.
    Assert:  none.
    """
    # Arrange
    floors = gate_run.floors

    # Act
    disagreements = _activation_disagreements(floors)

    # Assert
    detail = "\n".join(f"  {run}: {floors[run].describe()}" for run in disagreements)
    assert not disagreements, (
        f"{len(disagreements)} Basel 3.1 run(s) report an output-floor state (OF 02.00 "
        f"r0034 c0030) that is not the engine's:\n{detail}\n"
        "The engine binds on the modelled subset (strict >); the return activates on "
        "the whole book (>=, Annex II p.29). See P1.367 (the output-floor-subset bullet)."
    )


def test_each_floor_state_reaches_exactly_the_banked_row_shapes(gate_run: GateRun) -> None:
    """Leg (p): the shapes each floor state reaches are ``FLOOR_STATE_SHAPES``, two-way.

    Registered, live and binding is not enough: the binding run must hold the row
    a rule is written over, or that rule's binding branch is never evaluated. The
    binding state reaches one of the six shapes today and owes five (see
    ``FLOOR_STATE_SHAPES``); the slack state reaches all six. A shape that joins
    either state is coverage to bank; one that leaves is coverage lost.

    Arrange: the census over every Basel 3.1 run.
    Act:     union the runs' shapes per floor state and diff each against the bank.
    Assert:  no state gains or loses a shape.
    """
    # Arrange
    reached = _shapes_by_state(gate_run.floors)

    # Act
    moves = {state: diff(reached[state], banked) for state, banked in FLOOR_STATE_SHAPES.items()}

    # Assert
    detail = "\n".join(
        f"  {state}: gained {list(move.added)}, lost {list(move.removed)}"
        for state, move in moves.items()
        if move.added or move.removed
    )
    assert not detail, (
        f"the row shapes the output-floor states reach have moved:\n{detail}\n"
        "Bank a gain in FLOOR_STATE_SHAPES (a binding-state gain closes owed coverage). "
        "A loss means the registered runs no longer put that row in that state, and every "
        "published rule over it has lost that branch."
    )
