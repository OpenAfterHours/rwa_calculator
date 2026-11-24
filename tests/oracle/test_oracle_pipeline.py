"""
Oracle suite, end to end -- the same hand-derived figures through PipelineOrchestrator.

Why this module exists (P5.43): every case in ``test_oracle.py`` drives one
calculator branch directly (or, for phase O3, the CRM stage and then the SA
branch) on a row the driver builds itself. That isolates the regulatory
arithmetic, which is the point of that module -- and it means a green branch
oracle cannot show that a fix reaches production. P1.316 is the case on record:
wiring the Table 5 ladder into the SA branch turned the three institution
oracles green and discharged their strict xfails while a real portfolio still
took the 100% unrated fallback on every leg, because the branch driver sets
``cp_sovereign_cqs`` itself and nothing upstream had been checked to.

This module takes a curated handful of the SAME records, translates each into
the raw tables a firm would load (``drivers.run_pipeline``), runs them through
every stage, and holds the pipeline to the same expected values at the same
tolerance. Nothing here derives a value: every figure still comes from
``expected_values.json``, and that file, the derivations and their hash lock are
untouched by this module.

Pipeline position tested:
    raw tables -> PipelineOrchestrator (loader seal, hierarchy, classifier, CRM,
    calculators, aggregator, output floor) -> legs of the record's exposure

Two assertions per record, on purpose:
1. ``test_pipeline_reaches_the_records_fact_pattern`` -- adequacy
   (``.claude/LESSONS.md`` C11). The pipeline re-derives the exposure class and
   the approach, so a mistranslated record silently tests a different fact
   pattern. This test asserts the class, the approach, each stated input listed
   in ``drivers.PIPELINE_ECHOES`` (exactly) or ``drivers.PIPELINE_YEAR_ECHOES``
   (to within one day), the pre-floor RWA carrier, that no ERROR-severity
   finding appeared that the translation did not cause on purpose, and that no
   leg's treatment rests on a branch the engine itself calls unjustified -- no
   ``UNKNOWN_FALLBACK`` in any ``BRANCH_REASON_VOCABULARIES`` column and no BR001
   (WARNING severity, so the ERROR check cannot see it), with no record exempt.
   A figure reached through an indeterminate predicate can agree with the
   record by coincidence: ORC-052 did, at 40% on the Art. 121(6) unknown-
   domesticity limb, until the translation loaded its obligor's
   ``local_currency`` and the run reached the record's own case, a US bank lent
   USD (``domestic_currency``, 40%; with its local currency loaded as EUR the
   loan is foreign and the floor binds at 100%). The inputs
   the exit does NOT carry as stated -- ``ead``, residual maturity, the null
   ``lgd``, ``crm_method``, collateral, guarantee and guarantor items,
   ``is_exchange_traded`` -- are listed with the reason in
   ``drivers.PIPELINE_UNECHOED_INPUTS``. Most are held only by test 2's numbers;
   the two residual-maturity inputs and ``is_exchange_traded`` are INERT on
   every curated record that states them (varied, and no compared figure
   moved), so nothing here holds them and they are not coverage.
   ``test_every_stated_input_is_echoed_or_named_unechoed`` keeps the three maps
   a partition of what the curated records state.
2. ``test_pipeline_matches_oracle`` -- agreement, through the comparisons
   ``test_oracle.py`` uses, with RWA read before the output floor (the record is
   the exposure's own RWEA; the floor is an entity-level add-on). Its only
   precondition is class and approach -- NOT the echoed inputs -- so an input
   that fails to arrive shows up here as a wrong number as well as in test 1.

Observed red before it was relied on (C12), each mutant applied to a scratch
copy of ``src`` and run against this module and ``test_oracle.py``:

- The classifier's ``sovereign_cqs -> cp_sovereign_cqs`` alias replaced by a
  typed null -- the P1.316 symptom. ``test_oracle.py`` stayed green on the whole
  Table 5 family. Here ORC-105 / 020 / 109 failed both tests (RW 1.0 against
  0.20 / 0.50 / 1.50); ORC-106 failed the fact-pattern test only (its Table 5
  weight, 100%, IS the unrated fallback, so the number cannot see the loss); and
  ORC-021, whose sovereign is unrated, stayed green in both.
- An Art. 120 Table 3 style lift: the classifier copying ``cp_sovereign_cqs``
  into ``cqs`` for an unrated institution, the pattern the SA central-bank path
  uses for unrated central banks. Every Table 5 step but CQS 3 gives the same
  weight under Table 3, so before ORC-106 and the ``cqs`` echo were added this
  module stayed fully green while the pipeline took 50% for 100% on every
  unrated institution whose sovereign is CQS 3. Now ORC-105 / 020 / 109 / 106
  fail the fact-pattern test (``cqs`` carried as 1 / 2 / 6 / 3, stated null) and
  ORC-106 fails the numeric test as well (RW 0.5 against 1.0).
- The CRM stage's F-IRB senior unsecured LGD halved, in
  ``crm/collateral.py::_apply_collateral_unified`` (the path the pipeline takes
  even with no collateral; ``apply_firb_supervisory_lgd_no_collateral`` is not
  on it) -- invisible to the branch suite, whose IRB driver supplies
  ``lgd_post_crm`` itself. ORC-003 (CRR) and
  ORC-091 (Basel 3.1) each failed ``test_pipeline_matches_oracle`` on
  ``lgd_applied`` (0.225 / 0.20 against 0.45 / 0.40) while their fact-pattern
  tests stayed green: the numeric comparison fails on its own, in each regime
  separately.
- The classifier's ``local_currency -> cp_local_currency`` alias replaced by a
  typed null. ORC-052 failed the fact-pattern test alone, on
  ``sa_risk_weight_branch_reason`` reading ``UNKNOWN_FALLBACK``: its number
  stayed at 40%, which is why the branch-justification check exists, and
  ``test_oracle.py`` stayed green (its driver leaves ``cp_local_currency`` null).
  The same check, run on the translation before it loaded ``local_currency``,
  failed ORC-052 alone the same way.
- The Art. 121(6) domesticity test inverted (``currency == cp_local_currency``
  read as foreign). ORC-052 failed ``test_pipeline_matches_oracle`` alone (RW
  1.0 against 0.40, reason ``floor_bound``) and ``test_oracle.py`` stayed green:
  no institution-class record in ``expected_values.json`` states
  ``local_currency``, so among the oracles this limb is reached only here.
- The parking route, run for real on a scratch copy: under the LGD mutant with
  ``ORC-003@pipeline`` and ``ORC-091@pipeline`` parked, the module went green
  (both numbers tests XFAIL, both fact-pattern tests passing). Before the
  numbers-only marking, the same parking failed as XPASS(strict) on ORC-003's
  fact-pattern test. Under the null-sovereign mutant with ORC-105 / 020 / 109
  parked, their numbers tests XFAILed and their fact-pattern tests stayed red.
  Without a mutant, a parked ORC-003 fails as XPASS(strict) on its numbers test.

Disagreements: a record that disagrees only here is a finding, never a reason to
edit the record or to drop it from ``PIPELINE_ORACLES``. A fact-pattern failure
is never parked: it is a translation slip (a driver bug) or a stage losing or
inventing an input (an engine defect, as P1.316 was), and either is fixed. A
numbers-only disagreement -- fact-pattern test green, unechoed inputs checked
against the leg values (the failure message walks that order) -- may be parked
in ``test_oracle.KNOWN_DISAGREEMENTS`` under the key ``"<id>@pipeline"``, with an
``OWNER: P<n>.<n>`` token: that is the register
``scripts/check_parked_registers.py`` already ratchets shrink-only, so the
parking is reviewed. The key strict-xfails that record's
``test_pipeline_matches_oracle`` and nothing else -- not its fact-pattern test,
which keeps running unmarked, so a parking cannot hide a lost input; and not
``test_oracle.py``, which reads bare ids only.
``test_a_pipeline_parking_marks_the_numbers_test_only`` pins that on a fake
parking, because the register holds none.

References:
- tests/oracle/README.md ("What this suite is NOT")
- tests/unit/crr/test_p1_316_art_121_1_table_5_unrated_institution.py
"""

from __future__ import annotations

import functools
import math
from typing import TYPE_CHECKING, Any

import pytest

from rwa_calc.contracts.errors import ERROR_UNKNOWN_BRANCH_FALLBACK
from rwa_calc.domain.branch_reasons import BRANCH_REASON_VOCABULARIES, UNKNOWN_FALLBACK
from tests.oracle import drivers
from tests.oracle import test_oracle as branch_suite

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

#: The curated records. Each takes a different route through the pipeline, and
#: together they hold every approach ``drivers.run_pipeline`` translates in both
#: regimes (asserted below), so no translation rule ships unexercised.
PIPELINE_ORACLES: tuple[str, ...] = (
    # CRR Art. 121 Table 5 (20 / 50 / 100 / 100 / 100 / 150%), the P1.316
    # escape. Each step is here to tell the ladder apart from one specific wrong
    # variant (LESSONS B5):
    # - sovereign CQS 1 / 2 / 6 -> 20% / 50% / 150% separate the ladder from the
    #   100% unrated fallback the broken pipeline returned (CQS 6 is the capital
    #   shortfall side of it);
    # - sovereign CQS 3 -> 100% separates Table 5 from the rated-institution
    #   Art. 120 Table 3 (20 / 50 / 50 / 100 / 100 / 150%) -- the ONLY step where
    #   the two differ, so a pipeline that lent an unrated institution its
    #   sovereign's CQS as its own rating passes every other step;
    # - the unrated sovereign (Art. 121(2)) -> 100% is the SURVIVOR. The engine
    #   implements Art. 121(2) as the ladder's own null fallback
    #   (``sovereign_derived_rw_expr``), so a run that LOSES the sovereign CQS
    #   leaves this record green -- its staying green beside 105 / 020 / 109 is
    #   what shows such a mutant isolates the ladder -- and a ladder made
    #   unconditional would not move it either. What it does catch is a run that
    #   INVENTS a sovereign step (a ``fill_null`` of ``cp_sovereign_cqs``): the
    #   null must arrive as null (``PIPELINE_ECHOES``), and an invented step 1,
    #   2 or 6 also moves its number off 100%.
    "ORC-105",
    "ORC-020",
    "ORC-106",
    "ORC-109",
    "ORC-021",
    # Basel 3.1 replaces the ladder with SCRA grades read off ``scra_grade``.
    "ORC-052",
    # F-IRB corporate, one per regime: supervisory LGD, the CRR-only 1.06 scaling
    # factor, PD and M through the IRB formula.
    "ORC-003",
    "ORC-091",
    # Phase O3: the comprehensive method over two pledged items, the simple
    # method, and the guarantee substitution (two legs, totalled on
    # source_exposure_reference).
    "ORC-243",
    "ORC-244",
    "ORC-259",
    # Slotting, one per regime: the specialised-lending table plus a model id.
    "ORC-112",
    "ORC-116",
    # Equity, one per regime: the equity table, not the loan table.
    "ORC-036",
    "ORC-080",
)

#: Suffix of a ``test_oracle.KNOWN_DISAGREEMENTS`` key that parks a record's
#: pipeline parametrisation only (see the module docstring).
PIPELINE_DISAGREEMENT_SUFFIX = "@pipeline"

#: ``record["framework"]`` -> the carrier ``run_pipeline`` must read RWEA from.
#: The output floor runs only under Basel 3.1, which is where ``rwa_pre_floor``
#: is emitted; under CRR ``rwa_final`` is the pre-floor amount. Asserting the
#: pair stops a run that lost ``rwa_pre_floor`` from being compared post-floor.
_EXPECTED_RWA_CARRIER = {"CRR": "rwa_final", "BASEL_3_1": "rwa_pre_floor"}

#: ``test_oracle._COMPARISONS`` with RWA read off the pre-floor carrier.
_PIPELINE_COMPARISONS: tuple[tuple[str, tuple[str, ...]], ...] = tuple(
    (key, ("rwa_pre_floor",) if key == "rwa" else candidates)
    for key, candidates in branch_suite._COMPARISONS
)

_RECORDS: dict[str, dict[str, Any]] = {
    record["exposure_id"]: record for record in branch_suite.ORACLES
}


# =============================================================================
# The curated set
# =============================================================================


def test_every_pipeline_oracle_is_a_locked_record() -> None:
    """Each curated id names one hash-locked record in expected_values.json."""
    unknown = [oid for oid in PIPELINE_ORACLES if oid not in _RECORDS]
    duplicates = sorted({oid for oid in PIPELINE_ORACLES if PIPELINE_ORACLES.count(oid) > 1})

    assert not unknown, f"PIPELINE_ORACLES names no record for {unknown}"
    assert not duplicates, f"PIPELINE_ORACLES lists {duplicates} more than once"


def test_pipeline_oracles_hold_every_translated_approach_in_both_regimes() -> None:
    """No translation rule in ``drivers.run_pipeline`` ships without a record on it."""
    covered = {(_RECORDS[oid]["framework"], _RECORDS[oid]["approach"]) for oid in PIPELINE_ORACLES}
    required = {
        (framework, approach)
        for framework in _EXPECTED_RWA_CARRIER
        for approach in drivers.PIPELINE_APPROACHES
    }

    assert required <= covered, f"no curated record for {sorted(required - covered)}"


def test_every_stated_input_is_echoed_or_named_unechoed() -> None:
    """The adequacy test's coverage is a declared partition, not a claim.

    Each input a curated record states is either echoed at the aggregator exit
    (``PIPELINE_ECHOES`` exactly, ``PIPELINE_YEAR_ECHOES`` within a day) or named
    in ``PIPELINE_UNECHOED_INPUTS`` with the reason the exit does not carry it
    and what, if anything, holds it instead -- never both, never neither. A new
    curated record that states a new input fails here until someone decides
    which.
    """
    echoed = set(drivers.PIPELINE_ECHOES)
    year_echoed = set(drivers.PIPELINE_YEAR_ECHOES)
    unechoed = set(drivers.PIPELINE_UNECHOED_INPUTS)
    stated = {key for oid in PIPELINE_ORACLES for key in _RECORDS[oid]["inputs"]}

    overlaps = sorted((echoed & year_echoed) | (echoed & unechoed) | (year_echoed & unechoed))
    unclassified = sorted(stated - echoed - year_echoed - unechoed)

    assert not overlaps, f"inputs classified twice: {overlaps}"
    assert not unclassified, (
        f"curated records state {unclassified}, which no map in drivers classifies: "
        f"echo each at the exit or name it in PIPELINE_UNECHOED_INPUTS with the reason"
    )


def test_no_pipeline_oracle_is_a_known_branch_disagreement() -> None:
    """A record the branch suite already parks as wrong guards nothing here.

    And every pipeline-only parking names a curated record, so an entry cannot
    outlive the record it excuses.
    """
    parked = set(branch_suite.KNOWN_DISAGREEMENTS)
    pipeline_keys = {key for key in parked if key.endswith(PIPELINE_DISAGREEMENT_SUFFIX)}
    stale = sorted(
        key
        for key in pipeline_keys
        if key.removesuffix(PIPELINE_DISAGREEMENT_SUFFIX) not in PIPELINE_ORACLES
    )

    assert not parked & set(PIPELINE_ORACLES), (
        f"{sorted(parked & set(PIPELINE_ORACLES))} are parked as branch disagreements"
    )
    assert not stale, f"pipeline parkings for records not in PIPELINE_ORACLES: {stale}"


def test_pipeline_translation_refuses_an_input_it_cannot_carry() -> None:
    """An input with no translation raises rather than running as its default.

    The B1 failure mode on the pipeline side: an input that translates to
    nothing leaves the pipeline reading the default and testing a different
    fact pattern. A jurisdiction whose local currency the driver does not know
    is refused too, rather than loading the obligor with none -- which would
    hand a non-UK/EU institution to the Art. 121(6) unknown-domesticity limb.
    Every refusal runs before any stage does.
    """
    record = _RECORDS["ORC-105"]
    with_stray_input = {**record, "inputs": {**record["inputs"], "is_payroll_loan": True}}
    untranslated_approach = {**record, "approach": "AIRB"}
    unknown_jurisdiction = {**record, "inputs": {**record["inputs"], "country_code": "JP"}}

    with pytest.raises(ValueError, match="is_payroll_loan"):
        drivers.run_pipeline(with_stray_input)
    with pytest.raises(ValueError, match="no pipeline translation for approach"):
        drivers.run_pipeline(untranslated_approach)
    with pytest.raises(ValueError, match="no local currency known for jurisdiction 'JP'"):
        drivers.run_pipeline(unknown_jurisdiction)


# =============================================================================
# Per record
# =============================================================================


def _fact_pattern_params() -> list[Any]:
    """One UNMARKED param per curated record: the fact-pattern test is never parked.

    A fact-pattern failure is a translation slip or an engine defect that loses
    (or invents) an input on the way through the stages -- P1.316 was the second
    kind -- and both are fixed, not parked. So this deliberately does not read
    ``KNOWN_DISAGREEMENTS``: a record parked as ``"<id>@pipeline"`` still runs
    this test unmarked, which is what stops a parking from hiding a fact-pattern
    failure. (Marking it as well would break the one parking the triage allows:
    that record's fact-pattern test passes, and a strict xfail turns the pass red.)
    """
    return [pytest.param(_RECORDS[oid], id=oid) for oid in PIPELINE_ORACLES]


def _numbers_params(register: Mapping[str, str]) -> list[Any]:
    """One param per curated record, strict-xfailed where ``register`` parks it.

    Strict, so a parked record that starts agreeing fails as XPASS and its entry
    has to be deleted -- the shrink-only ratchet on the register sees that.
    """
    out = []
    for oid in PIPELINE_ORACLES:
        reason = register.get(f"{oid}{PIPELINE_DISAGREEMENT_SUFFIX}")
        marks = [pytest.mark.xfail(strict=True, reason=reason)] if reason else []
        out.append(pytest.param(_RECORDS[oid], id=oid, marks=marks))
    return out


#: The two per-record parametrisations, built once and asserted by identity in
#: ``test_a_pipeline_parking_marks_the_numbers_test_only``.
_FACT_PATTERN_PARAMS = _fact_pattern_params()
_NUMBERS_PARAMS = _numbers_params(branch_suite.KNOWN_DISAGREEMENTS)


def test_a_pipeline_parking_marks_the_numbers_test_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """``"<id>@pipeline"`` strict-xfails the numbers test and never the fact-pattern test.

    The register holds no such parking today, so the route is exercised on a
    fake one: the record it names gets exactly one strict xfail on its numbers
    param, no other record gets a mark, and no fact-pattern param gets a mark
    even while the real register parks it. The last two asserts pin the wiring
    -- each per-record test is parametrised by the list its role calls for -- so
    swapping the lists, or marking both, fails here rather than the first time
    someone parks a real disagreement. Independent of what the real register
    holds: the numbers params are built from a one-entry register.
    """
    parked, reason = "ORC-003", "probe: pipeline-only disagreement. OWNER: P5.43"
    fake_parking = {f"{parked}{PIPELINE_DISAGREEMENT_SUFFIX}": reason}
    for key, value in fake_parking.items():
        monkeypatch.setitem(branch_suite.KNOWN_DISAGREEMENTS, key, value)

    numbers = {param.id: param.marks for param in _numbers_params(fake_parking)}
    facts = {param.id: param.marks for param in _fact_pattern_params()}

    assert [(mark.name, mark.kwargs) for mark in numbers[parked]] == [
        ("xfail", {"strict": True, "reason": reason})
    ], f"the parking did not strict-xfail {parked}'s numbers test: {numbers[parked]!r}"
    assert not [oid for oid, marks in numbers.items() if marks and oid != parked], (
        "the parking marked another record's numbers test"
    )
    assert not [oid for oid, marks in facts.items() if marks], (
        "a fact-pattern param carries a mark: parking a numbers-only disagreement "
        "would XPASS(strict) there, and a fact-pattern failure could be parked"
    )
    assert _parametrisation(test_pipeline_reaches_the_records_fact_pattern) is (
        _FACT_PATTERN_PARAMS
    ), "the fact-pattern test is not parametrised by _fact_pattern_params()"
    assert _parametrisation(test_pipeline_matches_oracle) is _NUMBERS_PARAMS, (
        "the numbers test is not parametrised by _numbers_params(KNOWN_DISAGREEMENTS)"
    )


@pytest.mark.parametrize("record", _FACT_PATTERN_PARAMS)
def test_pipeline_reaches_the_records_fact_pattern(record: dict[str, Any]) -> None:
    """The run exercises the record's fact pattern, so its numbers mean something.

    Checked on every leg the pipeline produced for the record's exposure: the
    exposure class and approach the record names, and each stated input in
    ``drivers.PIPELINE_ECHOES`` unchanged -- a null input included -- and in
    ``drivers.PIPELINE_YEAR_ECHOES`` to within one day. A failure here is a
    translation slip or an input lost (or invented) on the way through the
    stages; the message says which column.
    """
    row = _pipeline_row(record["exposure_id"])

    _assert_class_and_approach(record, row)
    assert row["stray_rows"] == 0, "the run produced rows for an exposure that is not the record's"
    assert row["rwa_carrier"] == _EXPECTED_RWA_CARRIER[record["framework"]], (
        f"RWEA was read off {row['rwa_carrier']!r}, which is post-floor under this regime"
    )
    for key, column in drivers.PIPELINE_ECHOES.items():
        if key not in record["inputs"]:
            continue
        carried = row["leg_values"].get(column)
        assert carried == [record["inputs"][key]] * row["legs"], (
            f"input {key}={record['inputs'][key]!r} did not reach the aggregator exit "
            f"as {column}: the legs carry {carried!r}"
        )
    for key, column in drivers.PIPELINE_YEAR_ECHOES.items():
        if key not in record["inputs"]:
            continue
        want_years = float(record["inputs"][key])
        carried = row["leg_values"].get(column)
        assert carried is not None and len(carried) == row["legs"], (
            f"input {key}={want_years!r} is not carried at the aggregator exit as {column}"
        )
        off = [
            years
            for years in carried
            if years is None or abs(years - want_years) > drivers.PIPELINE_YEAR_ECHO_TOLERANCE
        ]
        assert not off, (
            f"input {key}={want_years!r} did not reach the aggregator exit as {column} "
            f"within one day: the legs carry {carried!r}"
        )
    unexpected = {
        code
        for code, severity in row["errors"]
        if severity in ("error", "critical") and code not in _deliberate_error_codes(record)
    }
    assert not unexpected, f"the pipeline judged the translated input defective: {unexpected}"
    _assert_every_branch_justified(row)


@pytest.mark.parametrize("record", _NUMBERS_PARAMS)
def test_pipeline_matches_oracle(record: dict[str, Any]) -> None:
    """The pipeline reproduces the independently-derived figure for one exposure.

    The same comparisons and tolerance as ``test_oracle.test_engine_matches_oracle``,
    with RWA read pre-floor and one difference of rule: an asserted figure the
    pipeline leaves absent is a disagreement here, not a skip -- the branch
    drivers always hand back the columns they compare, and a run that does not
    is the thing this module exists to see.
    """
    row = _pipeline_row(record["exposure_id"])
    _assert_class_and_approach(record, row)
    expected = branch_suite._expected_values(record)
    unasserted = set(record.get("unasserted", ()))

    diffs: list[tuple[str, float, float, float]] = []
    for key, candidates in _PIPELINE_COMPARISONS:
        if key not in expected or key in unasserted:
            continue
        want = float(expected[key])
        engine_value = branch_suite._pick(row, candidates)
        if engine_value is None:
            diffs.append((key, want, math.nan, math.inf))
            continue
        got = float(engine_value)
        error = branch_suite._relative_error(want, got)
        if error > branch_suite.TOLERANCE:
            diffs.append((key, want, got, error))

    assert not diffs, _report(record, diffs, row)


# =============================================================================
# Private helpers
# =============================================================================


def _parametrisation(test: Callable[..., None]) -> object:
    """The argvalues list a test's single ``parametrize`` mark was given."""
    (mark,) = [mark for mark in getattr(test, "pytestmark", ()) if mark.name == "parametrize"]
    return mark.args[1]


@functools.cache
def _pipeline_row(exposure_id: str) -> dict[str, Any]:
    """One pipeline run per record per session; both per-record tests read it."""
    return drivers.run_pipeline(_RECORDS[exposure_id])


def _assert_class_and_approach(record: dict[str, Any], row: dict[str, Any]) -> None:
    """The record's exposure class and approach, on every leg of its exposure."""
    legs = row["legs"]
    assert legs >= 1, "the pipeline produced no leg for the record's exposure"
    want_class = record["inputs"].get("exposure_class", record["exposure_class"])
    want_approach = drivers.PIPELINE_APPROACHES[record["approach"]]

    assert row["leg_values"]["exposure_class"] == [want_class] * legs, (
        f"the classifier put the translated record in {row['leg_values']['exposure_class']}, "
        f"not {want_class!r}: the run tests a different fact pattern"
    )
    assert row["leg_values"]["approach_applied"] == [want_approach] * legs, (
        f"the translated record routed {row['leg_values']['approach_applied']}, "
        f"not {want_approach!r}: the run tests a different fact pattern"
    )


def _assert_every_branch_justified(row: dict[str, Any]) -> None:
    """No leg's treatment rests on a branch the engine itself calls unjustified.

    ``UNKNOWN_FALLBACK`` in a branch-reason column means the predicate deciding
    the row could not be evaluated, so the figure came from the engine's
    fallback, not from the record's fact pattern, and can agree with the oracle
    by coincidence. ORC-052 did, before the translation loaded the obligor's
    ``local_currency``: PS1/26 Art. 121(6) floors an unrated institution at its
    sovereign's weight unless the exposure is in the local currency of its
    jurisdiction, and with that unknown for a US bank the engine left the 40%
    unfloored -- the record's figure, reached without deciding the record's
    question (measured with the obligor's local currency loaded as EUR, so the
    USD loan is foreign: the floor binds at 100%). The engine reports
    such a row as BR001 at WARNING severity on purpose, so the ERROR filter in
    the caller cannot see it; both halves are checked here, and a reason column
    missing from the exit fails rather than passing vacuously.

    No record is exempt. A curated run that reaches an indeterminate branch is
    a translation omitting an input the record implies, or a stage losing one,
    and either is fixed rather than declared.
    """
    for column in BRANCH_REASON_VOCABULARIES:
        reasons = row["leg_values"].get(column)
        assert reasons is not None, (
            f"the aggregator exit carries no {column}: the unjustified-branch check "
            f"would pass whatever the engine did"
        )
        assert UNKNOWN_FALLBACK not in reasons, (
            f"{column} reads {reasons!r}: the engine could not evaluate the predicate "
            f"that decides this record's treatment, so the run tests its fallback, not "
            f"the record's fact pattern. Translate the input the record implies "
            f"(drivers._translate_record), or fix the stage that lost it -- never park it"
        )
    unjustified = [error for error in row["errors"] if error[0] == ERROR_UNKNOWN_BRANCH_FALLBACK]
    assert not unjustified, (
        f"the run reported {unjustified}: a leg's treatment is unjustified by the "
        f"engine's own account, so agreement with the oracle proves nothing"
    )


def _deliberate_error_codes(record: dict[str, Any]) -> set[str]:
    """ERROR-severity codes the translation causes on purpose, and only those.

    DQ020 (no FX rate) for a record denominated in, or protected in, a currency
    other than GBP: ``run_pipeline`` supplies no ``fx_rates`` because a rate row
    rewrites ``currency`` and EAD and so changes the record's fact pattern.
    """
    inputs = record["inputs"]
    currencies = {inputs.get("currency", "GBP")}
    currencies |= {item.get("currency", "GBP") for item in inputs.get("collateral", None) or []}
    currencies |= {item.get("currency", "GBP") for item in inputs.get("guarantees", None) or []}
    return {"DQ020"} if currencies - {"GBP"} else set()


def _report(
    record: dict[str, Any],
    diffs: list[tuple[str, float, float, float]],
    row: dict[str, Any],
) -> str:
    """A triageable failure message: what diverged first, and through which run."""
    oid = record["exposure_id"]
    lines = [
        "",
        f"{oid} ({record['framework']} {record['approach']} {record['exposure_class']}) "
        f"disagrees with the oracle THROUGH THE PIPELINE.",
        f"  regulation:   {record['regulation']}",
        f"  first divergence: {diffs[0][0]}",
        "",
        f"  {'field':<20}{'oracle (derived)':>24}{'pipeline':>24}{'rel err':>12}",
    ]
    for key, want, got, error in diffs:
        lines.append(f"  {key:<20}{want:>24.10f}{got:>24.10f}{error:>12.2e}")
    lines += [
        "",
        f"  legs = {row['legs']}, RWEA carrier = {row['rwa_carrier']}, errors = {row['errors']}",
        f"  leg values = {row['leg_values']}",
        "",
        "  Triage in this order:",
        "  1. If test_pipeline_reaches_the_records_fact_pattern also fails for this",
        "     record, the run is not testing the record's fact pattern. Either the",
        "     translation slipped (a driver bug: fix drivers._translate_record) or",
        "     a stage lost or invented the input (an engine defect, as P1.316 was:",
        "     fix the stage). Fix it, never park it -- a parking marks this test",
        "     only, so the fact-pattern failure would stay red anyway.",
        "  2. If the fact pattern holds, check the inputs held only by the numbers",
        "     (drivers.PIPELINE_UNECHOED_INPUTS) against the leg values above: a",
        "     slip in translating one of those shows up ONLY here. An input whose",
        "     reason says it is inert moves no compared figure on its record.",
        "  3. If both hold and test_oracle.py agrees on this record, the regulatory",
        "     arithmetic is right and production does not reach it. Do NOT adjust",
        "     the oracle; park the record as '<id>@pipeline' in KNOWN_DISAGREEMENTS",
        "     with an OWNER token. It strict-xfails this test only.",
    ]
    return "\n".join(lines)
