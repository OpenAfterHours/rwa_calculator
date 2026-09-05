"""
Supervisory validation gate — the published rules, ratcheted against a baseline.

Pipeline position:
    reporting portfolios -> PipelineOrchestrator -> COREP + Pillar 3 bundles
        -> evaluate_all (EBA rules under CRR, BoE rules under Basel 3.1)
        -> known-breaks + known-uncovered baseline

Why this is not a plain "no failures" assertion: the estate currently breaks a
known set of published rules, leaves a known set of templates unchecked, and
executes a known set of rules that assert nothing. Asserting zero of any of
those would fail permanently and be switched off; asserting nothing would let a
new defect land unnoticed. So the gate is a RATCHET over a committed liability
register, applied to ALL THREE populations:

  (a) no broken rule outside the baseline           — the regression gate;
  (b) no baseline rule that no longer breaks        — a fix must shrink it;
  (c) no uncovered template outside the baseline    — a new blind spot fails;
  (d) no baseline template that is now covered      — closing one must shrink it;
  (e) every entry carries a written reason          — a register, not a hash;
  (f) no rule falls to vacuous outside the baseline — a PASS -> VACUOUS fails;
  (g) no baseline vacuous rule that now asserts     — activation must shrink it.

An Error-severity break rejects the entire return at submission, so every
``ERROR`` line in the register is a blocking filing defect.

All seven legs share ONE set-diff (P5.41):
    The arithmetic behind "new" and "gone" is ``scripts/tolerated_findings.py``
    ``::diff``, extracted from this file so that this register and the two
    DECLARED ones — ``tests/oracle/test_oracle.py::KNOWN_DISAGREEMENTS`` and
    ``tests/conformance/classification_table.toml``'s ``[[known_disagreement]]``
    — cannot drift apart on what a movement means. Four registers of the same
    shape were four places to get the direction wrong.

    The mechanism is shared; the POLICY is not, and the difference is
    deliberate. This register stays TWO-WAY: its membership is measured over
    twenty pipeline runs, so a fixture change legitimately grows it and
    ``REGEN_VALIDATION_BASELINE=1`` may bank that. The declared registers are
    SHRINK-ONLY, with no bulk affordance that adds an entry at all, because an
    entry there is a decision to ship a figure an independent derivation has
    shown is wrong. Each caller states which it is.

Why (c)/(d) matter as much as (a)/(b): ``check_supervisory_validations`` FAILS
OPEN. On a bundle it cannot read, every rule is NOT_EVALUATED, so there are no
breaks and the result is indistinguishable from a clean estate. A shrinking
break set is only evidence of progress if coverage held — so coverage is
ratcheted too, and the per-run summary keeps NOT_EVALUATED separate from PASS
rather than letting unevaluable rules flatter a headline figure.

Why (f)/(g) exist — the third way this gate used to fail open:
    A rule whose every operand is null or exactly zero is scored ``VACUOUS``:
    it reached a verdict, the verdict held, and it asserted NOTHING (see
    ``reporting/validations/evaluate.py::_Context.observe`` and
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

    FIRST, the union. Membership is the union over the twenty runs: a rule is
    vacuity-only when NO run gets a real verdict out of it. A change that empties
    a column on ONE portfolio while another still exercises the same rule leaves
    this population unmoved, and 221 rules (130 of them ERROR) currently hold a
    real verdict on exactly one run, so that is a wide surface. It cuts both ways
    on leg (g): a listed rule only leaves the population when the change reaches
    EVERY run where it was vacuous. Measured instance — ``crr/v3332_i`` is
    vacuous on both ``rich`` and ``crm-substitution``, so darkening it on ``rich``
    keeps it in the register and (g) stays green.

    SECOND, and this is the real hole: these legs are scoped to the ``VACUOUS``
    status. ``PASS -> NOT_EVALUATED`` escapes all six legs of this gate. Dropping
    one emitted row (``C 02.00`` r0160) from ``crr/rich`` moves two ERROR rules
    out of ``PASS`` into ``NOT_EVALUATED`` — one of them ``v3335_i``, which passed
    on ``rich`` alone, so afterwards it has no verdict anywhere in the matrix —
    and every leg here stays green with ``templates_uncovered`` unmoved, because a
    darkened rule is not a break, not a vacuity, and does not uncover its
    template. The worked example is ``v0207_m``: an ERROR rule on the C 02.00
    hierarchy that PASSes on six portfolios today and is VACUOUS on the other two,
    and which BOTH of that reviewer's mutations darken. It is a handful of dropped
    rows from silently joining ``v0204_m`` / ``v0205_m`` / ``v0210_m`` /
    ``v0211_m`` — four live ERROR rules that are already evaluated NOWHERE in the
    matrix, and which no leg here objects to.

    The mitigation, and its limits. ``scripts/coverage_report.py --check``
    ratchets ``never_evaluated_rules`` (a MAX, banked at 785) and
    ``union_binding_rules_{crr,b31}`` (a MIN, 257/289), and by those definitions
    the row-drop moves both. But (i) that is inference from the metric
    definitions, not a measured ``--check`` under the mutation; (ii) both are
    COUNTS, so one rule going dark while another activates nets to zero; and
    (iii) it is a DIFFERENT gate from this one, and this file is the mandatory
    Tier 2 register. So the ``NOT_EVALUATED`` half is mitigated, not closed, and
    it is owed work — not a property of legs (f)/(g).

    Where the single-portfolio case actually goes, stated per portfolio rather
    than waved at ``test_reporting_*_golden.py``: only SIX goldens exist — rich,
    ccr, irb-classes, off-bs, sa-classes and netting. ``crm-substitution``,
    ``re-split``, ``art199`` and ``irb-shapes`` have NO golden, only focused
    acceptance tests pinning the columns
    each fixture was built for: strong on those columns, silent elsewhere. Golden
    coverage for those four is owed work too.

Cost, and why every run is load-bearing:
    This file is the most expensive test in the suite: ten portfolios x two
    regimes, plus a prior-period run for each of the ten IRB ones, is
    THIRTY full pipeline runs. That is a standing temptation to trim the run set, so
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
    - ``crm-substitution`` the ONLY portfolio with a non-zero CRM-substitution
                           cell anywhere in the estate (C 07.00 cols
                           0050/0060/0090/0100, C 08.01 cols
                           0040/0050/0070/0080, C 08.02 col 0080) — the sole
                           route to every rule written over the
                           outflow/inflow columns.
    - ``netting``          the ONLY portfolio whose on-balance-sheet netting
                           agreement spans more than one counterparty, and so
                           the only route to C 07.00 col 0035 ("(-) Adjustment
                           due to on-balance sheet netting", Basel 3.1 sheet
                           only) carrying a figure at all.

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
    entry-by-entry), ``known_broken_rules``, ``known_uncovered_templates`` and
    ``known_vacuous_rules``.

Regenerating the baseline:
    Set ``REGEN_VALIDATION_BASELINE=1`` and run this file. Hand-written
    ``reason`` text is PRESERVED — regeneration refreshes the population and the
    recorded coordinates, never the curation. An entry nobody has written about
    gets the ``unclassified`` placeholder and must be given a real reason before
    the register is committed; where the mechanism is visible but the defect is
    not established, the honest reason is the greppable ``unattributed - needs
    investigation``, not a guess. Never bulk-regen to make a red gate green: a
    new break is a new filing defect until someone has said otherwise in writing.
    The same applies to a new ``known_vacuous_rules`` entry: a rule that has
    stopped asserting anything is a check we have LOST, so it is banked only with
    a written account of what emptied it.

    CHECK FOR STALE REASONS after every regeneration. Preserving curation is
    right up until the thing a reason CITES gets fixed, and then it rots
    silently: five entries once carried "…see crr/v4756_m" after ``v4756_m`` had
    left the register entirely. Grep each surviving reason for rule-id patterns
    (``v\\d{4,5}_[a-z]``, ``boe_b\\d{4}``) and check the ids still exist here.
    Some references are deliberate — ``boe_b0710`` cites ``v6364_m`` and
    ``v4721_m`` cites ``v4728_m`` precisely BECAUSE those rules pass for us — so
    the check is a prompt to look, not a rule. Where a cited rule has been fixed,
    RE-MEASURE the entry rather than editing its prose: the surrounding defect
    has usually changed shape too.

References:
- tests/acceptance/reporting/test_reporting_golden.py — the run-and-generate pattern
- src/rwa_calc/reporting/validations/ — the evaluator
- COREP Annex II (CRR); PRA PS1/26 Annex II (Basel 3.1)
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Sequence
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

import pytest
from scripts.tolerated_findings import diff
from tests.acceptance.reporting.test_reporting_golden import _b31_config, _crr_config
from tests.fixtures.reporting_ccr_portfolio import build_reporting_ccr_bundle
from tests.fixtures.reporting_crm_substitution_portfolio import (
    build_reporting_crm_substitution_bundle,
)
from tests.fixtures.reporting_funded_protection_portfolio import (
    build_reporting_art199_bundle,
)
from tests.fixtures.reporting_irb_classes_portfolio import build_reporting_irb_classes_bundle
from tests.fixtures.reporting_irb_shapes_portfolio import build_reporting_irb_shapes_bundle
from tests.fixtures.reporting_netting_portfolio import build_reporting_netting_bundle
from tests.fixtures.reporting_offbs_portfolio import build_reporting_offbs_bundle
from tests.fixtures.reporting_portfolio import build_reporting_bundle
from tests.fixtures.reporting_re_split_portfolio import build_reporting_re_split_bundle
from tests.fixtures.reporting_sa_classes_portfolio import build_reporting_sa_classes_bundle

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from rwa_calc.reporting.corep.generator import COREPGenerator
from rwa_calc.reporting.pillar3.generator import Pillar3Generator
from rwa_calc.reporting.validations import (
    STATUS_FAIL,
    STATUS_NOT_EVALUATED,
    STATUS_PASS,
    STATUS_VACUOUS,
    evaluate_all,
)

if TYPE_CHECKING:
    from rwa_calc.contracts.bundles import RawDataBundle

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

#: Sample cells recorded per vacuous rule. A vacuous rule has NO failing
#: coordinate — that is the whole point of it — so the tables it addresses and
#: the count of coordinates it held over vacuously are the only triage handles
#: the evaluator can give, and they are recorded instead.
MAX_RECORDED_TABLES = 5

#: Header written into the register on every regeneration, so the file explains
#: how to read itself to someone who never saw this module. Emitted from here
#: rather than hand-added to the JSON, which a regeneration would discard.
REGISTER_NOTES: dict[str, str] = {
    "what_this_is": (
        "Known supervisory validation breaks, coverage holes and VACUOUS rules, ratcheted by "
        "tests/acceptance/reporting/test_supervisory_validations.py. An entry is a LIABILITY, "
        "not a waiver: an ERROR-severity break rejects the entire return at submission."
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
        "Two limits, both measured, both stated because a green leg is otherwise read as more "
        "than it is. (1) UNION: a change that empties a column on one portfolio while another "
        "still gets a real verdict out of the same rule moves nothing here, and 221 rules (130 "
        "ERROR) currently hold a real verdict on exactly ONE run. Same masking on the removal "
        "leg: crr/v3332_i is vacuous on both rich and crm-substitution, so darkening it on rich "
        "leaves the entry standing. (2) STATUS SCOPE: these legs see VACUOUS only, so "
        "PASS -> NOT_EVALUATED escapes every leg of this gate - dropping one emitted row (C 02.00 "
        "r0160) from crr/rich darkens two ERROR rules, one of them (v3335_i) passing on rich "
        "alone, and the whole gate stays green. scripts/coverage_report.py --check mitigates that "
        "by ratcheting never_evaluated_rules (max 785) and union_binding_rules (min 257/289), but "
        "those are counts in a different gate, so one rule going dark nets against another "
        "activating. The NOT_EVALUATED half is owed work, not a property of this register."
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
        "structurally absent: absence is NOT_EVALUATED, which is worse than vacuity, not better - "
        "and per what_the_vacuity_ratchet_does_NOT_catch, that route may not even redden a leg, so "
        "nothing here will stop you doing it."
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
        "by our reporting nothing there. reporting/validations/evaluate.py::_evaluate_emptiness "
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
        "one grade row. Same shape as boe_b0779 on c0050 and v09782_m/v09783_m on C 08.06's "
        "risk-weight column. Recognise it before re-deriving it a fourth time."
    ),
    "pattern_empty_subrow_vs_negated_column": (
        "An inequality between an 'of which' sub-row and its parent inverts when the parent "
        "is a genuinely negative Annex II Sec.1.3 '(-)' deduction column and the sub-row's own "
        "subset is empty: our empty-subset convention renders the sub-row ALL-NULL, the "
        "evaluator coalesces that null to 0.0 for the comparison, and 0 <= a negative number "
        "reads false however correct that negative figure is. Same shape as the zero-exposure "
        "ratio family (boe_b0778/v09782_m and boe_b0779's 'no emptiness guard' — see the caution "
        "on unattributed entries above before assuming the parent's negative figure is itself "
        "the bug, as it genuinely was in the boe_b0378 worked example there)."
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
        "which is inherent to covering IRB off-balance-sheet exposure at all."
    ),
}


def _sa_config(framework: str) -> CalculationConfig:
    """STANDARDISED config, matching the off-BS and CCR goldens.

    C 07.00 is the SA template and its CCF-bucket columns are defined over the
    Art. 111 / PS1/26 Table A1 schedule; an F-IRB conversion factor has no bucket
    on this template to land in.
    """
    if framework == "CRR":
        return CalculationConfig.crr(
            reporting_date=date(2025, 12, 31), permission_mode=PermissionMode.STANDARDISED
        )
    return CalculationConfig.basel_3_1(
        reporting_date=date(2027, 6, 1), permission_mode=PermissionMode.STANDARDISED
    )


def _irb_config(framework: str) -> CalculationConfig:
    """IRB config, matching the IRB-classes goldens.

    ``enforce_retail_granularity=False`` on the Basel 3.1 arm, exactly as the rich
    portfolio does. Without it the Art. 123A(1)(b)(ii) 0.2%-of-portfolio limb is
    unsatisfiable for a compact oracle portfolio, every natural-person row
    reclassifies to corporate, and the retail-mortgage and QRRE sheets vanish —
    silently undoing the C 08.xx sheet-axis coverage this portfolio exists for.

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


#: The twenty runs, each the sole reachability route for a family of published
#: rules. See "Cost, and why every run is load-bearing" in the module docstring
#: before trimming this list — a dropped run does not make its rules pass, it
#: makes them NOT_EVALUATED, which reads the same on the error channel.
#:
#: The count in this comment read "sixteen" until the ``netting`` pair below was
#: added: it had already gone stale when ``art199`` and ``irb-shapes`` were
#: registered. Count the tuple, not the prose.
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
)


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


class GateRun(NamedTuple):
    """Everything the twenty runs produced.

    ``summary`` is per-run outcome counts, kept descriptive: nothing asserts an
    individual count, only that the four statuses are all reported and account
    for the enforced population. Vacuity used to live ONLY there, which is why it
    was invisible — the ratcheted population is ``vacuous``, at rule granularity.
    """

    broken: dict[RuleKey, RuleFact]
    uncovered: dict[TemplateKey, int]
    summary: dict[str, dict[str, int]]
    vacuous: dict[RuleKey, VacuityFact]


# ---------------------------------------------------------------------------
# Running the estate
# ---------------------------------------------------------------------------


def _run_gate() -> GateRun:
    """Evaluate every enforced rule over every portfolio/regime combination.

    ``broken`` is the union over portfolios, keyed by rule: a rule breaking on
    more than one portfolio is ONE defect, and the portfolios it was seen on are
    recorded on the entry.

    ``uncovered`` is per run, because whether a template was checked depends on
    which portfolio emitted it — C 34.x exists only on the CCR portfolio.

    ``summary`` keeps PASS, FAIL, VACUOUS and NOT_EVALUATED apart. Conflating the
    last two with PASS is how a coverage hole hides.

    ``vacuous`` is the union too, and is the set of rules that reached a verdict
    ONLY vacuously — vacuous on at least one run and never PASS or FAIL on any.
    A rule vacuous here and passing there is still being checked somewhere, so it
    is not a lost check; a rule that only ever holds at ``0 = 0`` is. That is why
    ``real_verdict`` is accumulated across every run before the filter is applied,
    rather than deciding membership run by run.
    """
    broken: dict[RuleKey, RuleFact] = {}
    uncovered: dict[TemplateKey, int] = {}
    summary: dict[str, dict[str, int]] = {}
    vacuous: dict[RuleKey, VacuityFact] = {}
    real_verdict: set[RuleKey] = set()
    for regime, framework, portfolio, build_bundle, build_config, build_prior in RUNS:
        result = PipelineOrchestrator().run_with_data(build_bundle(), build_config())
        prior = (
            PipelineOrchestrator().run_with_data(build_bundle(), build_prior())
            if build_prior is not None
            else None
        )
        corep = COREPGenerator().generate_from_lazyframe(
            result.results,
            framework=framework,
            previous_period_results=None if prior is None else prior.results,
        )
        pillar3 = Pillar3Generator().generate_from_lazyframe(result.results, framework=framework)

        report = evaluate_all(corep, pillar3, framework)
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
        broken,
        uncovered,
        summary,
        {key: fact for key, fact in vacuous.items() if key not in real_verdict},
    )


@pytest.fixture(scope="module")
def gate_run() -> GateRun:
    """The twenty runs, executed once for this file.

    ``--dist=loadfile`` pins this file to one worker, so the pipeline runs happen
    once per session rather than once per test.
    """
    return _run_gate()


# ---------------------------------------------------------------------------
# Baseline read / write
# ---------------------------------------------------------------------------


class Baseline(NamedTuple):
    """The committed register, as three ``{key: reason}`` maps.

    Named rather than a bare tuple because there are three populations now and a
    positional unpack (``_, baseline = _read_baseline()``) silently reads the
    wrong one the moment a fourth is added.
    """

    rules: dict[RuleKey, str]
    templates: dict[TemplateKey, str]
    vacuous: dict[RuleKey, str]


def _read_baseline() -> Baseline:
    """Load the committed register as three ``{key: reason}`` maps."""
    if not BASELINE_PATH.exists():
        return Baseline({}, {}, {})
    payload = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    rules = {
        RuleKey(*(entry[field] for field in RULE_KEY_FIELDS)): entry["reason"]
        for entry in payload.get("known_broken_rules", [])
    }
    templates = {
        TemplateKey(*(entry[field] for field in TEMPLATE_KEY_FIELDS)): entry["reason"]
        for entry in payload.get("known_uncovered_templates", [])
    }
    vacuous = {
        RuleKey(*(entry[field] for field in RULE_KEY_FIELDS)): entry["reason"]
        for entry in payload.get("known_vacuous_rules", [])
    }
    return Baseline(rules, templates, vacuous)


def _write_baseline(run: GateRun) -> None:
    """Rewrite the register, PRESERVING every hand-written reason that still applies.

    Only the reason is curated. Severity, coordinates, portfolios and the summary
    are facts about the current estate and are always refreshed.
    """
    existing_rules, existing_templates, existing_vacuous = _read_baseline()
    payload = {
        "notes": REGISTER_NOTES,
        "summary": run.summary,
        "known_broken_rules": [
            {
                "regime": key.regime,
                "rule_id": key.rule_id,
                "severity": fact.severity,
                "reason": existing_rules.get(key, UNCLASSIFIED),
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
                "reason": existing_templates.get(key, UNCLASSIFIED),
                "rules_executed_on_this_run": executed,
            }
            for key, executed in sorted(run.uncovered.items())
        ],
        "known_vacuous_rules": [
            {
                "regime": key.regime,
                "rule_id": key.rule_id,
                "severity": fact.severity,
                "reason": existing_vacuous.get(key, UNCLASSIFIED),
                "portfolios": sorted(set(fact.portfolios)),
                "vacuous_coordinates": fact.vacuous_coordinates,
                "tables": list(fact.tables),
                "expression": fact.expression,
            }
            for key, fact in sorted(run.vacuous.items())
        ],
    }
    BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
    BASELINE_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# The vacuity ratchet, as two named predicates
# ---------------------------------------------------------------------------
# Extracted rather than inlined like legs (a)-(d), for one reason: a gate nobody
# has watched fail is not a gate, and watching THIS one fail through the tests
# costs twenty pipeline runs plus a fixture change. Named functions over plain
# dicts can be driven with a synthetic measured-vs-baseline pair in seconds, so
# both directions are demonstrable on demand instead of argued from the code.
#
# All seven legs now route their set arithmetic through ONE mechanism —
# `scripts/tolerated_findings.py::diff`, extracted under P5.41 so this register
# and the two declared ones (`KNOWN_DISAGREEMENTS`,
# `classification_table.toml`'s `[[known_disagreement]]`) cannot drift apart on
# what "new" and "gone" mean. `diff` is deliberately direction-NEUTRAL: it
# reports both sides and each caller decides which is a failure. This register
# stays two-way — an increase may be banked with REGEN_VALIDATION_BASELINE=1,
# because its membership is MEASURED over twenty pipeline runs and a fixture
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

    All THREE populations are checked. A vacuity entry without a reason is the
    worst of the three to leave lying around: it looks like a passing rule.

    Arrange: the committed register.
    Act:     find entries still carrying the capture placeholder.
    Assert:  there are none.
    """
    if REGEN:
        pytest.skip("REGEN_VALIDATION_BASELINE=1 - reasons are written by hand after capture")

    # Arrange
    rules, templates, vacuous = _read_baseline()

    # Act
    untriaged = sorted(key.describe() for key, reason in rules.items() if reason == UNCLASSIFIED)
    untriaged += sorted(
        key.describe() for key, reason in templates.items() if reason == UNCLASSIFIED
    )
    untriaged += sorted(
        f"{key.describe()} (vacuous)" for key, reason in vacuous.items() if reason == UNCLASSIFIED
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
    discharge; absence is a regression wearing the same shirt.

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


def test_the_summary_keeps_unevaluable_rules_apart_from_passes(gate_run: GateRun) -> None:
    """A rule that cannot be evaluated is not a rule that passes.

    Conflating the two is precisely how a coverage hole hides, so every status is
    recorded separately and no headline figure can be flattered by rules that
    never ran.

    This asserts the SHAPE of the summary, not its figures — the counts move with
    every fixture change. It is deliberately NOT the vacuity gate: keeping the
    ``VACUOUS`` column in the summary was all this file used to do about vacuity,
    and four counts adding up to ``rules_enforced`` is satisfied just as neatly
    after a rule falls out of ``PASS`` into ``VACUOUS`` as before. Legs (f)/(g)
    ratchet the rules themselves.

    Arrange: the twenty runs.
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
