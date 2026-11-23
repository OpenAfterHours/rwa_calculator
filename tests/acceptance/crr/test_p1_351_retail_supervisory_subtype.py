"""P1.351 — retail IRB rows priced on a corporate supervisory LGD are named (IRB009).

CRR Art. 161(1) is a corporates / institutions article: (e)/(f) confine the
senior/subordinated supervisory LGD rates to purchased **corporate** receivables
and (a)/(b) are the corporate seniority fallbacks (`crr.pdf` p.157). For retail,
Art. 151(7) and Art. 164(1) require own LGD estimates, and the only supervisory
retail LGD is for **dilution risk** of purchased receivables (Art. 164(1)).
PS1/26 doubles the confinement: Art. 161 is headed "CORPORATES AND
INSTITUTIONS" and para 1 opens "An institution using the Foundation IRB
Approach"; Art. 164(1)(a) requires own retail estimates and (b) sets retail
dilution at 100%; Art. 147A(1)(g) allows retail only SA or A-IRB.

The engine nevertheless accepts a ``retail_other`` / ``foundation_irb`` model
permission and prices the retail rows on the Art. 161(1) rates. That root cause
(accepting the permission, discarding the firm's LGD) is a separate item whose
remedy is an owner decision. **P1.351 is the error-channel half only:** the
pipeline exit raises an IRB009 WARNING naming every retail IRB row priced on a
corporate supervisory LGD, and no LGD or RWA moves.

The guard is asymmetric, and the asymmetry is the whole test:

- FIRES on retail ``senior`` and ``subordinated`` subtypes (Art. 161(1)(e)/(f))
  and on the retail row with NO subtype, which takes ``supervisory_firb`` — the
  Art. 161(1)(a) seniority fallback, every bit as corporate as (e)/(f).
- SILENT on the retail ``dilution_risk`` row (Art. 164(1) legislates it) and on
  the corporate ``senior`` row (Art. 161(1)(e) authorises it).

The silent limb is the EXACT spelling ``dilution_risk``, not an allowlist of
``senior`` / ``subordinated``. The input gate's DQ006 lower-cases both sides, so
``Subordinated`` or ``Dilution_Risk`` passes it; the engine dispatch matches
exactly, so it prices those rows on the Art. 161(1)(a)/(b) seniority fallback.
``TestCaseVariantSubtypes`` runs that input in both regimes: IRB009 is the only
finding that names those rows.

Both regimes are covered and each can fail on its own (the error-channel class
is parametrised). The Basel 3.1 leg needs two input deltas
(``create_p1351_b31_counterparty`` / ``create_p1351_b31_loans``) to reach retail
F-IRB at all; the adequacy test asserts it got there, so the leg cannot pass by
the rows going to SA.

Two measured facts recorded here because they are easy to get backwards:

- Row 1 (``senior``) applies **the same LGD as row 5 (no subtype at all)** —
  0.45 under CRR. The subtype changes the recorded branch reason, not the
  number.
- Row 5 reaches ``SUPERVISORY_FIRB``, **not** ``UNKNOWN_FALLBACK``, so no BR001
  is raised for it. ``is_firb_cleared`` fires for any F-IRB row with a null LGD
  before the ``otherwise`` clause, and ``scripts/branch_census_baseline.json``
  banks ``UNKNOWN_FALLBACK`` as desired-dead. IRB009 therefore keys on the
  branch reason and the IRB class, never on the subtype alone.

References:
- CRR Art. 151(7), Art. 161(1)(a)/(e)/(f), Art. 164(1)
- PS1/26 Art. 147A(1)(g), Art. 161(1), Art. 164(1)(a)/(b)
"""

from __future__ import annotations

from functools import cache

import pytest
from tests.fixtures.p1_351.p1_351 import (
    B31_REPORTING_DATE,
    CASE_VARIANT_SUBTYPES,
    LOAN_REF_CORP_JUNIOR,
    LOAN_REF_CORP_SENIOR,
    LOAN_REF_RETAIL_DILUTION,
    LOAN_REF_RETAIL_NOSUBTYPE,
    LOAN_REF_RETAIL_SENIOR,
    LOAN_REF_RETAIL_SUB,
    REPORTING_DATE,
    create_p1351_b31_counterparty,
    create_p1351_b31_loans,
    create_p1351_counterparty,
    create_p1351_loans,
    create_p1351_model_permissions,
    create_p1351_rating,
    respell_p1351_subtypes,
)
from tests.fixtures.raw_bundle import make_raw_bundle

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.contracts.errors import ErrorCategory, ErrorSeverity
from rwa_calc.domain.branch_reasons import UNKNOWN_FALLBACK
from rwa_calc.engine.pipeline import PipelineOrchestrator

#: The IRB009 code, written out rather than imported so the test is anchored to
#: the published code and not to whatever the constant happens to hold.
_IRB009 = "IRB009"
_BR001 = "BR001"

_RETAIL_REFS = (
    LOAN_REF_RETAIL_SENIOR,
    LOAN_REF_RETAIL_SUB,
    LOAN_REF_RETAIL_DILUTION,
    LOAN_REF_RETAIL_NOSUBTYPE,
)

#: The rows priced on an Art. 161(1) corporate rate although their IRB class is
#: retail — senior (e), subordinated (f) and the no-subtype (a) fallback.
_UNAUTHORISED_RETAIL_REFS = frozenset(
    {LOAN_REF_RETAIL_SENIOR, LOAN_REF_RETAIL_SUB, LOAN_REF_RETAIL_NOSUBTYPE}
)


#: Case-variant leg: the four retail rows, each priced on an Art. 161(1) corporate
#: rate, the respelled ``Dilution_Risk`` row included.
_RESPELLED_UNAUTHORISED_RETAIL_REFS = frozenset(_RETAIL_REFS)

#: The Art. 161(1)(a) senior seniority fallback each regime prices a respelled
#: senior-seniority row on: CRR 45%; PS1/26 40% for a non-financial obligor
#: (Art. 161(1)(aa)). Not the Art. 164(1) dilution rate (CRR 75%, PS1/26 100%).
_SENIOR_FALLBACK_LGD = {"crr": 0.45, "b31": 0.40}

#: The Art. 161(1)(b) subordinated fallback, in both regimes — not (f)'s 100%.
_SUBORDINATED_FALLBACK_LGD = 0.75


@cache
def _run(regime: str, *, respelled: bool = False):
    """Run the P1.351 bundle once per regime, from the fixture's own frames.

    ``respelled`` swaps in the case-variant leg (``respell_p1351_subtypes``).
    """
    if regime == "crr":
        counterparties, loans = create_p1351_counterparty(), create_p1351_loans()
        config = CalculationConfig.crr(reporting_date=REPORTING_DATE)
    else:
        counterparties, loans = create_p1351_b31_counterparty(), create_p1351_b31_loans()
        config = CalculationConfig.basel_3_1(reporting_date=B31_REPORTING_DATE)
    if respelled:
        loans = respell_p1351_subtypes(loans)
    bundle = make_raw_bundle(
        counterparties=counterparties,
        loans=loans,
        ratings=create_p1351_rating(),
        model_permissions=create_p1351_model_permissions(),
    )
    return PipelineOrchestrator().run_with_data(bundle, config)


def _rows_by_reference(result) -> dict[str, dict]:
    """Index a result's rows by exposure reference."""
    frame = result.results.collect()
    return {
        row["exposure_reference"]: row for row in frame.to_dicts() if row.get("exposure_reference")
    }


@pytest.fixture(scope="module")
def p1351_result():
    """The P1.351 bundle run under CRR."""
    return _run("crr")


@pytest.fixture(scope="module")
def p1351_rows(p1351_result) -> dict[str, dict]:
    """Index the CRR result rows by exposure reference."""
    return _rows_by_reference(p1351_result)


@pytest.fixture(scope="module", params=["crr", "b31"])
def regime_run(request) -> tuple[str, object, dict[str, dict]]:
    """The P1.351 bundle run under each regime: (regime, result, rows)."""
    result = _run(request.param)
    return request.param, result, _rows_by_reference(result)


class TestSupervisorySubtypeReachesTheDispatch:
    """The dispatch is exercised at all — it is banked as dead everywhere else."""

    @pytest.mark.parametrize(
        "ref",
        [
            LOAN_REF_RETAIL_SENIOR,
            LOAN_REF_RETAIL_SUB,
            LOAN_REF_RETAIL_DILUTION,
            LOAN_REF_CORP_SENIOR,
        ],
    )
    def test_subtype_rows_take_the_supervisory_subtype_branch(
        self, p1351_rows: dict[str, dict], ref: str
    ) -> None:
        """Every subtype-bearing row is priced by the Art. 161(1) dispatch."""
        row = p1351_rows[ref]

        assert row["irb_lgd_branch_reason"] == "supervisory_subtype", (
            f"{ref} did not reach the supervisory-subtype dispatch. This fixture is "
            "the only thing in the estate that exercises it — the branch census "
            "banks it as dead because the subtype is null everywhere else."
        )


class TestTodaysLgdValues:
    """Absolute LGD/RWA pins. A fix that changes a VALUE here is out of P1.351's scope.

    The dilution row's RWA moved once, deliberately, under review TR-03 — not an
    LGD change (its 0.75 is untouched) but the risk-weight FUNCTION: CRR
    Art. 157(1) prices "dilution risk of purchased corporate and retail
    receivables in accordance with the formula set out in Article 153(1)", so the
    retail row takes the corporate correlation (0.164146 at PD 2%, not the
    retail 0.094556). At M = 1 the maturity adjustment is 1, so RWA =
    0.75 x (N(...) - 0.02) x 12.5 x 1.06 x 100,000 = 169,194.90 (was 102,442.72).
    """

    @pytest.mark.parametrize(
        ("ref", "expected_lgd", "expected_rwa"),
        [
            (LOAN_REF_RETAIL_SENIOR, 0.45, 61_465.63),
            (LOAN_REF_RETAIL_SUB, 1.00, 136_590.29),
            (LOAN_REF_RETAIL_DILUTION, 0.75, 169_194.90),
            (LOAN_REF_CORP_SENIOR, 0.45, 101_516.94),
            (LOAN_REF_RETAIL_NOSUBTYPE, 0.45, 61_465.63),
        ],
    )
    def test_lgd_and_rwa(
        self, p1351_rows: dict[str, dict], ref: str, expected_lgd: float, expected_rwa: float
    ) -> None:
        """P1.351 is an ERROR-CHANNEL item: these numbers must not move."""
        row = p1351_rows[ref]

        assert row["lgd_floored"] == pytest.approx(expected_lgd, abs=1e-9)
        assert row["rwa_final"] == pytest.approx(expected_rwa, abs=0.01)

    def test_senior_subtype_changes_the_reason_but_not_the_number(
        self, p1351_rows: dict[str, dict]
    ) -> None:
        """The sharpest fact in the item, and the easiest to get backwards.

        A retail row with ``senior`` and a retail row with NO subtype take the
        SAME LGD by DIFFERENT routes. So on this F-IRB path the unauthorised
        supervisory rate is not a wrong number — it is an unrecorded one.
        """
        with_subtype = p1351_rows[LOAN_REF_RETAIL_SENIOR]
        without_subtype = p1351_rows[LOAN_REF_RETAIL_NOSUBTYPE]

        assert with_subtype["lgd_floored"] == without_subtype["lgd_floored"]
        assert with_subtype["irb_lgd_branch_reason"] != without_subtype["irb_lgd_branch_reason"]
        assert without_subtype["irb_lgd_branch_reason"] == "supervisory_firb"


class TestIrb009NamesRetailRowsOnCorporateSupervisoryLgd:
    """The P1.351 fix, in both regimes: IRB009 on exactly three rows, no value moved."""

    def test_retail_rows_reach_foundation_irb_on_a_retail_class(self, regime_run) -> None:
        """Adequacy: the population the warning is about exists in this regime.

        Without this the Basel 3.1 leg could pass by every retail row going to
        SA (no ``irb_lgd_branch_reason``, so nothing to warn about).
        """
        regime, _, rows = regime_run

        for ref in _RETAIL_REFS:
            assert rows[ref]["approach_applied"] == "foundation_irb", (
                f"{regime}: {ref} did not reach F-IRB - the IRB009 assertions below "
                "would be vacuous"
            )
            assert rows[ref]["exposure_class_irb"] == "retail_other", f"{regime}: {ref}"
        assert rows[LOAN_REF_CORP_SENIOR]["exposure_class_irb"] == "corporate"
        assert rows[LOAN_REF_RETAIL_NOSUBTYPE]["irb_lgd_branch_reason"] == "supervisory_firb"
        for ref in (LOAN_REF_RETAIL_SENIOR, LOAN_REF_RETAIL_SUB, LOAN_REF_RETAIL_DILUTION):
            assert rows[ref]["irb_lgd_branch_reason"] == "supervisory_subtype", f"{regime}: {ref}"

    def test_irb009_names_exactly_the_unauthorised_retail_rows(self, regime_run) -> None:
        """Retail senior / subordinated / no-subtype fire; dilution and corporate do not.

        Arrange: the five P1.351 rows under one regime.
        Act:     read the IRB009 errors the pipeline exit raised.
        Assert:  they name exactly the three retail rows priced on an Art. 161(1)
                 corporate rate, once each. The retail dilution row (Art. 164(1)
                 legislates it) and the corporate row (Art. 161(1)(e) authorises
                 it) must stay silent, or the guard over-reaches.
        """
        regime, result, _ = regime_run

        named = [e.exposure_reference for e in result.errors if e.code == _IRB009]

        assert sorted(named) == sorted(_UNAUTHORISED_RETAIL_REFS), (
            f"{regime}: IRB009 named {sorted(named)}; expected exactly "
            f"{sorted(_UNAUTHORISED_RETAIL_REFS)}"
        )

    def test_irb009_is_a_data_quality_warning(self, regime_run) -> None:
        """WARNING, not ERROR: the row keeps its number; the error names the authority gap."""
        regime, result, _ = regime_run

        irb009 = [e for e in result.errors if e.code == _IRB009]

        assert irb009, f"{regime}: no IRB009 raised"
        for error in irb009:
            assert error.severity == ErrorSeverity.WARNING
            assert error.category == ErrorCategory.DATA_QUALITY
            assert error.field_name == "irb_lgd_branch_reason"
            assert "Art. 164(1)" in (error.regulatory_reference or "")

    def test_no_p1351_row_lands_on_unknown_fallback(self, regime_run) -> None:
        """Row 5 is justified-by-construction (``supervisory_firb``), so no BR001."""
        regime, result, rows = regime_run

        br001 = [e.exposure_reference for e in result.errors if e.code == _BR001]

        assert br001 == [], f"{regime}: unexpected BR001 on {br001}"
        assert all(row["irb_lgd_branch_reason"] != UNKNOWN_FALLBACK for row in rows.values())


class TestCrrErrorChannel:
    """Under CRR the bundle is otherwise clean, so IRB009 is the whole error list."""

    def test_irb009_is_the_only_error_raised(self, p1351_result) -> None:
        """Pre-fix this list was ``[]`` — the silence that WAS the defect."""
        assert sorted(e.code for e in p1351_result.errors) == [_IRB009] * 3, (
            "Under CRR exactly the senior, subordinated and no-subtype RETAIL rows "
            "carry an IRB009 warning and nothing else is raised. The dilution row "
            "(Art. 164(1) legislates for it) and the corporate row (Art. 161(1)(e) "
            "authorises it) must stay silent, or the guard is over-reaching."
        )

    def test_every_row_is_emitted(self, p1351_rows: dict[str, dict]) -> None:
        """Negative space: a vanished row is neither a result nor an error."""
        for ref in (
            LOAN_REF_RETAIL_SENIOR,
            LOAN_REF_RETAIL_SUB,
            LOAN_REF_RETAIL_DILUTION,
            LOAN_REF_CORP_SENIOR,
            LOAN_REF_RETAIL_NOSUBTYPE,
        ):
            assert ref in p1351_rows, f"{ref} did not reach the results frame"
            assert p1351_rows[ref]["lgd_floored"] is not None
            assert p1351_rows[ref]["rwa_final"] is not None


class TestClassSplitIsWhatDistinguishes:
    """The retail/corporate split is the whole regulatory point."""

    def test_retail_and_corporate_senior_share_a_rate_but_not_an_authority(
        self, p1351_rows: dict[str, dict]
    ) -> None:
        """Both take 0.45; only the corporate one is authorised to.

        CRR Art. 161(1)(e) says "senior purchased CORPORATE receivables". The
        retail row reaching the same rate is the defect — and because the RATE
        matches, no value-based test can distinguish them. Only the class can.
        """
        retail = p1351_rows[LOAN_REF_RETAIL_SENIOR]
        corporate = p1351_rows[LOAN_REF_CORP_SENIOR]

        assert retail["lgd_floored"] == pytest.approx(corporate["lgd_floored"], abs=1e-9)
        assert retail["exposure_class_irb"] == "retail_other"
        assert corporate["exposure_class_irb"] == "corporate"


@pytest.fixture(scope="module", params=["crr", "b31"])
def respelled_run(request) -> tuple[str, object, dict[str, dict]]:
    """The case-variant leg under each regime: (regime, result, rows)."""
    result = _run(request.param, respelled=True)
    return request.param, result, _rows_by_reference(result)


class TestCaseVariantSubtypes:
    """A respelled subtype passes the input gate and misses the dispatch: IRB009 names it.

    DQ006 lower-cases both sides before checking (``contracts/validation.py``),
    so ``Senior`` / ``Subordinated`` / ``Dilution_Risk`` are valid input. The
    engine dispatch (``engine/irb/transforms.py::apply_firb_lgd``) matches the
    exact lower-case spelling, so each respelled row takes the ``otherwise``
    seniority fallback — an Art. 161(1)(a)/(b) corporate rate — on the
    ``supervisory_subtype`` branch. ``Dilution_Risk`` is therefore NOT priced on
    the Art. 164(1) retail dilution rate, and IRB009 is the only finding that
    names it. A guard that allowlisted ``senior`` / ``subordinated`` (and left an
    off-vocabulary spelling to DQ006) lets all three through in silence.
    """

    def test_respelled_rows_take_the_seniority_fallback_on_the_subtype_branch(
        self, respelled_run
    ) -> None:
        """Adequacy: the respelled rows reach the dispatch and miss every subtype rate.

        Arrange: the case-variant leg under one regime.
        Act:     read the respelled retail rows.
        Assert:  each is on ``supervisory_subtype`` and priced on the Art. 161(1)
                 seniority fallback by its ``seniority`` column — so the
                 ``Dilution_Risk`` row is on the corporate senior rate, not the
                 Art. 164(1) dilution rate.
        """
        regime, _, rows = respelled_run
        senior_fallback = _SENIOR_FALLBACK_LGD[regime]
        expected_lgd = {
            LOAN_REF_RETAIL_SENIOR: senior_fallback,
            LOAN_REF_RETAIL_SUB: _SUBORDINATED_FALLBACK_LGD,
            LOAN_REF_RETAIL_DILUTION: senior_fallback,
        }

        for ref, lgd in expected_lgd.items():
            row = rows[ref]
            assert row["purchased_receivables_subtype"] == CASE_VARIANT_SUBTYPES[ref]
            assert row["exposure_class_irb"] == "retail_other", f"{regime}: {ref}"
            assert row["irb_lgd_branch_reason"] == "supervisory_subtype", f"{regime}: {ref}"
            assert row["lgd_floored"] == pytest.approx(lgd, abs=1e-9), f"{regime}: {ref}"

    def test_input_gate_names_only_the_out_of_vocabulary_spelling(self, respelled_run) -> None:
        """DQ006 runs on this path and accepts every respelling: it names ``junior`` only.

        This pins the premise the IRB009 design must not lean on: an
        off-vocabulary subtype is NOT always named by DQ006.
        """
        regime, result, _ = respelled_run

        dq006 = [e.actual_value for e in result.errors if e.code == "DQ006"]

        assert dq006 == ["junior"], f"{regime}: DQ006 raised on {dq006}"

    def test_irb009_names_every_retail_row_on_a_corporate_rate(self, respelled_run) -> None:
        """All four retail rows fire, ``Dilution_Risk`` included; both corporate rows do not.

        Arrange: the case-variant leg under one regime.
        Act:     read the IRB009 errors the pipeline exit raised.
        Assert:  they name exactly the four retail rows, once each. The corporate
                 ``Senior`` and ``junior`` rows are Art. 161(1)'s own population
                 and stay silent, whatever the spelling.
        """
        regime, result, _ = respelled_run

        named = [e.exposure_reference for e in result.errors if e.code == _IRB009]

        assert sorted(named) == sorted(_RESPELLED_UNAUTHORISED_RETAIL_REFS), (
            f"{regime}: IRB009 named {sorted(named)}; expected exactly "
            f"{sorted(_RESPELLED_UNAUTHORISED_RETAIL_REFS)}"
        )
        assert LOAN_REF_CORP_JUNIOR not in named
