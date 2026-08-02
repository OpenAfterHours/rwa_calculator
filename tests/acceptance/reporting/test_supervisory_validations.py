"""
Supervisory validation gate — the published rules, ratcheted against a baseline.

Pipeline position:
    reporting portfolios -> PipelineOrchestrator -> COREP + Pillar 3 bundles
        -> evaluate_all (EBA rules under CRR, BoE rules under Basel 3.1)
        -> known-breaks + known-uncovered baseline

Why this is not a plain "no failures" assertion: the estate currently breaks a
known set of published rules, and leaves a known set of templates unchecked.
Asserting zero of either would fail permanently and be switched off; asserting
nothing would let a new defect land unnoticed. So the gate is a RATCHET over a
committed liability register, applied to BOTH populations:

  (a) no broken rule outside the baseline           — the regression gate;
  (b) no baseline rule that no longer breaks        — a fix must shrink it;
  (c) no uncovered template outside the baseline    — a new blind spot fails;
  (d) no baseline template that is now covered      — closing one must shrink it;
  (e) every entry carries a written reason          — a register, not a hash.

An Error-severity break rejects the entire return at submission, so every
``ERROR`` line in the register is a blocking filing defect.

Why (c)/(d) matter as much as (a)/(b): ``check_supervisory_validations`` FAILS
OPEN. On a bundle it cannot read, every rule is NOT_EVALUATED, so there are no
breaks and the result is indistinguishable from a clean estate. A shrinking
break set is only evidence of progress if coverage held — so coverage is
ratcheted too, and the per-run summary keeps NOT_EVALUATED separate from PASS
rather than letting unevaluable rules flatter a headline figure.

Why the key is ``(regime, rule_id)`` and not the failing coordinate:
    Coordinates are recorded on each entry for triage, but they are NOT the key.
    ``RuleOutcome.failures`` is capped at ``MAX_RECORDED_FAILURES``, and a
    substantial minority of failing rules exceed that cap (it was 20 of 75 when
    this was measured) — so partially fixing one shifts the recorded window and
    would manufacture a spurious "new break" alongside the real "now fixed". The
    regime prefix is load-bearing in its own right: 85 rule ids appear in BOTH
    published extracts (``v09779_m`` was a live case, failing under each), so a
    key on ``rule_id`` alone silently drops half.

Cost, and why every run is load-bearing:
    This file is the most expensive test in the suite: six portfolios x two
    regimes, plus a prior-period run for each of the six IRB ones, is EIGHTEEN
    full pipeline runs. That is a standing temptation to trim the run set, so
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

    Measured: ``sa-classes`` and ``irb-classes`` together move 53 CRR and 32
    Basel 3.1 rules out of NOT_EVALUATED. The six prior-period runs exist
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
    object with ``summary`` (per-run outcome counts, informational),
    ``known_broken_rules`` and ``known_uncovered_templates``.

Regenerating the baseline:
    Set ``REGEN_VALIDATION_BASELINE=1`` and run this file. Hand-written
    ``reason`` text is PRESERVED — regeneration refreshes the population and the
    recorded coordinates, never the curation. An entry nobody has written about
    gets the ``unclassified`` placeholder and must be given a real reason before
    the register is committed; where the mechanism is visible but the defect is
    not established, the honest reason is the greppable ``unattributed - needs
    investigation``, not a guess. Never bulk-regen to make a red gate green: a
    new break is a new filing defect until someone has said otherwise in writing.

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
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

import pytest
from tests.acceptance.reporting.test_reporting_golden import _b31_config, _crr_config
from tests.fixtures.reporting_ccr_portfolio import build_reporting_ccr_bundle
from tests.fixtures.reporting_crm_substitution_portfolio import (
    build_reporting_crm_substitution_bundle,
)
from tests.fixtures.reporting_irb_classes_portfolio import build_reporting_irb_classes_bundle
from tests.fixtures.reporting_offbs_portfolio import build_reporting_offbs_bundle
from tests.fixtures.reporting_portfolio import build_reporting_bundle
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

#: Header written into the register on every regeneration, so the file explains
#: how to read itself to someone who never saw this module. Emitted from here
#: rather than hand-added to the JSON, which a regeneration would discard.
REGISTER_NOTES: dict[str, str] = {
    "what_this_is": (
        "Known supervisory validation breaks and coverage holes, ratcheted by "
        "tests/acceptance/reporting/test_supervisory_validations.py. An entry is a LIABILITY, "
        "not a waiver: an ERROR-severity break rejects the entire return at submission."
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
        "it should. v0308_m/boe_b0471/v8726_m/boe_b0556 exist because that assumption was "
        "false: C 07.00's own col 0200 is Sum(ead_col) over the ORIGIN population (the F4 "
        "build, docs/plans/phase7-declarative-reporting.md, never extended substitution-"
        "awareness to it), while CR4/CR5 (reporting/pillar3/cr4.py, cr5.py) genuinely do key "
        "on the post-substitution `reporting_class` they cite the same definition for - so two "
        "parts of the estate that cite one shared basis are no longer consistent with each "
        "other. Verify a definition is IMPLEMENTED before citing it as evidence a related gap "
        "is a deliberate decision rather than a build shortfall."
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


#: The twelve runs, each the sole reachability route for a family of published
#: rules. See "Cost, and why every run is load-bearing" in the module docstring
#: before trimming this list — a dropped run does not make its rules pass, it
#: makes them NOT_EVALUATED, which reads the same on the error channel.
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


class GateRun(NamedTuple):
    """Everything the six runs produced."""

    broken: dict[RuleKey, RuleFact]
    uncovered: dict[TemplateKey, int]
    summary: dict[str, dict[str, int]]


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
    """
    broken: dict[RuleKey, RuleFact] = {}
    uncovered: dict[TemplateKey, int] = {}
    summary: dict[str, dict[str, int]] = {}
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

        for outcome in report.by_status(STATUS_FAIL):
            key = RuleKey(regime, outcome.rule_id)
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
    return GateRun(broken, uncovered, summary)


@pytest.fixture(scope="module")
def gate_run() -> GateRun:
    """The six runs, executed once for this file.

    ``--dist=loadfile`` pins this file to one worker, so the pipeline runs happen
    once per session rather than once per test.
    """
    return _run_gate()


# ---------------------------------------------------------------------------
# Baseline read / write
# ---------------------------------------------------------------------------


def _read_baseline() -> tuple[dict[RuleKey, str], dict[TemplateKey, str]]:
    """Load the committed register as two ``{key: reason}`` maps."""
    if not BASELINE_PATH.exists():
        return {}, {}
    payload = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    rules = {
        RuleKey(*(entry[field] for field in RULE_KEY_FIELDS)): entry["reason"]
        for entry in payload.get("known_broken_rules", [])
    }
    templates = {
        TemplateKey(*(entry[field] for field in TEMPLATE_KEY_FIELDS)): entry["reason"]
        for entry in payload.get("known_uncovered_templates", [])
    }
    return rules, templates


def _write_baseline(run: GateRun) -> None:
    """Rewrite the register, PRESERVING every hand-written reason that still applies.

    Only the reason is curated. Severity, coordinates, portfolios and the summary
    are facts about the current estate and are always refreshed.
    """
    existing_rules, existing_templates = _read_baseline()
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
    }
    BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
    BASELINE_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


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
    baseline, _ = _read_baseline()

    # Act
    new_breaks = sorted(key for key in gate_run.broken if key not in baseline)

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
    baseline, _ = _read_baseline()

    # Act
    stale = sorted(key for key in baseline if key not in gate_run.broken)

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
    _, baseline = _read_baseline()

    # Act
    new_holes = sorted(key for key in gate_run.uncovered if key not in baseline)

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
    _, baseline = _read_baseline()

    # Act
    closed = sorted(key for key in baseline if key not in gate_run.uncovered)

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

    Arrange: the committed register.
    Act:     find entries still carrying the capture placeholder.
    Assert:  there are none.
    """
    if REGEN:
        pytest.skip("REGEN_VALIDATION_BASELINE=1 - reasons are written by hand after capture")

    # Arrange
    rules, templates = _read_baseline()

    # Act
    untriaged = sorted(key.describe() for key, reason in rules.items() if reason == UNCLASSIFIED)
    untriaged += sorted(
        key.describe() for key, reason in templates.items() if reason == UNCLASSIFIED
    )

    # Assert
    assert not untriaged, (
        f"{len(untriaged)} baseline entry/entries were captured but never triaged. "
        f"Replace the placeholder in {BASELINE_PATH.name} with what defect each "
        "entry corresponds to:\n  " + "\n  ".join(untriaged)
    )


def test_the_summary_keeps_unevaluable_rules_apart_from_passes(gate_run: GateRun) -> None:
    """A rule that cannot be evaluated is not a rule that passes.

    Conflating the two is precisely how a coverage hole hides, so every status is
    recorded separately and no headline figure can be flattered by rules that
    never ran.

    Arrange: the six runs.
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
