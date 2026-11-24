"""
Contract: the test harness may give a class column only a value production writes there by design.

Pipeline position:
    (not a pipeline stage) — a gate over the test harness itself: the
    single-exposure builders (``tests/fixtures/single_exposure.py``), the
    contract-column pads (``tests/fixtures/contract_columns.py``), the
    stage-output bundle seals (``tests/fixtures/resolved_bundle.py``) and the
    class-column string literals written under ``tests/`` in a builder
    keyword, a parameter default or a frame dict (see "What the scan does not
    read" below).

Key responsibilities:
- The single-exposure builders hand their calculator a frame whose every row
  carries an ``ExposureClass`` value — read from the frame each one actually
  passes to ``calculate_branch`` (a recording stand-in calculator), so a
  builder that drops the column or nulls it fails as surely as one fed a
  wrong spelling. The equity builder hands none, because production's equity
  calculator input carries none; the IRB builder's default is an enum value.
- The pads and the bundle seals never hand a row on without a class: the
  crm_exit pad, the calculator-branch pads, the classifier / crm / aggregator
  exit seals behind ``make_classified_bundle`` / ``make_crm_bundle`` /
  ``make_aggregated_bundle``, and that builder's summary-frame seal all refuse
  a non-empty frame whose ``exposure_class`` is absent or null on any row
  (they neither null it nor leave it absent). They do NOT check that a
  supplied string is an ``ExposureClass`` value — that is the literal scan's
  job, and a variable-fed string is outside it (below).
- No lenient seal CALL under ``tests/`` null-completes an engine-derived
  ``exposure_class`` unguarded. Read function by function: in the two
  stage-output modules (``resolved_bundle.py``, ``contract_columns.py``) every
  ``seal_lenient`` / ``conform_lenient`` call runs
  ``require_class_on_every_row`` on the same frame first or is a named
  exemption whose edge resolves and carries no class; elsewhere an unguarded
  one must resolve to an edge with no engine-derived class. An edge that
  cannot be resolved fails. The anchor reads syntax, not control flow — see
  "What the seal anchor does not read" below.
- Every class-column keyword argument and parameter default under ``tests/``
  is in its column's harness domain — an ``ExposureClass`` value, or one of
  the column's ``PRODUCTION_EXTRA_VALUES``, the strings production writes there
  by design (only ``guarantor_exposure_class = ""``) — outside a short
  allowlist of the user-input namespaces that legitimately take another
  spelling. The class-column family is every edge-contract column that holds
  an ``ExposureClass`` value, enforced against ``rwa_calc.contracts.edges``.
- The domain is NOT everything production writes. Under CRR with IRB
  permission and ``equity_pd_lgd=True`` the Art. 155(3) PD/LGD equity branch
  leaves ``"CORPORATE"`` on six class columns (``exposure_class``,
  ``exposure_class_applied``, ``exposure_class_post_crm``, ``reporting_class``,
  ``reporting_class_origin``, ``reporting_class_pre_default``) — a known
  production defect (``OWNER: P1.480``, an open plan bullet — checked),
  declared in ``KNOWN_PRODUCTION_CLASS_DEFECTS`` with the class a fixed writer
  must leave, and refused by the harness on purpose.
  Both declarations are measured by one anchor that runs the ``rich`` portfolio
  under exactly three configs (``ANCHOR_LEGS``: CRR and Basel 3.1 defaults, and
  that CRR PD/LGD config) — a writer only another config reaches is invisible
  to it.
- The class-column frame literals that are not yet in their column's domain
  may only shrink, file by file.

Why this is a gate and not a review criterion:
    ``exposure_class`` is engine-derived. It is absent from every exposure
    input schema, and the classifier writes it as ``ExposureClass.<X>.value`` —
    lowercase and never null (``engine/classify/attributes.py``). A harness
    frame hand-writes it, so it can hand the calculators a class the
    classifier never writes, take the wrong branch of an exact-``.value`` gate
    (``engine/classify/approach.py``, ``engine/sa/rw_adjustments.py``,
    ``engine/irb/adjustments.py``, ``engine/aggregator/aggregator.py``), and
    still pass. P1.374 hit it twice in one branch — a builder that omitted the
    column (the ABSENT path) and a pad that injected a typed null (the NULL
    path) — and, measured by this module's ``class_literal_census`` over the
    pre-P5.69 ``tests/`` tree (``git archive 7dadcaf tests``, 2026-11-23), the
    estate held 264 non-member ``exposure_class=`` keyword sites in 19 files (3
    of them allowlisted CIU holdings), 6 non-member parameter defaults and 474
    non-member frame literals across 70 files. No reviewer can hold the two
    spellings apart by eye across that many sites, so the rule is executable.

Three shapes, three limbs:
    A literal scan sees only one of the three ways a harness class goes wrong.
    ABSENT and NULL (``.claude/LESSONS.md`` B1 — different code paths) are
    closed at the choke points hand frames pass through: the single-exposure
    builders (each refuses, on the frame it hands its calculator, a class that
    is absent, null or not an enum value; the builder-probe tests read that
    frame independently of the builder's own guard) and the pads and seals
    (absent or null only). A non-production STRING is closed by the builders
    and by the scan. A hand frame passed STRAIGHT to ``calculate_branch``
    passes none of these choke points — see "What the scan does not read".
    Neither ABSENT nor NULL fails loudly on its own: a null takes the null
    branch of every exact gate, and an absent column takes the silent
    presence-guard fallback of at least six engine readers (measured 2026-11-24 — every
    ``"exposure_class" in`` / ``not in`` test and ``col_or_default`` on the
    column under ``engine/``): ``engine/supporting_factors.py`` (the Art. 501a
    class limb becomes ``pl.lit(True)``), ``engine/crm/processor.py``,
    ``engine/aggregator/_securitisation.py``, ``engine/aggregator/_equity_prep.py``
    (stamps a class of its own), and ``engine/aggregator/_floor.py`` /
    ``engine/aggregator/_supporting_factors.py`` (``col_or_default``: a typed
    null).

Namespaces a value-based allowlist cannot separate:
    The SA risk-weight join tables are keyed on the upper-cased spelling of real
    enum members (``CORPORATE``, ``INSTITUTION``, ``PSE``, ``COVERED_BOND`` …),
    so an allowlist of table keys by VALUE would disarm the check for most of
    the estate. The scan instead classifies a literal by WHERE it goes: a
    builder keyword, a parameter default, or an exposure frame. Table queries
    are comparisons, never one of those three. A row of one of the two
    user-input schemas that carry the column (``CIU_HOLDINGS_SCHEMA``,
    ``MODEL_PERMISSIONS_SCHEMA``) is exempt only when it carries the schema's
    marker key AND every key is a column of that schema — ``model_id`` alone is
    not enough, because every calculator-branch edge carries it too. A dict that
    maps column names (a ``.rename({...})`` argument, or a ``NON_FRAME_DICTS``
    entry) is not a frame.

What the scan does not read:
    A class that reaches a frame through a NAME — a ``parametrize`` value list
    (``test_b31_sa_risk_weights.py`` feeds the non-member ``"RETAIL_SME"`` this
    way, ``test_lgd_floor_blended.py`` feeds ``"CORPORATE"``), a helper
    argument, a comprehension — is invisible to it: 135 class-column dict
    entries in 102 files and 32 class-column keywords in 16 files take their
    value from an expression that references a name other than ``pl`` /
    ``ExposureClass`` and spells out neither a string literal nor an
    ``ExposureClass`` member (measured 2026-11-24 on ``ab0c8c8f``,
    twelve-column family). Comparisons are not read, on purpose.
    Nor is a literal wrapped in an expression the frame-value reader does not
    unpack (it reads a string, a list or tuple, ``[...] * n`` and
    ``pl.Series([...])`` only): ``pl.lit("X").alias(<class col>)``,
    ``with_columns(<class col>=pl.lit("X"))``, ``pl.repeat("X", n)``,
    ``dict(<class col>=[...])`` (a keyword whose value is a list, not a
    string) and a conditional element (``["X" if c else "Y"]``) each score 0
    (probed 2026-11-24; the eight ``pl.lit`` class sites under ``tests/`` hold
    an enum member today, apart from one null set deliberately after a pad in
    ``tests/unit/irb/test_irb_formulas.py``, but nothing holds them there).
    The builder refusals cover the variable-fed strings that go through the
    builders; the pad and seal refusals cover only a missing or null class.
    A variable-fed or expression-wrapped non-member string anywhere else is a
    known gap, not a pass. So is a frame a test builds itself and passes
    straight to ``calculate_branch``: 180 such calls in 41 test files
    (measured 2026-11-24 on ``ab0c8c8f``, every ``.calculate_branch(`` under ``tests/`` outside
    ``tests/fixtures/single_exposure.py``) are checked only where the frame
    went through a pad or a seal first, so one that omits or nulls the class
    is unchecked. So is the rest of the class-column family at the
    aggregator exit: the guard reads ``exposure_class`` only, so
    ``seal_aggregator_exit`` still null-completes ``reporting_class``,
    ``reporting_class_origin`` and ``exposure_class_applied`` when a hand
    results frame omits them.

What the seal anchor does not read:
    It matches calls by name — ``seal_lenient`` (or a local import alias of
    it) and ``.conform_lenient`` — and counts a seal as guarded when a
    ``require_class_on_every_row`` call on the same frame expression appears
    EARLIER in the same function. It does not follow control flow, so a guard
    in a branch that never runs (``if False: require_class_on_every_row(lf)``)
    still counts; and a seal reached through another callable —
    ``functools.partial(seal_lenient, edge=CRM_EXIT_EDGE)(lf)``, or
    ``seal_lenient`` passed as a value — is not seen at all (both probed
    2026-11-24). Neither shape exists under ``tests/`` today; the anchor is a
    tripwire for the ordinary shape, not a proof.

References:
- ``IMPLEMENTATION_PLAN.md`` P5.69 (fallout of P1.374)
- ``.claude/LESSONS.md`` B1 (NULL and ABSENT are different paths), B3 (anchor to
  the enum, not to a hand list), C11 (a fixture is a claim)
"""

from __future__ import annotations

import ast
import functools
import inspect
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

import polars as pl
import pytest
from scripts.check_parked_registers import read_open_bullets
from scripts.tolerated_findings import (
    STALE_OWNER_GUIDANCE,
    UNOWNED_GUIDANCE,
    closed_owners,
    owner_of,
)
from tests.fixtures import contract_columns
from tests.fixtures.contract_columns import (
    pad_crm_exit_defaults,
    pad_irb_branch,
    pad_sa_branch,
    pad_slotting_branch,
)
from tests.fixtures.reporting_portfolio import build_reporting_bundle
from tests.fixtures.resolved_bundle import (
    make_aggregated_bundle,
    make_classified_bundle,
    make_crm_bundle,
)
from tests.fixtures.single_exposure import (
    calculate_single_equity_exposure,
    calculate_single_irb_exposure,
    calculate_single_sa_exposure,
    calculate_single_slotting_exposure,
)

from rwa_calc.contracts import edges as edge_contracts
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.contracts.edges import AGGREGATOR_SUMMARY_EDGES, CALC_BRANCH_EDGES, RAW_TABLE_EDGES
from rwa_calc.data.schemas import (
    CIU_HOLDINGS_SCHEMA,
    MODEL_PERMISSIONS_SCHEMA,
)
from rwa_calc.domain.enums import EquityApproach, ExposureClass, PermissionMode
from rwa_calc.engine.irb.calculator import IRBCalculator
from rwa_calc.engine.pipeline import PipelineOrchestrator
from rwa_calc.engine.sa.calculator import SACalculator

REPO_ROOT = Path(__file__).resolve().parents[2]
TESTS_ROOT = REPO_ROOT / "tests"

#: The domain. Anchored to the enum, never to a hand-written list (LESSONS B3).
EXPOSURE_CLASS_VALUES: frozenset[str] = frozenset(member.value for member in ExposureClass)

#: The class-column family a harness frame hand-writes: every edge-contract
#: column that holds an ``ExposureClass`` value — or, on rows where it has no
#: class to hold, a value listed for it in ``PRODUCTION_EXTRA_VALUES`` (only
#: ``guarantor_exposure_class``, ``""`` for a row with no eligible guarantor).
#: Nulls are not read by the scan. The siblings feed exact-key
#: consumers of their own — ``post_crm_exposure_class_guaranteed`` is read by
#: ``reporting/corep/c07.py`` and ``reporting/corep/crm_substitution.py``;
#: ``reporting_class_origin`` (the aggregator's copy of
#: ``exposure_class_applied``) by ``is_in`` / ``==`` in ``reporting/pillar3`` and
#: COREP C 02.00 / C 07.00 / C 08 / C 09 — so a scan keyed on ``exposure_class``
#: alone would leave them unguarded. Completeness is enforced against the edge
#: contracts by ``test_class_columns_cover_every_class_valued_edge_column``.
CLASS_COLUMNS: frozenset[str] = frozenset(
    {
        "exposure_class",
        "pre_crm_exposure_class",
        "post_crm_exposure_class_guaranteed",
        "guarantor_exposure_class",
        "exposure_class_applied",
        "exposure_class_post_crm",
        "exposure_class_sa",
        "exposure_class_irb",
        "re_split_target_class",
        "reporting_class",
        "reporting_class_origin",
        "reporting_class_pre_default",
    }
)

#: Edge-contract columns whose name says "class" but which do NOT hold an
#: ``ExposureClass`` value. Every other such column must be in ``CLASS_COLUMNS``
#: — ``test_class_columns_cover_every_class_valued_edge_column`` enforces it, so
#: the next sibling column cannot be silently left out of the scan.
CLASS_COLUMN_EXCLUSIONS: dict[str, str] = {
    "exposure_subclass": "an ExposureSubclass value (engine/classify/subtypes.py), not a class",
    "reporting_subclass": "exposure_subclass carried to the aggregator exit",
    "addon_by_asset_class": "an SA-CCR add-on Struct keyed by derivative asset class",
    "reclassified_to_retail": "a Boolean flag",
}

#: Strings outside ``ExposureClass`` that production writes to a class column BY
#: DESIGN, keyed by column — the column's harness domain is the enum PLUS these.
#: This is NOT everything production writes to a class column: a string a valid
#: config writes by DEFECT is declared in ``KNOWN_PRODUCTION_CLASS_DEFECTS``
#: instead, and stays outside the domain, so the harness refuses it on purpose.
#: Measured, never assumed: ``test_production_extra_values_are_what_a_real_run_writes``
#: runs the ``rich`` portfolio under each of the three ``ANCHOR_LEGS`` configs — and
#: only those — and fails if a listed value stops appearing in any leg (so the
#: allowance cannot outlive its writer) or if a class column carries a string
#: declared in neither place. Measured 2026-11-24 on the feature-branch tip
#: ``ab0c8c8f`` over every config the 39 ``RUNS`` entries of
#: ``tests/acceptance/reporting/test_supervisory_validations.py`` execute (59: 39
#: current and 20 prior-period, both regimes): the only such string on any class
#: column at the aggregator exit is ``""`` on ``guarantor_exposure_class``, in
#: every one of the 59. No ``RUNS`` config enables ``equity_pd_lgd``, so that
#: measurement cannot see the defect below; only the anchor's third leg does.
PRODUCTION_EXTRA_VALUES: dict[str, frozenset[str]] = {
    # The CRM stage writes "" for every row with no guarantor or an ineligible
    # one: ``engine/crm/guarantees.py`` (``replace_strict(..., default="")``)
    # and the no-guarantee initialiser in ``engine/crm/processor.py``; and
    # ``engine/crm/guarantees.py`` / ``guarantor_eligibility.py`` read it
    # (``!= ""``) as "no guarantor class".
    "guarantor_exposure_class": frozenset({""}),
}


@dataclass(frozen=True)
class KnownClassDefect:
    """A non-enum string a valid production config writes to class columns — by DEFECT.

    Not part of any column's harness domain: ``production_domain`` never reads
    it, so the builders, the keyword scan and the frame ratchet refuse the
    string exactly as they refuse any other, and no test can lean on the
    defect. It is declared so the anchor can see the writer in both
    directions: ``leg`` must reach the writer's population (``population``, a
    column and the value it holds on the rows the writer touches) and observe
    exactly ``values`` there, and nowhere else.

    "The strings vanished" is not evidence of a fix: dropping ``.upper()`` from
    the writer makes ``"CORPORATE"`` vanish and leaves the rows ``corporate``,
    an enum value no other check objects to, and still the wrong class. So the
    entry also states what a FIXED writer leaves (``fixed_classes``: a column
    that splits the population, and for each of its values the classes admitted
    there), and on every population row each declared column must hold either
    the defect string or an admitted class. Anything else — the case-folded
    defect, another class, a null — fails as a wrong fix, never as a fix; the
    anchor fails STALE (shrink or delete the entry) only once a declared column
    holds an admitted class on every population row.

    ``owner`` is held to the parked-register grammar of
    ``scripts/tolerated_findings.py``: an ``OWNER: P<n>.<n>`` token naming a
    bullet ``IMPLEMENTATION_PLAN.md`` holds open, so closing the owning bullet
    without removing the entry fails here, as it does for every other register
    (``.claude/LESSONS.md`` B7).
    """

    owner: str  # reason text whose first ``OWNER: P<n>.<n>`` token owns the fix
    leg: str  # the ANCHOR_LEGS config that reaches the writer
    values: dict[str, frozenset[str]]  # class column -> strings the writer leaves there
    population: tuple[str, str]  # (column, value) marking the rows the writer reaches
    fixed_classes: tuple[str, dict[str, frozenset[str]]]  # (split column, {value: classes})
    writer: str  # where production writes it, and the correct value


#: The configs the anchor runs the ``rich`` portfolio (``build_reporting_bundle``)
#: under — and the ONLY ones: a writer reached only by another config is invisible
#: to the anchor. The first two are each regime's factory default (standardised
#: permission); the third reaches the CRR Art. 155(3) PD/LGD equity branch, the
#: one known defect writer (``KNOWN_PRODUCTION_CLASS_DEFECTS``).
ANCHOR_LEGS: dict[str, Callable[[], CalculationConfig]] = {
    "crr": lambda: CalculationConfig.crr(reporting_date=date(2026, 6, 30)),
    "b31": lambda: CalculationConfig.basel_3_1(reporting_date=date(2027, 6, 30)),
    "crr-irb-equity-pd-lgd": lambda: CalculationConfig.crr(
        reporting_date=date(2026, 6, 30),
        permission_mode=PermissionMode.IRB,
        equity_pd_lgd=True,
    ),
}

#: Known production DEFECTS that write a non-enum string to a class column.
#: Refused by the harness on purpose (see ``KnownClassDefect``); held here so the
#: anchor fails both while an undeclared writer appears and once a declared one
#: is fixed. Measured 2026-11-24 (``ab0c8c8f``): the ``crr-irb-equity-pd-lgd`` leg
#: routes all three of the rich book's equity-file legs to ``pd_lgd`` (the listed
#: holding ``RP-EQ-LISTED`` and the two CIU legs, which carry ``equity`` / ``ciu``
#: under the default legs) and leaves ``"CORPORATE"`` on exactly these six class
#: columns of all three, and on no other; neither default leg, and none of the 59
#: ``RUNS`` configs, writes it. (Review of P5.69 named the first four columns; the
#: last two — ``exposure_class_post_crm``, ``reporting_class_pre_default`` — were
#: found by the same measurement over the whole ``CLASS_COLUMNS`` family.)
#: What a fixed writer leaves splits on ``equity_type``: a listed holding is an
#: equity exposure (CRR Art. 147(2)(e), 147(6)(a)), so ``equity`` only; the CIU
#: legs' class on the IRB path is not decided here (Art. 147(2) lists no CIU
#: class, and the default legs stamp ``ciu``), so the fix may leave ``equity`` or
#: ``ciu`` there. ``corporate``, in any case, is admitted on none.
KNOWN_PRODUCTION_CLASS_DEFECTS: tuple[KnownClassDefect, ...] = (
    KnownClassDefect(
        owner=(
            "OWNER: P1.480 - CRR Art. 155(3) PD/LGD equity legs leave the aggregator "
            "classed 'CORPORATE' (filed from P5.69 residual (e))"
        ),
        leg="crr-irb-equity-pd-lgd",
        values={
            column: frozenset({ExposureClass.CORPORATE.value.upper()})
            for column in (
                "exposure_class",
                "exposure_class_applied",
                "exposure_class_post_crm",
                "reporting_class",
                "reporting_class_origin",
                "reporting_class_pre_default",
            )
        },
        population=("equity_method", EquityApproach.PD_LGD.value),
        fixed_classes=(
            "equity_type",
            {
                "listed": frozenset({ExposureClass.EQUITY.value}),
                "ciu": frozenset({ExposureClass.EQUITY.value, ExposureClass.CIU.value}),
            },
        ),
        writer=(
            "engine/equity/calculator.py, CRR Art. 155(3) PD/LGD branch: it sets "
            "exposure_class to ExposureClass.CORPORATE.value.upper() to borrow the "
            "Art. 153(1) formula and restores EQUITY only for significant investments; "
            "engine/aggregator/_equity_prep.py restamps (equity, or ciu for a CIU leg) "
            "only when the column is absent, so every non-significant PD/LGD leg leaves "
            "the aggregator as 'CORPORATE', and five other class carriers hold the same "
            "string at the exit. CRR Art. 147(2)(e)/(6) put an equity exposure in "
            "the equity class whatever the approach (Art. 155(3) borrows only the "
            "Art. 153(1) formula): the fix restores ExposureClass.EQUITY.value (and "
            "decides the CIU legs' class), never lower-case 'corporate'."
        ),
    ),
)

#: Class-column keyword sites whose callee is NOT an engine-derived
#: exposure class. Keyed by (file, callee). Every entry names the namespace.
KEYWORD_ALLOWLIST: dict[tuple[str, str], str] = {
    # CIU_HOLDINGS_SCHEMA.exposure_class is USER INPUT. The CIU look-through
    # upper-cases it before joining the risk-weight table and checks it against
    # an upper-cased vocabulary (engine/equity/calculator.py), so an upper-case
    # spelling is a value production accepts, not a harness fiction.
    ("tests/fixtures/p1_139/p1_139.py", "_CiuHolding"): "CIU_HOLDINGS_SCHEMA user input",
    ("tests/fixtures/p2_15/p2_15.py", "_CiuHolding"): "CIU_HOLDINGS_SCHEMA user input",
}

#: A dict literal carrying one of these keys is a row of a user-input schema
#: whose ``exposure_class`` is not engine-derived; it is outside the scan.
INPUT_NAMESPACE_MARKERS: dict[str, dict[str, object]] = {
    "holding_reference": CIU_HOLDINGS_SCHEMA,
    "model_id": MODEL_PERMISSIONS_SCHEMA,
}

#: Dicts keyed on a class column that are NOT frames — a field-to-label map, not
#: rows. Keyed by (file, assigned name); every entry says what the dict maps.
#: (A ``.rename({...})`` argument is recognised structurally and needs no entry.)
NON_FRAME_DICTS: dict[tuple[str, str], str] = {
    # Maps each asserted conformance FIELD to the TOML table holding its rules
    # ("exposure_class" -> "class_rule"); the values are section names.
    ("tests/conformance/table.py", "_RULE_SECTION"): "field -> TOML rule-section name",
    # Maps each curated-record INPUT NAME to the reason the aggregator exit does
    # not echo it ("exposure_class" -> "derived by the classifier; ..."); the
    # values are prose, not classes.
    ("tests/oracle/drivers.py", "PIPELINE_UNECHOED_INPUTS"): (
        "input name -> why the aggregator exit does not echo it"
    ),
}

#: The harness modules that build stage-output frames for the calculators, the
#: aggregator and the reporting layer. Every lenient seal in them must run the
#: class guard on its frame first, or carry a reason in ``UNGUARDED_SEALS``.
STAGE_OUTPUT_MODULES: frozenset[str] = frozenset(
    {"tests/fixtures/resolved_bundle.py", "tests/fixtures/contract_columns.py"}
)

#: Lenient seals in ``STAGE_OUTPUT_MODULES`` that run WITHOUT the class guard,
#: keyed by (module, enclosing function). Each says why its edge needs no class;
#: the anchor still resolves each one's edge and fails if it cannot, or if the
#: edge declares ``exposure_class`` — a reason cannot excuse a classed edge.
UNGUARDED_SEALS: dict[tuple[str, str], str] = {
    ("tests/fixtures/resolved_bundle.py", "seal_hierarchy_exit"): (
        "hierarchy_exit is the classifier's INPUT: no exposure_class on the edge yet"
    ),
    ("tests/fixtures/resolved_bundle.py", "make_counterparty_lookup"): (
        "the cp_lookup_* edges are counterparty tables, with no exposure_class"
    ),
}

#: Lenient seals OUTSIDE ``STAGE_OUTPUT_MODULES`` whose edge argument cannot be
#: resolved statically, keyed by (file, edge expression as written). Each names
#: the edge it is; any other unresolvable edge fails the anchor.
UNRESOLVED_SEALS: dict[tuple[str, str], str] = {
    ("tests/contracts/test_edge_contracts.py", "contract"): (
        "the module's synthetic _contract() edge, which unit-tests the seal primitive "
        "and declares no exposure_class"
    ),
    ("tests/contracts/test_edge_contracts.py", "self._edge()"): (
        "a synthetic two-column cond_edge built by the test class, with no exposure_class"
    ),
}

#: The raw input edges: their ``exposure_class`` (CIU holdings, model
#: permissions) is user input, not engine-derived — see ``_declares_engine_class``.
_RAW_EDGE_NAMES: frozenset[str] = frozenset(edge.name for edge in RAW_TABLE_EDGES.values())
#: The class guard a lenient seal must be preceded by.
_GUARD = "require_class_on_every_row"
#: Sentinel for a ``getattr`` that found nothing on the edges module.
_UNRESOLVED = object()

#: Shrink-only residue: per file, the count of class-column frame literals that
#: are not ``ExposureClass`` values. Measured, never typed — re-measure with
#: ``frame_literal_census()``. A file may only go DOWN; lower its entry (or
#: delete it at zero) in the same change that converts its literals.
FRAME_LITERAL_BASELINE: dict[str, int] = {
    "tests/acceptance/basel31/test_p1_107_fcsm_b31_corporate_cqs3.py": 2,
    "tests/acceptance/basel31/test_p1_251_b31_firb_uk_resi_commitment_ccf.py": 2,
    "tests/acceptance/basel31/test_p1_93_art_222_4_fcsm_sft_carveout.py": 4,
    "tests/acceptance/basel31/test_scenario_b31_d7_parameter_substitution.py": 1,
    "tests/acceptance/basel31/test_scenario_b31_p1106_fcsm_inst_cqs2.py": 2,
    "tests/acceptance/crr/test_p1_104_art_239_1_fcsm_maturity_eligibility.py": 2,
    "tests/acceptance/crr/test_p1_247_art_158_7_equity_simple_el.py": 1,
    "tests/contracts/test_one_day_maturity_floor_propagation.py": 7,
    "tests/fixtures/p1_146/p1_146.py": 3,
    "tests/integration/test_pre_post_crm_reporting.py": 17,
    "tests/integration/test_ui_reconciliation.py": 1,
    "tests/unit/api/test_export.py": 3,
    "tests/unit/api/test_formatters.py": 2,
    "tests/unit/api/test_results_cache.py": 3,
    "tests/unit/crm/test_crm_error_propagation.py": 1,
    "tests/unit/crm/test_ead_for_crm.py": 1,
    "tests/unit/crm/test_guarantee_fx_mismatch.py": 1,
    "tests/unit/crm/test_multi_guarantor_split.py": 1,
    "tests/unit/crm/test_multi_level_guarantees.py": 16,
    "tests/unit/crm/test_pre_post_crm.py": 7,
    "tests/unit/crm/test_restructuring_exclusion.py": 1,
    "tests/unit/crr/test_crr_institution_standard.py": 1,
    "tests/unit/crr/test_crr_irb.py": 6,
    "tests/unit/crr/test_crr_sa.py": 14,
    "tests/unit/crr/test_irb_defaulted.py": 5,
    "tests/unit/crr/test_irb_transforms.py": 28,
    "tests/unit/engine/aggregator/test_crm_lgd_reporting_seal.py": 4,
    "tests/unit/engine/test_collapse.py": 5,
    "tests/unit/engine/test_reconciliation.py": 9,
    "tests/unit/irb/test_ccr_maturity_rung.py": 3,
    "tests/unit/irb/test_firb_sft_maturity.py": 2,
    "tests/unit/irb/test_irb_el_guarantee.py": 10,
    "tests/unit/irb/test_irb_formulas.py": 4,
    "tests/unit/irb/test_irb_guarantor_sa_rw_io_mdb.py": 1,
    "tests/unit/irb/test_irb_parameter_substitution.py": 10,
    "tests/unit/irb/test_irb_pre_post_crm.py": 9,
    "tests/unit/irb/test_p1_156_psm_guarantor_lgd_seniority.py": 2,
    "tests/unit/irb/test_p1_249_firb_fixed_maturity.py": 1,
    "tests/unit/test_aggregator.py": 22,
    "tests/unit/test_aggregator_eager_views.py": 3,
    "tests/unit/test_b31_re_junior_charges.py": 10,
    "tests/unit/test_b31_revolving_maturity.py": 15,
    "tests/unit/test_b31_sa_risk_weights.py": 37,
    "tests/unit/test_basel31_engine.py": 59,
    "tests/unit/test_branch_error_accumulation.py": 1,
    "tests/unit/test_effective_maturity.py": 9,
    "tests/unit/test_guarantor_exposure_class_rw.py": 1,
    "tests/unit/test_of_adj.py": 2,
    "tests/unit/test_output_floor_entity_type.py": 1,
    "tests/unit/test_output_floor_ig_assessment.py": 6,
    "tests/unit/test_output_floor_non_finite_guard.py": 3,
    "tests/unit/test_output_floor_skip_transitional.py": 1,
    "tests/unit/test_p1_253_crr_mdb_guarantor_institution_rw.py": 1,
    "tests/unit/test_p2_20_total_rwa_post_floor_naming.py": 6,
    "tests/unit/test_pipeline.py": 4,
    "tests/unit/test_portfolio_level_floor.py": 32,
    "tests/unit/test_sa_sl_classification.py": 2,
    "tests/unit/test_sovereign_floor_institutions.py": 4,
    "tests/unit/test_t2_cap_floor_isolation.py": 6,
    "tests/unit/ui/test_output_writer.py": 2,
    "tests/unit/ui/test_views_recon_placement.py": 3,
    "tests/unit/ui/test_views_reconciliation.py": 6,
    "tests/unit/ui/test_views_reconciliation_signoff.py": 1,
    "tests/unit/ui/views/test_comparison.py": 2,
    "tests/unit/ui/views/test_method_split.py": 10,
}


# ---------------------------------------------------------------------------
# Limb 1 — the builders refuse a non-production class
# ---------------------------------------------------------------------------


#: Frames in which at least one row has no class. ``partial-null`` is the one
#: that separates a per-row refusal from an all-null one: a guard that refuses
#: only when EVERY row is null (``null_count() == height``) passes the two
#: one-row shapes and accepts this frame, emitting ``["corporate", None]``.
_ROWS_WITHOUT_A_CLASS = [
    pytest.param({"exposure_reference": ["X"], "rwa_final": [1.0]}, id="absent"),
    pytest.param(
        {
            "exposure_reference": ["X"],
            "rwa_final": [1.0],
            "exposure_class": pl.Series([None], dtype=pl.String),
        },
        id="null",
    ),
    pytest.param(
        {
            "exposure_reference": ["X", "Y"],
            "rwa_final": [1.0, 1.0],
            "exposure_class": ["corporate", None],
        },
        id="partial-null",
    ),
]


@pytest.mark.parametrize("bad_class", ["CORPORATE", "RETAIL", "COMMERCIAL_RE", "Corporate", ""])
def test_sa_builder_refuses_a_class_production_cannot_write(bad_class: str) -> None:
    """``calculate_single_sa_exposure`` raises on a non-``ExposureClass`` class.

    Arrange: an upper-case variant, an invented class, and a mixed-case spelling.
    Act:     build a single SA exposure with it.
    Assert:  ValueError before any calculation runs.
    """
    # Arrange
    config = CalculationConfig.crr(reporting_date=date(2026, 6, 30))

    # Act / Assert
    with pytest.raises(ValueError, match="not an ExposureClass value"):
        calculate_single_sa_exposure(
            SACalculator(), ead=Decimal("1000"), exposure_class=bad_class, config=config
        )


def test_irb_builder_refuses_a_class_production_cannot_write() -> None:
    """``calculate_single_irb_exposure`` raises on a non-``ExposureClass`` class."""
    # Arrange
    config = CalculationConfig.crr(reporting_date=date(2026, 6, 30))

    # Act / Assert
    with pytest.raises(ValueError, match="not an ExposureClass value"):
        calculate_single_irb_exposure(
            IRBCalculator(),
            ead=Decimal("1000"),
            pd=Decimal("0.01"),
            exposure_class=ExposureClass.CORPORATE.value.upper(),
            config=config,
        )


def test_irb_builder_default_class_is_an_exposure_class_value() -> None:
    """A caller that omits the class must get one production can write."""
    # Arrange
    signature = inspect.signature(calculate_single_irb_exposure)

    # Act
    default = signature.parameters["exposure_class"].default

    # Assert
    assert default in EXPOSURE_CLASS_VALUES, f"IRB builder defaults to {default!r}"


def test_builder_frame_guard_admits_every_exposure_class_value() -> None:
    """Positive control: the builders' frame guard is a membership test, not a blanket refusal."""
    # Arrange
    values = sorted(EXPOSURE_CLASS_VALUES)
    frame = pl.LazyFrame({"exposure_reference": values, "exposure_class": values})

    # Act / Assert — returns without raising
    contract_columns.require_exposure_class_values(frame, "probe")


def _class_rows(classes: list[str]) -> dict[str, list[str]]:
    """One row per class. Built through a parameter so the scan does not bank the probes."""
    return {"exposure_reference": [f"X{i}" for i in range(len(classes))], "exposure_class": classes}


#: Frames the builders' frame guard must refuse: the pads' three shapes (no
#: class, a null, a null on one row of two) plus the non-member strings only a
#: membership check sees — on every row, and on one row of two.
_FRAMES_WITHOUT_A_PRODUCTION_CLASS = [
    *_ROWS_WITHOUT_A_CLASS,
    pytest.param(_class_rows([ExposureClass.CORPORATE.value.upper()]), id="upper-case"),
    pytest.param(_class_rows([""]), id="empty-string"),
    pytest.param(_class_rows([ExposureClass.CORPORATE.value, "RETAIL"]), id="partial-non-member"),
]


@pytest.mark.parametrize("rows", _FRAMES_WITHOUT_A_PRODUCTION_CLASS)
def test_builder_frame_guard_refuses_a_row_without_a_production_class(rows: dict) -> None:
    """``require_exposure_class_values`` refuses absent, null and non-member classes on any row."""
    # Arrange
    frame = pl.LazyFrame(rows)

    # Act / Assert
    with pytest.raises(ValueError, match="exposure_class"):
        contract_columns.require_exposure_class_values(frame, "probe")


class _RecordingCalculator:
    """Stands in for every calculator: records the frame a builder hands ``calculate_branch``.

    The builder-probe tests read THAT frame — not the builder's arguments and
    not its own guard — so a builder that drops or nulls the class column fails
    them even if its guard is deleted with it.
    """

    def __init__(self) -> None:
        self.frames: list[pl.DataFrame] = []

    def calculate_branch(self, exposures: pl.LazyFrame, config: CalculationConfig) -> pl.LazyFrame:
        """Record the branch input and hand back the one column a builder post-processes."""
        self.frames.append(exposures.collect())
        return exposures.with_columns(pl.lit(0.0).alias("rwa_post_factor"))

    def _determine_approach(self, config: CalculationConfig) -> str:
        """What ``calculate_single_equity_exposure`` reads after the branch call."""
        return "sa"


_PROBE_CONFIG = CalculationConfig.crr(reporting_date=date(2026, 6, 30))

#: Every builder in ``tests/fixtures`` that hands a frame to ``calculate_branch``,
#: called the way its callers call it. The IRB call omits the class, so the probe
#: reads the builder's DEFAULT; the slotting builder takes no class argument.
#: ``test_every_calculate_branch_builder_is_probed`` keeps this complete.
_BUILDER_CALLS: dict[str, Callable[[_RecordingCalculator], object]] = {
    "calculate_single_sa_exposure": lambda calc: calculate_single_sa_exposure(
        calc,
        ead=Decimal("1000"),
        exposure_class=ExposureClass.CORPORATE.value,
        config=_PROBE_CONFIG,
    ),
    "calculate_single_irb_exposure": lambda calc: calculate_single_irb_exposure(
        calc,
        ead=Decimal("1000"),
        pd=Decimal("0.01"),
        config=_PROBE_CONFIG,
    ),
    "calculate_single_slotting_exposure": lambda calc: calculate_single_slotting_exposure(
        calc,
        ead=Decimal("1000"),
        category="strong",
        config=_PROBE_CONFIG,
    ),
    "calculate_single_equity_exposure": lambda calc: calculate_single_equity_exposure(
        calc,
        ead=Decimal("1000"),
        equity_type="listed",
        config=_PROBE_CONFIG,
    ),
}

#: Builders whose calculator receives NO class in production, so the builder
#: must write none either. Each names the production input it mirrors; the
#: probe also re-checks that input still carries no class.
UNCLASSED_BUILDERS: dict[str, str] = {
    # Measured 2026-11-24 through PipelineOrchestrator on the RUNS ``rich`` (both
    # regimes) and ``equity-transitional`` portfolios: the frame reaching
    # EquityCalculator.get_equity_result_bundle has no exposure_class column; the
    # aggregator exit then carries ``equity`` or ``ciu``, stamped by
    # engine/aggregator/_equity_prep.py from equity_type. Writing ``equity`` here
    # would hand the calculator a state production never does, and the wrong
    # class for a CIU holding.
    "calculate_single_equity_exposure": "equity_exposures",
}


@pytest.mark.parametrize("builder", sorted(set(_BUILDER_CALLS) - set(UNCLASSED_BUILDERS)))
def test_builder_hands_its_calculator_a_production_class(builder: str) -> None:
    """The frame a classed builder hands ``calculate_branch`` carries an enum class on every row.

    Motivating instance 1 of P5.69: ``calculate_single_slotting_exposure``
    omitted ``exposure_class``, so every caller took the column-absent fallback
    of the infrastructure-factor class gate, and every caller stayed green. The
    probe reads the frame the calculator actually receives, so a builder that
    drops the column, nulls it or writes a non-member fails here even when its
    callers' expected values do not move.
    """
    # Arrange
    calculator = _RecordingCalculator()

    # Act
    _BUILDER_CALLS[builder](calculator)

    # Assert
    (frame,) = calculator.frames
    assert "exposure_class" in frame.columns, f"{builder} hands its calculator no exposure_class"
    classes = frame["exposure_class"].to_list()
    assert None not in classes, f"{builder} hands its calculator a null exposure_class"
    assert set(classes) <= EXPOSURE_CLASS_VALUES, (
        f"{builder} hands its calculator {classes!r}, not an ExposureClass value"
    )


@pytest.mark.parametrize("builder", sorted(UNCLASSED_BUILDERS))
def test_unclassed_builder_hands_its_calculator_no_class(builder: str) -> None:
    """A builder whose production input carries no class writes none either.

    Adequacy first: the raw table the calculator's production input comes from
    must still declare no ``exposure_class`` — if it starts to, this builder
    belongs with the classed ones and must write the class production writes.
    """
    # Arrange
    production_input = RAW_TABLE_EDGES[UNCLASSED_BUILDERS[builder]]
    assert "exposure_class" not in production_input.columns, (
        f"{production_input.name} now declares exposure_class — move {builder} out of "
        "UNCLASSED_BUILDERS and have it write the class production writes"
    )
    calculator = _RecordingCalculator()

    # Act
    _BUILDER_CALLS[builder](calculator)

    # Assert
    (frame,) = calculator.frames
    assert "exposure_class" not in frame.columns, (
        f"{builder} invents an exposure_class its production input never carries"
    )


def test_every_calculate_branch_builder_is_probed() -> None:
    """Anchor: every fixture function that calls ``calculate_branch`` is in ``_BUILDER_CALLS``.

    Read from ``tests/fixtures/**`` by AST, so a new builder — in
    ``single_exposure.py`` or in a module of its own — cannot hand a calculator
    a hand frame without a probe reading it.
    """
    # Arrange
    builders: set[tuple[str, str]] = set()
    for path in sorted((TESTS_ROOT / "fixtures").rglob("*.py")):
        rel = path.relative_to(REPO_ROOT).as_posix()
        for scope, nodes in _scopes(ast.parse(path.read_text(encoding="utf-8"))):
            if any(
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "calculate_branch"
                for node in nodes
            ):
                builders.add((rel, scope))

    # Act
    probed = {("tests/fixtures/single_exposure.py", name) for name in _BUILDER_CALLS}

    # Assert
    assert builders, "the scan found no calculate_branch call under tests/fixtures"
    assert builders == probed, (
        f"unprobed builders: {sorted(builders - probed)}; stale probes: {sorted(probed - builders)}"
    )
    assert set(UNCLASSED_BUILDERS) <= set(_BUILDER_CALLS), "an UNCLASSED_BUILDERS entry is stale"


# ---------------------------------------------------------------------------
# Limb 2 — the pads never invent a typed-null class for a row
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("rows", _ROWS_WITHOUT_A_CLASS)
def test_crm_exit_pad_refuses_a_row_without_a_class(rows: dict) -> None:
    """The crm_exit pad refuses a non-empty frame with no class, or a null on any row.

    Neither shape is one production produces, and neither fails loudly on its
    own. A typed null takes the null branch of every exact-``.value`` gate. An
    ABSENT column is no safer: at least six engine readers guard on the
    column's presence and fall back silently when it is missing (listed in the
    module docstring) — ``engine/supporting_factors.py``'s Art. 501a class limb
    becomes ``pl.lit(True)``, so an unclassed CRR infrastructure row would
    collect the 0.75 factor that a null or an ``institution`` class is denied.
    LESSONS B1: NULL and ABSENT are different code paths — both are refused
    here.
    """
    # Arrange
    frame = pl.LazyFrame(rows)

    # Act / Assert
    with pytest.raises(ValueError, match="exposure_class"):
        pad_crm_exit_defaults(frame)


def test_crm_exit_pad_accepts_an_empty_frame() -> None:
    """A zero-row frame carries no class to get wrong, so it pads as before."""
    # Arrange
    frame = pl.LazyFrame({"exposure_reference": pl.Series([], dtype=pl.String)})

    # Act
    padded = pad_crm_exit_defaults(frame).collect()

    # Assert
    assert padded.height == 0


def test_crm_exit_pad_preserves_a_supplied_class() -> None:
    """A frame that names its class keeps it verbatim."""
    # Arrange
    frame = pl.LazyFrame({"exposure_reference": ["X"], "exposure_class": ["corporate"]})

    # Act
    padded = pad_crm_exit_defaults(frame).collect()

    # Assert
    assert padded["exposure_class"].to_list() == ["corporate"]


_BRANCH_PADS = {
    "sa_branch": pad_sa_branch,
    "irb_branch": pad_irb_branch,
    "slotting_branch": pad_slotting_branch,
}


@pytest.mark.parametrize("branch", sorted(_BRANCH_PADS))
@pytest.mark.parametrize("rows", _ROWS_WITHOUT_A_CLASS)
def test_branch_pad_refuses_a_row_without_a_class(branch: str, rows: dict) -> None:
    """The branch-exit pads would seal a missing REQUIRED class to a typed null.

    ``seal_lenient`` injects every missing required column as a typed null, so
    without this refusal a hand results frame reaches the aggregator's exact
    class gates carrying a value production never writes.
    """
    # Arrange
    frame = pl.LazyFrame(rows)

    # Act / Assert
    with pytest.raises(ValueError, match="exposure_class"):
        _BRANCH_PADS[branch](frame)


@pytest.mark.parametrize("branch", sorted(_BRANCH_PADS))
def test_branch_pad_accepts_an_empty_frame(branch: str) -> None:
    """A zero-row frame carries no class to get wrong, so it seals as before."""
    # Arrange
    frame = pl.LazyFrame({"exposure_reference": pl.Series([], dtype=pl.String)})

    # Act
    sealed = _BRANCH_PADS[branch](frame).collect()

    # Assert
    assert sealed.height == 0


@pytest.mark.parametrize("branch", sorted(_BRANCH_PADS))
def test_branch_pad_accepts_a_row_with_a_class(branch: str) -> None:
    """Positive control: a row that names a production class seals unchanged."""
    # Arrange
    frame = pl.LazyFrame({"exposure_reference": ["X"], "exposure_class": ["corporate"]})

    # Act
    sealed = _BRANCH_PADS[branch](frame).collect()

    # Assert
    assert sealed["exposure_class"].to_list() == ["corporate"]


#: The stage-output seals of ``tests/fixtures/resolved_bundle.py`` — "the
#: sanctioned way tests construct" stage outputs, and the oracle drivers' route
#: to a classified bundle. Each lenient-seals an edge on which ``exposure_class``
#: is required and injected, so each would otherwise turn an unsupplied class
#: into a typed null exactly as the pads did. Keyed by the seal function, reached
#: through the bundle builder it sits behind, because that is what callers use.
_BUNDLE_SEALS = {
    "seal_classifier_exit": lambda frame: make_classified_bundle(all_exposures=frame).all_exposures,
    "seal_crm_exit": lambda frame: make_crm_bundle(exposures=frame).exposures,
    "seal_aggregator_exit": lambda frame: make_aggregated_bundle(results=frame).results,
}


@pytest.mark.parametrize("seal", sorted(_BUNDLE_SEALS))
@pytest.mark.parametrize("rows", _ROWS_WITHOUT_A_CLASS)
def test_bundle_seal_refuses_a_row_without_a_class(seal: str, rows: dict) -> None:
    """The stage-output bundle seals refuse a non-empty frame with no class or a null one.

    ``make_crm_bundle(exposures=<frame without a class>)`` is motivating
    instance 2 — a typed-null class injected by a lenient seal — reached through
    a sibling helper instead of a pad.
    """
    # Arrange
    frame = pl.LazyFrame(rows)

    # Act / Assert
    with pytest.raises(ValueError, match="exposure_class"):
        _BUNDLE_SEALS[seal](frame)


@pytest.mark.parametrize("seal", sorted(_BUNDLE_SEALS))
def test_bundle_seal_accepts_an_empty_frame(seal: str) -> None:
    """A zero-row frame carries no class to get wrong, so it seals as before."""
    # Arrange
    frame = pl.LazyFrame({"exposure_reference": pl.Series([], dtype=pl.String)})

    # Act
    sealed = _BUNDLE_SEALS[seal](frame).collect()

    # Assert
    assert sealed.height == 0


@pytest.mark.parametrize("seal", sorted(_BUNDLE_SEALS))
def test_bundle_seal_accepts_a_row_with_a_class(seal: str) -> None:
    """Positive control: a row that names a production class seals unchanged."""
    # Arrange
    frame = pl.LazyFrame({"exposure_reference": ["X"], "exposure_class": ["corporate"]})

    # Act
    sealed = _BUNDLE_SEALS[seal](frame).collect()

    # Assert
    assert sealed["exposure_class"].to_list() == ["corporate"]


@dataclass(frozen=True)
class LenientSeal:
    """One ``seal_lenient(frame, edge)`` / ``edge.conform_lenient(frame)`` call in a test module.

    ``guarded`` is True when the enclosing function called
    ``require_class_on_every_row`` on the same frame expression earlier.
    ``edges`` is every edge contract the edge argument can be, resolved
    statically, or ``None`` when it cannot be.
    """

    path: str
    scope: str  # enclosing function (``Class.method``), or ``<module>``
    line: int
    edge_source: str  # the edge argument as written
    guarded: bool
    edges: tuple[edge_contracts.EdgeContract, ...] | None


def test_every_lenient_seal_in_the_stage_output_helpers_is_guarded() -> None:
    """Anchor: every lenient seal in the two stage-output modules runs the class guard.

    Function-level, over ``STAGE_OUTPUT_MODULES``: each function (or module
    body) that calls ``seal_lenient`` / ``EdgeContract.conform_lenient`` must
    call ``require_class_on_every_row`` on the SAME frame earlier in that
    function, or be named in ``UNGUARDED_SEALS`` with a reason. Keyed by
    function, not by edge or by a ``seal_*`` name, so an inline seal in any
    helper — a ``make_*`` builder, a private function, a second seal on an
    edge another function already guards — is read too. An exempt seal's edge
    is resolved statically; one that cannot be resolved FAILS rather than
    being skipped, and so does one that declares ``exposure_class``. The
    reading is syntactic: see "What the seal anchor does not read" in the
    module docstring for the two shapes it cannot see.
    """
    # Arrange
    seals = [seal for seal in harness_seal_census() if seal.path in STAGE_OUTPUT_MODULES]

    # Act
    offenders = [message for seal in seals if (message := _seal_offence(seal))]

    # Assert
    assert {seal.path for seal in seals} == set(STAGE_OUTPUT_MODULES), (
        "the census read no lenient seal in a stage-output module — it is not reading them"
    )
    assert not offenders, "unguarded lenient seals:\n  " + "\n  ".join(offenders)


def test_no_other_harness_module_lenient_seals_an_engine_classed_edge() -> None:
    """Anchor: outside the two stage-output modules, no lenient seal null-completes a class.

    Every other ``seal_lenient`` / ``conform_lenient`` call under ``tests/``
    must be guarded, or seal an edge that resolves statically and declares no
    engine-derived ``exposure_class`` (the SFT tables, and the raw input
    tables, whose ``exposure_class`` is user input that the production loader
    seals the same lenient way). An unresolvable edge fails unless
    ``UNRESOLVED_SEALS`` names it. So a fixture written anywhere else that
    lenient-seals ``crm_exit`` cannot reintroduce the typed-null class either.
    """
    # Arrange
    seals = [seal for seal in harness_seal_census() if seal.path not in STAGE_OUTPUT_MODULES]

    # Act
    offenders = [message for seal in seals if (message := _seal_offence(seal))]

    # Assert
    assert seals, "the census read no lenient seal outside the stage-output modules"
    assert not offenders, "lenient seals of an engine-classed edge:\n  " + "\n  ".join(offenders)


def test_seal_exemptions_are_live() -> None:
    """Every ``UNGUARDED_SEALS`` / ``UNRESOLVED_SEALS`` entry still matches a seal."""
    # Arrange
    unguarded = [seal for seal in harness_seal_census() if not seal.guarded]

    # Act
    stale = sorted(set(UNGUARDED_SEALS) - {(seal.path, seal.scope) for seal in unguarded})
    stale += sorted(
        set(UNRESOLVED_SEALS)
        - {(seal.path, seal.edge_source) for seal in unguarded if seal.edges is None}
    )

    # Assert
    assert not stale, f"stale seal exemptions: {stale}"


_SEAL_PROBE_IMPORTS = (
    "from rwa_calc.contracts.edges import (\n"
    "    CALC_BRANCH_EDGES, CRM_EXIT_EDGE, HIERARCHY_EXIT_EDGE, RAW_TABLE_EDGES,\n"
    "    SFT_TABLE_EDGES, seal_lenient,\n"
    ")\n"
    "from tests.fixtures.contract_columns import require_class_on_every_row\n"
)
_RESOLVED_BUNDLE = "tests/fixtures/resolved_bundle.py"
_ELSEWHERE = "tests/fixtures/some_new_builder.py"


@pytest.mark.parametrize(
    ("path", "body", "offences"),
    [
        # The reviewer's probe: an inline seal in a ``make_*`` helper, the
        # shape of ``make_counterparty_lookup``, on a classed edge.
        pytest.param(
            _RESOLVED_BUNDLE,
            "def make_crm_results_frame(lf):\n"
            "    sealed, _m, _l = seal_lenient(lf, CRM_EXIT_EDGE)\n"
            "    return sealed\n",
            1,
            id="inline-seal-in-a-builder",
        ),
        pytest.param(
            _RESOLVED_BUNDLE,
            "def f(lf):\n"
            "    seal_lenient(lf, CRM_EXIT_EDGE)\n"
            "    require_class_on_every_row(lf, 'crm_exit')\n",
            1,
            id="guard-after-the-seal",
        ),
        pytest.param(
            _RESOLVED_BUNDLE,
            "def f(lf, other):\n"
            "    require_class_on_every_row(other, 'crm_exit')\n"
            "    seal_lenient(lf, CRM_EXIT_EDGE)\n",
            1,
            id="guard-on-another-frame",
        ),
        pytest.param(
            _RESOLVED_BUNDLE,
            "SEALED = seal_lenient(LF, CRM_EXIT_EDGE)\n",
            1,
            id="module-level-seal",
        ),
        pytest.param(
            "tests/fixtures/contract_columns.py",
            "def pad(lf, branch):\n    seal_lenient(lf, CALC_BRANCH_EDGES[branch])\n",
            1,
            id="unguarded-registry-seal",
        ),
        pytest.param(
            _RESOLVED_BUNDLE,
            "def seal_hierarchy_exit(lf, edge):\n    seal_lenient(lf, edge)\n",
            1,
            id="exempt-but-unresolvable",
        ),
        pytest.param(
            _RESOLVED_BUNDLE,
            "def seal_hierarchy_exit(lf):\n    seal_lenient(lf, CRM_EXIT_EDGE)\n",
            1,
            id="exempt-but-classed",
        ),
        pytest.param(
            _ELSEWHERE,
            "def build(lf):\n    edge = CRM_EXIT_EDGE\n    seal_lenient(lf, edge)\n",
            1,
            id="elsewhere-classed-via-a-local",
        ),
        pytest.param(
            _ELSEWHERE,
            "def build(lf):\n    CRM_EXIT_EDGE.conform_lenient(lf)\n",
            1,
            id="elsewhere-conform-lenient",
        ),
        pytest.param(
            _ELSEWHERE,
            "def build(lf, edge):\n    seal_lenient(lf, edge)\n",
            1,
            id="elsewhere-unresolvable",
        ),
        pytest.param(
            _ELSEWHERE,
            "from rwa_calc.contracts.edges import seal_lenient as conform\n"
            "def build(lf):\n    conform(lf, CRM_EXIT_EDGE)\n",
            1,
            id="elsewhere-aliased-seal",
        ),
        pytest.param(
            _ELSEWHERE,
            "from rwa_calc.contracts import edges as contracts\n"
            "def build(lf):\n    contracts.seal_lenient(lf, contracts.CRM_EXIT_EDGE)\n",
            1,
            id="elsewhere-module-attribute-seal",
        ),
        # Positive controls: the shapes the anchors must let through.
        pytest.param(
            _RESOLVED_BUNDLE,
            "def f(lf):\n"
            "    require_class_on_every_row(lf, 'crm_exit')\n"
            "    seal_lenient(lf, CRM_EXIT_EDGE)\n",
            0,
            id="guarded",
        ),
        pytest.param(
            _RESOLVED_BUNDLE,
            "def seal_hierarchy_exit(lf):\n    seal_lenient(lf, HIERARCHY_EXIT_EDGE)\n",
            0,
            id="exempt-and-unclassed",
        ),
        pytest.param(
            _ELSEWHERE,
            "def build(lf):\n    seal_lenient(lf, SFT_TABLE_EDGES['sft_trades'])\n",
            0,
            id="elsewhere-sft-table",
        ),
        pytest.param(
            _ELSEWHERE,
            "def build(lf, name):\n    seal_lenient(lf, RAW_TABLE_EDGES[name])\n",
            0,
            id="elsewhere-raw-input-table",
        ),
    ],
)
def test_seal_anchor_probes(path: str, body: str, offences: int) -> None:
    """The seal anchors flag each unguarded shape and pass each sanctioned one.

    Negative controls for the two anchors above: without them a census that
    read nothing, or resolved nothing, would pass the real modules vacuously.
    """
    # Arrange
    tree = ast.parse(_SEAL_PROBE_IMPORTS + body)

    # Act
    found = [message for seal in _lenient_seals(path, tree) if (message := _seal_offence(seal))]

    # Assert
    assert len(found) == offences, found


_CLASSED_SUMMARY_FIELDS = sorted(
    field for field, edge in AGGREGATOR_SUMMARY_EDGES.items() if "exposure_class" in edge.columns
)


#: The ``exposure_class`` column of a hand summary frame: ``null`` is one null
#: row, ``partial-null`` two rows of which the second is null (an all-null-only
#: guard accepts it), ``classed`` two production classes (the positive control).
_SUMMARY_CLASSES: dict[str, list[str | None]] = {
    "null": [None],
    "partial-null": [ExposureClass.CORPORATE.value, None],
    "classed": [ExposureClass.CORPORATE.value, ExposureClass.RETAIL_OTHER.value],
}


@pytest.mark.parametrize("shape", ["null", "partial-null"])
@pytest.mark.parametrize("field", _CLASSED_SUMMARY_FIELDS)
def test_summary_seal_refuses_a_null_class(field: str, shape: str) -> None:
    """A hand summary / floor frame may not carry a null class on any row either.

    ``make_aggregated_bundle``'s summary seal already refuses an ABSENT required
    column (its ``missing`` assertion); a supplied NULL class passed it. The
    aggregator never emits one: the summaries take their class from
    ``reporting_class`` / ``exposure_class``, non-null on every row of every
    config the 39 ``RUNS`` entries execute (59 with the prior-period ones, both
    regimes; re-measured 2026-11-24 on ``ab0c8c8f``).
    """
    # Arrange
    summary = _summary_frame(field, _SUMMARY_CLASSES[shape])
    results = pl.LazyFrame({"exposure_reference": ["X"], "exposure_class": ["corporate"]})

    # Act / Assert
    with pytest.raises(ValueError, match="exposure_class"):
        make_aggregated_bundle(results=results, **{field: summary})


@pytest.mark.parametrize("field", _CLASSED_SUMMARY_FIELDS)
def test_summary_seal_accepts_a_classed_frame(field: str) -> None:
    """Positive control: the same frame shape with a class on every row seals.

    Without it the refusal above could be a blanket one; with it the two
    differ only in the null class.
    """
    # Arrange
    summary = _summary_frame(field, _SUMMARY_CLASSES["classed"])
    results = pl.LazyFrame({"exposure_reference": ["X"], "exposure_class": ["corporate"]})

    # Act
    bundle = make_aggregated_bundle(results=results, **{field: summary})

    # Assert
    sealed = getattr(bundle, field).collect()
    assert sealed["exposure_class"].to_list() == _SUMMARY_CLASSES["classed"]


# ---------------------------------------------------------------------------
# Limb 3 — the literal scan
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ClassLiteral:
    """One ``exposure_class``-family string literal found in a test module."""

    path: str
    line: int
    kind: str  # "keyword" | "default" | "frame"
    owner: str  # callee name (keyword), function name (default), column (frame)
    value: str
    column: str  # the class column the literal is bound to

    @property
    def in_production_domain(self) -> bool:
        """True when ``value`` is in ``column``'s harness domain (never a known defect)."""
        return self.value in production_domain(self.column)


def test_input_namespace_markers_identify_only_input_schemas() -> None:
    """Each marker belongs to an input schema that carries ``exposure_class``.

    Anchors the frame-scan exclusion to the schemas rather than to a hand list.
    A marker alone is NOT enough to exempt a frame — ``model_id`` is also a
    column of every calculator-branch edge (``CALC_BRANCH_EDGES``), beside
    ``exposure_class`` — so the exclusion additionally requires every key of
    the dict to be a column of the marker's schema. This test pins that the
    subset rule is what separates the two: no branch edge fits inside an input
    schema.
    """
    # Act / Assert
    for marker, schema in INPUT_NAMESPACE_MARKERS.items():
        assert "exposure_class" in schema, f"{marker}'s schema carries no exposure_class"
        assert marker in schema, f"{marker} is not a column of its input schema"
        for name, edge in CALC_BRANCH_EDGES.items():
            assert not set(edge.columns) <= set(schema), f"{name} fits inside {marker}'s schema"


@pytest.mark.parametrize("marker", sorted(INPUT_NAMESPACE_MARKERS))
def test_a_marker_on_an_exposure_frame_does_not_exempt_it(marker: str) -> None:
    """Negative control: an exposure frame that carries a marker key is still scanned.

    ``model_id`` sits on every ``CALC_BRANCH_EDGES`` edge and on the output
    schema, so a hand-built IRB results frame carries it as a matter of course.
    Were the marker alone to exempt a dict, that frame would skip the scan.
    """
    # Arrange
    snippet = (
        "frame = {\n"
        '    "exposure_reference": ["X"],\n'
        f'    "{marker}": ["M1"],\n'
        '    "exposure_class": ["CORPORATE"],\n'
        '    "approach_applied": ["foundation_irb"],\n'
        '    "rwa_final": [1.0],\n'
        "}\n"
    )

    # Act
    found = _scan_module("snippet.py", ast.parse(snippet))

    # Assert
    assert [(lit.kind, lit.value) for lit in found] == [("frame", "CORPORATE")]


@pytest.mark.parametrize("marker", sorted(INPUT_NAMESPACE_MARKERS))
def test_an_input_schema_row_is_outside_the_scan(marker: str) -> None:
    """Positive control: a dict made only of an input schema's columns is exempt."""
    # Arrange
    columns = sorted(INPUT_NAMESPACE_MARKERS[marker])
    entries = "".join(
        f'    "{col}": ["CORPORATE"],\n' if col == "exposure_class" else f'    "{col}": [None],\n'
        for col in columns
    )
    snippet = "row = {\n" + entries + "}\n"

    # Act
    found = _scan_module("snippet.py", ast.parse(snippet))

    # Assert
    assert found == []


@pytest.mark.parametrize("column", sorted(CLASS_COLUMNS))
def test_every_class_column_keyword_is_scanned(column: str) -> None:
    """Negative control: the keyword limb reads the whole class-column family.

    The default and frame limbs already key on ``CLASS_COLUMNS``; a keyword
    limb keyed on ``exposure_class`` alone would leave
    ``build(post_crm_exposure_class_guaranteed="CORPORATE")`` unread.
    """
    # Arrange
    snippet = f'build({column}="CORPORATE")\n'

    # Act
    found = _scan_module("snippet.py", ast.parse(snippet))

    # Assert
    assert [(lit.kind, lit.owner, lit.value) for lit in found] == [
        ("keyword", "build", "CORPORATE")
    ]


def test_class_columns_cover_every_class_valued_edge_column() -> None:
    """Anchor: the scanned family is every edge column named for a class (LESSONS B3).

    Read from every ``EdgeContract`` that ``rwa_calc.contracts.edges`` declares,
    so the family cannot drift from the contracts the harness frames are sealed
    against: each column whose name contains ``class`` is either scanned
    (``CLASS_COLUMNS``) or excluded with a reason (``CLASS_COLUMN_EXCLUSIONS``),
    and neither list names a column no edge carries.
    """
    # Arrange
    edge_class_columns = {
        column for edge in _all_edge_contracts() for column in edge.columns if "class" in column
    }

    # Act
    unaccounted = edge_class_columns - CLASS_COLUMNS - set(CLASS_COLUMN_EXCLUSIONS)
    stale = (CLASS_COLUMNS | set(CLASS_COLUMN_EXCLUSIONS)) - edge_class_columns

    # Assert
    assert not unaccounted, (
        f"edge columns named for a class but neither scanned nor excluded: {sorted(unaccounted)}"
    )
    assert not stale, f"class-column entries no edge contract carries: {sorted(stale)}"
    assert not CLASS_COLUMNS & set(CLASS_COLUMN_EXCLUSIONS), "a column is both scanned and excluded"


def test_a_column_rename_mapping_is_not_a_frame() -> None:
    """A ``.rename({...})`` argument maps column NAMES; its values are not classes.

    Counting ``{"exposure_class": "Asset_Class"}`` as a frame literal would bank
    a string that can never be converted, because it is a column name.
    """
    # Arrange
    snippet = 'df.rename({"exposure_class": "Asset_Class", "ead_final": "EAD"})\n'

    # Act
    found = _scan_module("snippet.py", ast.parse(snippet))

    # Assert
    assert found == []


def test_non_frame_dict_allowlist_entries_are_live() -> None:
    """Every ``NON_FRAME_DICTS`` entry names an assignment that still exists."""
    # Arrange
    stale = []
    for path, name in NON_FRAME_DICTS:
        tree = ast.parse((REPO_ROOT / path).read_text(encoding="utf-8"))

        # Act
        if not any(isinstance(node.value, ast.Dict) for node in _assignments_to(tree, name)):
            stale.append((path, name))

    # Assert
    assert not stale, f"stale NON_FRAME_DICTS entries: {stale}"


def test_exposure_class_keywords_and_defaults_are_exposure_class_values() -> None:
    """Every class-column keyword and parameter default is in its column's harness domain.

    Zero tolerance: this is the population every single-exposure builder and
    local frame helper is fed through. The domain is per column — the enum,
    plus the column's measured ``PRODUCTION_EXTRA_VALUES`` (so
    ``guarantor_exposure_class=""``, the unguaranteed-row state, is admitted
    and ``exposure_class=""`` is not), and never a
    ``KNOWN_PRODUCTION_CLASS_DEFECTS`` string (so ``exposure_class="CORPORATE"``
    is refused although the CRR PD/LGD equity branch writes it). A test that
    must exercise the engine's case tolerance computes the variant
    (``member.value.upper()``) instead of writing it as a literal, so it states
    its intent in code.
    """
    # Act
    offenders = [
        lit
        for lit in class_literal_census()
        if lit.kind in {"keyword", "default"}
        and not lit.in_production_domain
        and (lit.path, lit.owner) not in KEYWORD_ALLOWLIST
    ]

    # Assert
    assert not offenders, (
        f"{len(offenders)} class-column literal(s) outside that column's harness domain "
        "— use ExposureClass.<X>.value (lower case):\n  "
        + "\n  ".join(
            f"{o.path}:{o.line} {o.owner}(... {o.column}={o.value!r})" for o in offenders[:40]
        )
    )


def test_the_guarantor_blank_is_admitted_on_its_own_column_only() -> None:
    """``""`` is a production value of ``guarantor_exposure_class`` and of no other column.

    Negative and positive control in one: the same literal is admitted in a
    keyword and a frame on the column production writes it to by design, and
    refused on ``exposure_class``, which no anchor leg and none of the 59 ``RUNS``
    configs leaves blank (measured 2026-11-24).
    """
    # Arrange
    snippet = (
        'build(guarantor_exposure_class="", exposure_class="")\n'
        'frame = {"guarantor_exposure_class": [""], "exposure_class": [""]}\n'
    )

    # Act
    found = _scan_module("snippet.py", ast.parse(snippet))

    # Assert
    assert len(found) == 4, f"the scan read {len(found)} of the snippet's 4 literals"
    outside = sorted((lit.kind, lit.column) for lit in found if not lit.in_production_domain)
    assert outside == [("frame", "exposure_class"), ("keyword", "exposure_class")]


@pytest.mark.parametrize("leg", sorted(ANCHOR_LEGS))
def test_production_extra_values_are_what_a_real_run_writes(leg: str) -> None:
    """Anchor: the declared non-enum strings are what a real run leaves on the class columns.

    Runs the ``rich`` portfolio (``tests/fixtures/reporting_portfolio.py``)
    through ``PipelineOrchestrator`` under one ``ANCHOR_LEGS`` config and reads
    every class column at the aggregator exit. Three legs — CRR and Basel 3.1
    factory defaults, and CRR IRB with ``equity_pd_lgd=True`` — and NO others: a
    writer only another config reaches is invisible here (the 59-config ``RUNS``
    measurement is recorded on ``PRODUCTION_EXTRA_VALUES``, and is not re-run).

    Two-way, for both declarations:

    - each ``PRODUCTION_EXTRA_VALUES`` string (by design) must appear in every
      leg, and each ``KNOWN_PRODUCTION_CLASS_DEFECTS`` string (by defect) in its
      own leg — an allowance that outlives its writer is slack, and a defect
      that stops appearing has been fixed, so its entry must go;
    - no class column may carry a non-enum string declared in neither place,
      so a new writer is declared — as design or as defect — before it can pass.

    A defect leg first asserts it reaches the writer's population, so a fixture
    that stops reaching it fails as inadequate rather than as "fixed" (LESSONS
    C11). It then holds every population row, on every declared column, to the
    defect string or a class the entry's ``fixed_classes`` admits for that row,
    and the defect string to the population alone — so a change that makes the
    string vanish by writing some other wrong class (``corporate``, from
    dropping the writer's ``.upper()``) fails as a wrong fix, and only a writer
    that leaves an admitted class reads as "fixed". One portfolio, so the
    undeclared half is a tripwire, not a proof. Outside a defect's population,
    nulls are not compared: the scan does not read them.
    """
    # Arrange
    bundle = build_reporting_bundle()
    defects = [defect for defect in KNOWN_PRODUCTION_CLASS_DEFECTS if defect.leg == leg]
    expected_defects: dict[str, frozenset[str]] = {}
    for defect in defects:
        for column, values in defect.values.items():
            expected_defects[column] = expected_defects.get(column, frozenset()) | values

    # Act
    results = PipelineOrchestrator().run_with_data(bundle, ANCHOR_LEGS[leg]()).results.collect()

    # Assert
    for defect in defects:
        column, value = defect.population
        assert column in results.columns and results[column].eq(value).any(), (
            f"{leg}: no row has {column} == {value!r} — the leg no longer reaches the "
            f"writer of {defect.owner!r}, so it cannot tell a fix from a lost "
            "population. Restore the population before reading the declaration."
        )
    undeclared_splits = [
        finding for defect in defects for finding in _undeclared_splits(defect, results)
    ]
    assert not undeclared_splits, (
        f"{leg}: a KNOWN_PRODUCTION_CLASS_DEFECTS population row has no declared fixed class "
        "— add its split value to the entry's fixed_classes, with the class a fixed writer "
        f"must leave there: {undeclared_splits}"
    )
    wrong_fixes = [finding for defect in defects for finding in _wrong_fixes(defect, results)]
    assert not wrong_fixes, (
        f"{leg}: a KNOWN_PRODUCTION_CLASS_DEFECTS population row holds a class that is "
        "neither the declared defect string nor one a fixed writer may leave — this is NOT "
        "a fix; do not delete the entry. The entry's writer text says which class is right "
        f"(split value, column, value held, classes admitted): {wrong_fixes}"
    )
    strays = [finding for defect in defects for finding in _strays(defect, results)]
    assert not strays, (
        f"{leg}: a KNOWN_PRODUCTION_CLASS_DEFECTS string is written outside its declared "
        f"population — a second writer, declare or fix it (column, value): {strays}"
    )
    observed = {
        column: frozenset(
            value
            for value in results[column].unique().to_list()
            if value is not None and value not in EXPOSURE_CLASS_VALUES
        )
        for column in sorted(CLASS_COLUMNS)
        if column in results.columns
    }
    declared_columns = set(PRODUCTION_EXTRA_VALUES) | set(expected_defects)
    assert declared_columns <= set(observed), (
        f"{leg}: a declared column is absent from the aggregator exit — the run cannot "
        f"measure it: {sorted(declared_columns - set(observed))}"
    )
    stale_extras = {
        column: sorted(values - observed[column])
        for column, values in PRODUCTION_EXTRA_VALUES.items()
        if values - observed[column]
    }
    stale_defects = {
        column: sorted(values - observed[column])
        for column, values in expected_defects.items()
        if values - observed[column]
    }
    undeclared = {
        column: sorted(
            values
            - PRODUCTION_EXTRA_VALUES.get(column, frozenset())
            - expected_defects.get(column, frozenset())
        )
        for column, values in observed.items()
        if values
        - PRODUCTION_EXTRA_VALUES.get(column, frozenset())
        - expected_defects.get(column, frozenset())
    }
    assert not stale_extras, (
        f"{leg}: PRODUCTION_EXTRA_VALUES no longer written — remove them: {stale_extras}"
    )
    assert not stale_defects, (
        f"{leg}: KNOWN_PRODUCTION_CLASS_DEFECTS no longer written, and every population row "
        "holds a class its fixed_classes admits — the defect is fixed on these columns "
        f"({[defect.owner for defect in defects]}); remove them from the entry's values, "
        f"and delete the entry once none remain: {stale_defects}"
    )
    assert not undeclared, (
        f"{leg}: class-column strings production writes but nobody declared — add them to "
        f"PRODUCTION_EXTRA_VALUES (by design) or KNOWN_PRODUCTION_CLASS_DEFECTS (by defect, "
        f"with an OWNER): {undeclared}"
    )


def test_known_production_defects_stay_outside_the_harness_domain() -> None:
    """A defect string is refused by the harness, and every declaration names a real leg.

    The point of ``KNOWN_PRODUCTION_CLASS_DEFECTS`` is to see the writer without
    admitting its output: if a defect string were also in its column's domain
    (via ``PRODUCTION_EXTRA_VALUES`` or the enum), the builders, the keyword scan
    and the frame ratchet would accept a test that leans on the defect. Also
    checks each entry names an ``ANCHOR_LEGS`` leg and a ``CLASS_COLUMNS``
    column, so no declaration is unreachable, and that every class its
    ``fixed_classes`` admits is an ``ExposureClass`` value other than the
    case-fold of a defect string — the obvious wrong fix (drop the writer's
    ``.upper()``) must stay a wrong fix, not be admitted as the right one.
    """
    # Act
    admitted = [
        (defect.owner, column, value)
        for defect in KNOWN_PRODUCTION_CLASS_DEFECTS
        for column, values in defect.values.items()
        for value in values
        if value in production_domain(column)
    ]
    unreachable = [
        defect.owner
        for defect in KNOWN_PRODUCTION_CLASS_DEFECTS
        if defect.leg not in ANCHOR_LEGS
        or not set(defect.values) <= CLASS_COLUMNS
        or not all(defect.values.values())
        or not defect.fixed_classes[1]
    ]
    bad_fixes = [
        (defect.owner, split, sorted(classes))
        for defect in KNOWN_PRODUCTION_CLASS_DEFECTS
        for split, classes in defect.fixed_classes[1].items()
        if not classes
        or not classes <= EXPOSURE_CLASS_VALUES
        or classes & {value.lower() for values in defect.values.values() for value in values}
    ]

    # Assert
    assert not admitted, f"defect strings admitted to the harness domain: {admitted}"
    assert not unreachable, f"declarations with no leg, class column or fixed class: {unreachable}"
    assert not bad_fixes, (
        "fixed_classes must name ExposureClass values, never the case-fold of the defect "
        f"string: {bad_fixes}"
    )


def test_every_known_production_defect_names_an_open_owner() -> None:
    """Each ``KNOWN_PRODUCTION_CLASS_DEFECTS`` entry is owned by a bullet the plan holds open.

    The register parks a production defect on a capital-path class column, so it
    is held to the same rule as every other parked register
    (``scripts/check_parked_registers.py`` requirement (d),
    ``tests/contracts/test_register_owners.py``): ``owner`` carries an
    ``OWNER: P<n>.<n>`` token (``scripts/tolerated_findings.py::owner_of``), and
    every such token names a bullet ``IMPLEMENTATION_PLAN.md`` holds open. A
    prose owner ("P5.69 residual (e)") is not one, and a bullet closed or pruned
    while its entry stays owns nothing (``.claude/LESSONS.md`` B7) — so the change
    that closes the owning bullet turns this red until it removes the entry.
    """
    # Arrange
    open_ids = read_open_bullets()

    # Act
    unowned = [
        defect.owner for defect in KNOWN_PRODUCTION_CLASS_DEFECTS if owner_of(defect.owner) is None
    ]
    not_open = {
        defect.owner: closed_owners(defect.owner, open_ids)
        for defect in KNOWN_PRODUCTION_CLASS_DEFECTS
        if closed_owners(defect.owner, open_ids)
    }

    # Assert
    assert not unowned, f"{UNOWNED_GUIDANCE}\nunowned: {unowned}"
    assert not not_open, f"{STALE_OWNER_GUIDANCE}\nnot open: {not_open}"


def test_keyword_allowlist_entries_are_live() -> None:
    """An allowlist entry that matches nothing is slack — prune it."""
    # Arrange
    seen = {(lit.path, lit.owner) for lit in class_literal_census() if lit.kind == "keyword"}

    # Act
    stale = sorted(set(KEYWORD_ALLOWLIST) - seen)

    # Assert
    assert not stale, f"stale KEYWORD_ALLOWLIST entries: {stale}"


def test_exposure_class_frame_literals_may_only_shrink() -> None:
    """The non-production frame literals per file match the banked residue.

    Two-way, like every count ratchet here: a file that GROWS is a new harness
    fiction and fails; a file that SHRINKS fails until its entry is lowered, so
    the slack a fix frees can never absorb a later addition.
    """
    # Arrange
    census = frame_literal_census()

    # Act
    grown = {
        path: (FRAME_LITERAL_BASELINE.get(path, 0), count)
        for path, count in census.items()
        if count > FRAME_LITERAL_BASELINE.get(path, 0)
    }
    shrunk = {
        path: (banked, census.get(path, 0))
        for path, banked in FRAME_LITERAL_BASELINE.items()
        if census.get(path, 0) < banked
    }

    # Assert
    assert not grown, (
        "class-column frame literals outside that column's harness domain were "
        "ADDED (banked -> now). Use ExposureClass.<X>.value:\n  "
        + "\n  ".join(f"{p}: {b} -> {n}" for p, (b, n) in sorted(grown.items()))
    )
    assert not shrunk, (
        "exposure_class frame literals were converted — bank the lower count in "
        "FRAME_LITERAL_BASELINE (delete the entry at zero):\n  "
        + "\n  ".join(f"{p}: {b} -> {n}" for p, (b, n) in sorted(shrunk.items()))
    )


def frame_literal_census() -> dict[str, int]:
    """Count, per test file, the class-column frame literals outside their column's domain."""
    counts: dict[str, int] = {}
    for lit in class_literal_census():
        if lit.kind == "frame" and not lit.in_production_domain:
            counts[lit.path] = counts.get(lit.path, 0) + 1
    return counts


def production_domain(column: str) -> frozenset[str]:
    """One class column's harness domain: the enum plus what production writes there by design.

    Never a ``KNOWN_PRODUCTION_CLASS_DEFECTS`` string — production writes those
    too, but by defect, and the harness refuses them on purpose.
    """
    return EXPOSURE_CLASS_VALUES | PRODUCTION_EXTRA_VALUES.get(column, frozenset())


@functools.cache
def class_literal_census() -> tuple[ClassLiteral, ...]:
    """The class-column string literals under ``tests/`` in three harness sites.

    Three sites are read: ``<class column>=<str>`` keyword arguments (``kind ==
    "keyword"``), class-column parameter defaults (``"default"``), and
    dict entries keyed on a ``CLASS_COLUMNS`` name whose value is a string or a
    list / tuple / ``pl.Series`` / ``[...] * n`` of strings (``"frame"``).
    A value bound through a name (a parametrize list, a helper argument) is
    NOT read — see the module docstring. Comparisons are deliberately NOT read
    either: an upper-case comparison is how a test legitimately queries the SA
    risk-weight join table.
    """
    found: list[ClassLiteral] = []
    for path in sorted(TESTS_ROOT.rglob("*.py")):
        rel = path.relative_to(REPO_ROOT).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        found.extend(_scan_module(rel, tree))
    return tuple(found)


@functools.cache
def harness_seal_census() -> tuple[LenientSeal, ...]:
    """Every lenient-seal call under ``tests/`` — see ``LenientSeal``."""
    found: list[LenientSeal] = []
    for path in sorted(TESTS_ROOT.rglob("*.py")):
        rel = path.relative_to(REPO_ROOT).as_posix()
        found.extend(_lenient_seals(rel, ast.parse(path.read_text(encoding="utf-8"))))
    return tuple(found)


def _population(defect: KnownClassDefect, results: pl.DataFrame) -> pl.DataFrame:
    """The aggregator-exit rows ``defect``'s writer reaches (its ``population`` marker)."""
    column, value = defect.population
    return results.filter(pl.col(column) == value)


def _undeclared_splits(defect: KnownClassDefect, results: pl.DataFrame) -> list[object]:
    """Population split values ``defect.fixed_classes`` states no fixed class for."""
    split_column, admitted_by_split = defect.fixed_classes
    if split_column not in results.columns:
        return [f"split column {split_column!r} absent from the aggregator exit"]
    splits = _population(defect, results)[split_column].unique().to_list()
    return sorted((split for split in splits if split not in admitted_by_split), key=repr)


def _wrong_fixes(
    defect: KnownClassDefect, results: pl.DataFrame
) -> list[tuple[object, str, str | None, list[str]]]:
    """Population cells that hold neither the defect string nor a class a fix may leave.

    ``(split value, column, value held, classes admitted)`` for every declared
    column of every population row whose value is outside ``defect.values`` for
    that column plus ``fixed_classes`` for the row's split value. A null is
    such a value: a writer that nulls the class has not fixed it.
    """
    split_column, admitted_by_split = defect.fixed_classes
    rows = _population(defect, results).select(split_column, *defect.values)
    findings: set[tuple[object, str, str | None, tuple[str, ...]]] = set()
    for row in rows.iter_rows(named=True):
        admitted = admitted_by_split.get(row[split_column], frozenset())
        for column, defect_values in defect.values.items():
            if row[column] not in defect_values | admitted:
                findings.add((row[split_column], column, row[column], tuple(sorted(admitted))))
    return [
        (split, column, held, list(admitted))
        for split, column, held, admitted in sorted(findings, key=repr)
    ]


def _strays(defect: KnownClassDefect, results: pl.DataFrame) -> list[tuple[str, str]]:
    """``(column, value)`` for each defect string written on a row outside the population."""
    column, value = defect.population
    outside = results.filter(pl.col(column).ne_missing(value))
    return sorted(
        (declared, held)
        for declared, values in defect.values.items()
        for held in outside[declared].unique().to_list()
        if held in values
    )


def _seal_offence(seal: LenientSeal) -> str | None:
    """Why ``seal`` may null-complete ``exposure_class``, or None when it cannot.

    A guarded seal is clean wherever it is. In a stage-output module an
    unguarded seal must be exempt by name AND resolve to edges with no class;
    elsewhere it must resolve (or be named in ``UNRESOLVED_SEALS``) to edges
    with no engine-derived class.
    """
    if seal.guarded:
        return None
    where = f"{seal.path}:{seal.line} {seal.scope}() seals {seal.edge_source}"
    if seal.path in STAGE_OUTPUT_MODULES and (seal.path, seal.scope) not in UNGUARDED_SEALS:
        return f"{where} without require_class_on_every_row on the same frame first"
    if seal.edges is None:
        if (
            seal.path in STAGE_OUTPUT_MODULES
            or (seal.path, seal.edge_source) not in UNRESOLVED_SEALS
        ):
            return f"{where}, an edge that cannot be resolved statically"
        return None
    classed = sorted(edge.name for edge in seal.edges if _declares_engine_class(edge))
    return f"{where}, which declares exposure_class on {classed}" if classed else None


def _declares_engine_class(edge: edge_contracts.EdgeContract) -> bool:
    """True when ``edge`` declares an ``exposure_class`` the engine writes.

    The raw input tables are the exception: ``raw_ciu_holdings`` and
    ``raw_model_permissions`` carry a USER-INPUT ``exposure_class`` that the
    production loader seals with the same ``seal_lenient``, so a null there is
    a state production produces for a file without the column.
    """
    return "exposure_class" in edge.columns and edge.name not in _RAW_EDGE_NAMES


def _lenient_seals(rel: str, tree: ast.Module) -> list[LenientSeal]:
    """The lenient-seal calls of one parsed module, scope by scope."""
    imports, module_aliases = _edge_module_names(tree)
    seal_names = {"seal_lenient"} | {
        local for local, name in imports.items() if name == "seal_lenient"
    }
    scopes = _scopes(tree)
    module_bindings = _bindings(next(nodes for name, nodes in scopes if name == "<module>"))
    found: list[LenientSeal] = []
    for scope, nodes in scopes:
        layers = (_bindings(nodes), module_bindings)
        calls = [node for node in nodes if isinstance(node, ast.Call)]
        guards = [call for call in calls if _callee_name(call.func) == _GUARD and call.args]
        for call in calls:
            target = _seal_target(call, seal_names)
            if target is None:
                continue
            frame, edge = target
            guarded = any(
                ast.dump(guard.args[0]) == ast.dump(frame)
                and (guard.lineno, guard.col_offset) < (call.lineno, call.col_offset)
                for guard in guards
            )
            values = _possible_values(edge, layers, imports, module_aliases, frozenset())
            edges = (
                tuple(values)
                if values and all(isinstance(v, edge_contracts.EdgeContract) for v in values)
                else None
            )
            found.append(LenientSeal(rel, scope, call.lineno, ast.unparse(edge), guarded, edges))
    return found


def _seal_target(call: ast.Call, seal_names: set[str]) -> tuple[ast.expr, ast.expr] | None:
    """``(frame, edge)`` of a lenient-seal call, or None for any other call.

    ``seal_names`` holds ``seal_lenient`` and every local alias the module
    imports it under. A missing argument becomes ``None`` as a constant, which
    resolves to no edge, so a seal call with its arguments in an unexpected
    shape fails rather than being skipped. A seal reached through another
    callable (``functools.partial``) is not a call this matches.
    """
    keywords = {kw.arg: kw.value for kw in call.keywords if kw.arg}
    missing = ast.Constant(value=None)
    if _callee_name(call.func) in seal_names:
        frame = call.args[0] if call.args else keywords.get("lf", missing)
        edge = call.args[1] if len(call.args) > 1 else keywords.get("edge", missing)
        return frame, edge
    if isinstance(call.func, ast.Attribute) and call.func.attr == "conform_lenient":
        return (call.args[0] if call.args else keywords.get("lf", missing)), call.func.value
    return None


def _scopes(tree: ast.Module) -> list[tuple[str, list[ast.AST]]]:
    """Each function (``Class.method`` qualified), class body and the module body, and its nodes.

    A scope's own nodes exclude the bodies of the functions and classes nested
    in it, which are scopes of their own — so a call is attributed to the
    innermost function that makes it.
    """
    found: list[tuple[str, list[ast.AST]]] = []

    def visit(node: ast.AST, qualname: str) -> None:
        own: list[ast.AST] = []
        stack = list(ast.iter_child_nodes(node))
        while stack:
            child = stack.pop()
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                prefix = "" if qualname == "<module>" else f"{qualname}."
                visit(child, prefix + child.name)
                continue
            own.append(child)
            stack.extend(ast.iter_child_nodes(child))
        found.append((qualname, own))

    visit(tree, "<module>")
    return found


def _bindings(nodes: list[ast.AST]) -> dict[str, list[ast.expr | None]]:
    """Each name a scope binds, and the expression bound (None when opaque).

    A plain assignment binds its value. A parameter, a loop or ``with``
    target, an unpacking or an augmented assignment binds something the
    resolver cannot follow, so the name becomes unresolvable.
    """
    bound: dict[str, list[ast.expr | None]] = {}

    def opaque(target: ast.AST) -> None:
        for name in ast.walk(target):
            if isinstance(name, ast.Name):
                bound.setdefault(name.id, []).append(None)

    for node in nodes:
        if isinstance(node, ast.Assign | ast.AnnAssign | ast.NamedExpr) and node.value is not None:
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    bound.setdefault(target.id, []).append(node.value)
                else:
                    opaque(target)
        elif isinstance(node, ast.AugAssign | ast.For | ast.AsyncFor | ast.comprehension):
            opaque(node.target)
        elif isinstance(node, ast.withitem) and node.optional_vars is not None:
            opaque(node.optional_vars)
        elif isinstance(node, ast.arg):
            bound.setdefault(node.arg, []).append(None)
    return bound


def _possible_values(
    expr: ast.expr,
    layers: tuple[dict[str, list[ast.expr | None]], ...],
    imports: dict[str, str],
    module_aliases: set[str],
    seen: frozenset[tuple[int, str]],
) -> list[object] | None:
    """Every object ``expr`` can evaluate to, read statically, or None if unknown.

    Follows a name through the scope's own bindings, then the module's, then
    the names imported from ``rwa_calc.contracts.edges``; an attribute of that
    module; and a subscript of one of its edge registries — a constant key
    picks one edge, any other key stands for every edge in the registry.
    """
    if isinstance(expr, ast.Name):
        for depth, layer in enumerate(layers):
            if expr.id not in layer:
                continue
            key = (id(layer), expr.id)
            if key in seen:
                return None
            outer = layers[depth:]
            values = [
                None
                if bound is None
                else _possible_values(bound, outer, imports, module_aliases, seen | {key})
                for bound in layer[expr.id]
            ]
            if any(value is None for value in values):
                return None
            return [item for value in values if value is not None for item in value]
        if expr.id in imports:
            value = getattr(edge_contracts, imports[expr.id], _UNRESOLVED)
            return None if value is _UNRESOLVED else [value]
        return [edge_contracts] if expr.id in module_aliases else None
    if isinstance(expr, ast.Attribute):
        bases = _possible_values(expr.value, layers, imports, module_aliases, seen)
        if not bases or any(base is not edge_contracts for base in bases):
            return None
        value = getattr(edge_contracts, expr.attr, _UNRESOLVED)
        return None if value is _UNRESOLVED else [value]
    if isinstance(expr, ast.Subscript):
        registries = _possible_values(expr.value, layers, imports, module_aliases, seen)
        if not registries or not all(isinstance(registry, dict) for registry in registries):
            return None
        dicts = [registry for registry in registries if isinstance(registry, dict)]
        if isinstance(expr.slice, ast.Constant):
            key = expr.slice.value
            return [registry[key] for registry in dicts] if all(key in r for r in dicts) else None
        return [value for registry in dicts for value in registry.values()]
    return None


def _edge_module_names(tree: ast.Module) -> tuple[dict[str, str], set[str]]:
    """Local names bound to ``rwa_calc.contracts.edges`` members, and to the module itself."""
    imports: dict[str, str] = {}
    module_aliases: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "rwa_calc.contracts.edges":
            imports |= {alias.asname or alias.name: alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module == "rwa_calc.contracts":
            module_aliases |= {
                alias.asname or alias.name for alias in node.names if alias.name == "edges"
            }
        elif isinstance(node, ast.Import):
            module_aliases |= {
                alias.asname
                for alias in node.names
                if alias.name == "rwa_calc.contracts.edges" and alias.asname
            }
    return imports, module_aliases


def _scan_module(rel: str, tree: ast.AST) -> list[ClassLiteral]:
    """Collect the class literals of one parsed module."""
    not_frames = _non_frame_dict_ids(rel, tree)
    found: list[ClassLiteral] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            found.extend(_keyword_literals(rel, node))
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            found.extend(_default_literals(rel, node))
        elif isinstance(node, ast.Dict) and id(node) not in not_frames:
            found.extend(_frame_literals(rel, node))
    return found


def _non_frame_dict_ids(rel: str, tree: ast.AST) -> set[int]:
    """The dict literals of a module that map column names rather than hold rows.

    Two shapes: the mapping argument of a ``.rename(...)`` call (Polars' column
    rename, whose values are column NAMES), and the assignments that
    ``NON_FRAME_DICTS`` names for this file.
    """
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _callee_name(node.func) == "rename":
            args = [*node.args, *(kw.value for kw in node.keywords if kw.arg == "mapping")]
            ids |= {id(arg) for arg in args if isinstance(arg, ast.Dict)}
    for path, name in NON_FRAME_DICTS:
        if path == rel:
            ids |= {
                id(node.value)
                for node in _assignments_to(tree, name)
                if isinstance(node.value, ast.Dict)
            }
    return ids


def _keyword_literals(rel: str, node: ast.Call) -> list[ClassLiteral]:
    """``f(..., <class column>="X")`` — one literal per matching keyword."""
    callee = _callee_name(node.func)
    return [
        ClassLiteral(rel, kw.value.lineno, "keyword", callee, kw.value.value, kw.arg)
        for kw in node.keywords
        if kw.arg in CLASS_COLUMNS
        and isinstance(kw.value, ast.Constant)
        and isinstance(kw.value.value, str)
    ]


def _default_literals(rel: str, node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ClassLiteral]:
    """``def f(exposure_class: str = "X")`` — positional and keyword-only defaults."""
    args = node.args
    positional = args.posonlyargs + args.args
    pairs = list(
        zip(positional[len(positional) - len(args.defaults) :], args.defaults, strict=True)
    )
    pairs += [(a, d) for a, d in zip(args.kwonlyargs, args.kw_defaults, strict=True) if d]
    return [
        ClassLiteral(rel, default.lineno, "default", node.name, default.value, arg.arg)
        for arg, default in pairs
        if arg.arg in CLASS_COLUMNS
        and isinstance(default, ast.Constant)
        and isinstance(default.value, str)
    ]


def _frame_literals(rel: str, node: ast.Dict) -> list[ClassLiteral]:
    """``{"exposure_class": [...]}`` entries, outside the user-input namespaces."""
    if _is_input_schema_row(node):
        return []
    found: list[ClassLiteral] = []
    for key, value in zip(node.keys, node.values, strict=True):
        if isinstance(key, ast.Constant) and key.value in CLASS_COLUMNS:
            found.extend(
                ClassLiteral(rel, const.lineno, "frame", key.value, const.value, key.value)
                for const in _string_constants(value)
            )
    return found


def _is_input_schema_row(node: ast.Dict) -> bool:
    """True when the dict is a row of a user-input schema that carries the column.

    A marker key is necessary but not sufficient: ``model_id`` is also a column
    of every calculator-branch edge, so an exposure frame can carry it. The dict
    is exempt only when it has the marker AND every key is a string constant
    naming a column of that marker's schema — a ``**spread`` or any exposure
    column keeps it in the scan.
    """
    keys = [k.value if isinstance(k, ast.Constant) else None for k in node.keys]
    if not all(isinstance(k, str) for k in keys):
        return False
    return any(
        marker in keys and set(keys) <= set(schema)
        for marker, schema in INPUT_NAMESPACE_MARKERS.items()
    )


def _string_constants(node: ast.expr) -> list[ast.Constant]:
    """The string constants a frame-column value spells out literally."""
    if isinstance(node, ast.Constant):
        return [node] if isinstance(node.value, str) else []
    if isinstance(node, ast.List | ast.Tuple):
        return [c for elt in node.elts for c in _string_constants(elt)]
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult):
        return _string_constants(node.left) + _string_constants(node.right)
    if isinstance(node, ast.Call) and _callee_name(node.func) == "Series":
        # ``pl.Series("name", [...])`` — a bare-string argument is the series
        # NAME, never a value; only the sequence arguments carry values.
        return [
            c
            for arg in node.args
            if not isinstance(arg, ast.Constant)
            for c in _string_constants(arg)
        ]
    return []


def _assignments_to(tree: ast.AST, name: str) -> list[ast.Assign | ast.AnnAssign]:
    """Every ``name = ...`` / ``name: T = ...`` assignment in a module."""
    found: list[ast.Assign | ast.AnnAssign] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        else:
            continue
        if any(isinstance(t, ast.Name) and t.id == name for t in targets):
            found.append(node)
    return found


def _callee_name(func: ast.expr) -> str:
    """The bare name of a call target: ``f`` for ``f(...)`` and ``a.b.f(...)``."""
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return "<expr>"


def _all_edge_contracts() -> list[edge_contracts.EdgeContract]:
    """Every ``EdgeContract`` the edges module declares, bare or in a registry dict."""
    found: dict[str, edge_contracts.EdgeContract] = {}
    for value in vars(edge_contracts).values():
        members = value.values() if isinstance(value, dict) else [value]
        for member in members:
            if isinstance(member, edge_contracts.EdgeContract):
                found[member.name] = member
    return list(found.values())


def _summary_frame(field: str, classes: list[str | None]) -> pl.LazyFrame:
    """A hand frame for one classed summary edge: its required columns, typed.

    ``exposure_class`` takes ``classes``; every other required column is a
    typed null of the same height, which the seal accepts (it refuses only an
    absent column or a lossy cast).
    """
    edge = AGGREGATOR_SUMMARY_EDGES[field]
    return pl.LazyFrame(
        {
            name: pl.Series(
                classes if name == "exposure_class" else [None] * len(classes),
                dtype=column.dtype,
            )
            for name, column in edge.columns.items()
            if column.required
        }
    )
