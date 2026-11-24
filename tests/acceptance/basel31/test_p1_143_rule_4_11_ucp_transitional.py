"""
P1.143 / P6.15: PS1/26 rule 4.11 — pre-2027 unfunded credit protection keeps
CRR's narrower Art. 213(1)(c)(i) during 1 January 2027 to 30 June 2028.

Pipeline position:
    Loader -> HierarchyResolver -> Classifier -> CRMProcessor -> SACalculator -> Aggregator

Key responsibilities:
- A guarantee whose only defect is a unilateral-change clause, entered into
  before 1 January 2027, is recognised on a Basel 3.1 reporting date inside the
  window (1 January 2027 to 30 June 2028, both days included) and raises no
  CRM012.
- Outside the window, entered into on or after 1 January 2027, or with no
  inception date, the same guarantee is not recognised and raises CRM012.
- The cancel limb is never omitted: a pre-2027 guarantee the provider can
  unilaterally cancel stays ineligible inside the window.
- CRR control: CRR's Art. 213(1)(c)(i) has no "or change" words, so a
  changeable-only guarantee is recognised whatever its inception date.
- IRB route (PS1/26 Art. 183(1A)(b), the same "or change" words for IRB): on
  the P1.122(a) F-IRB borrower, a pre-2027 changeable-only guarantee is
  substituted in the window (750,000 on the covered leg); with no inception
  date it is dropped with a CRM012.

Rule text (ps126app1.pdf, PS1/26 Credit Risk: General Provisions (CRR) Part):
    "4.11 During the period beginning with 1 January 2027 and ending with 30
    June 2028, point (b) of paragraph 1A of Credit Risk: Internal Ratings Based
    Approach (CRR) Part Article 183 and point (c)(i) of paragraph 1 of Credit
    Risk Mitigation (CRR) Part Article 213 shall apply to unfunded credit
    protection entered into prior to 1 January 2027 with the words 'or change'
    wherever they appear omitted."

Hand calculation: tests/fixtures/p1_143/p1_143.py (200,000 recognised,
1,000,000 not recognised, per scenario and reporting date).

Defect under test (pre-fix): GUARANTEE_SCHEMA has no inception date, so the
loader's seal drops ``protection_inception_date`` and the Basel 3.1 change limb
fires on every reporting date — PRE and EVE come out at 1,000,000 with a CRM012
inside the window.

References:
- PS1/26 Credit Risk: General Provisions (CRR) Part, rule 4.11.
- PS1/26 Art. 213(1)(c)(i), Art. 183(1A)(b); CRR Art. 213(1)(c)(i).
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl
import pytest

from rwa_calc.contracts.bundles import AggregatedResultBundle
from rwa_calc.contracts.config import CalculationConfig, PermissionMode
from rwa_calc.contracts.errors import ERROR_INELIGIBLE_UNFUNDED_PROTECTION, CalculationError
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.acceptance.crr.conftest import aggregate_sa_rows_by_parent
from tests.fixtures.p1_122a.p1_122a import EXPECTED_RWA_B31 as P1122A_RWA_SUBSTITUTED
from tests.fixtures.p1_122a.p1_122a import LOAN_REF as P1122A_LOAN_REF
from tests.fixtures.p1_143.p1_143 import (
    INCEPTION_CUTOFF,
    RWA_NOT_RECOGNISED,
    RWA_RECOGNISED,
    SCENARIO_BY_KEY,
    SCENARIOS,
    WINDOW_FIRST_DAY,
    WINDOW_LAST_DAY,
    create_p1143_counterparties,
    create_p1143_guarantees,
    create_p1143_loans,
    create_p1143_ratings,
)
from tests.fixtures.raw_bundle import make_raw_bundle

# ---------------------------------------------------------------------------
# Expected outcomes: True = recognised (200,000), False = not (1,000,000)
# ---------------------------------------------------------------------------

_INSIDE = {"PRE": True, "EVE": True, "CUT": False, "POST": False, "NULL": False, "CANCEL": False}
_OUTSIDE = dict.fromkeys(_INSIDE, False)

# (id, reporting date, expected recognition per scenario)
_B31_RUNS: list[tuple[str, date, dict[str, bool]]] = [
    ("before-window-2026-12-31", date(2026, 12, 31), _OUTSIDE),
    ("first-day-2027-01-01", WINDOW_FIRST_DAY, _INSIDE),
    ("inside-2027-06-30", date(2027, 6, 30), _INSIDE),
    ("last-day-2028-06-30", WINDOW_LAST_DAY, _INSIDE),
    ("after-window-2028-07-01", date(2028, 7, 1), _OUTSIDE),
]

_CRR_REPORTING_DATE = date(2026, 12, 31)
_CRR_EXPECTED = {**dict.fromkeys(_INSIDE, True), "CANCEL": False}

_CASES = [
    pytest.param(run_id, reporting_date, key, expected[key], id=f"{run_id}-{key}")
    for run_id, reporting_date, expected in _B31_RUNS
    for key in expected
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(config: CalculationConfig) -> AggregatedResultBundle:
    """One SA pipeline run over every P1.143 scenario."""
    bundle = make_raw_bundle(
        loans=create_p1143_loans(),
        counterparties=create_p1143_counterparties(),
        ratings=create_p1143_ratings(),
        guarantees=create_p1143_guarantees(),
    )
    return PipelineOrchestrator().run_with_data(bundle, config)


def _rwa(results: AggregatedResultBundle, loan_reference: str) -> float:
    """The loan's rwa_final, summed over its guarantee split rows."""
    assert results.sa_results is not None
    return aggregate_sa_rows_by_parent(results.sa_results.collect(), loan_reference)["rwa_final"]


def _crm012_for(results: AggregatedResultBundle, loan_reference: str) -> list[CalculationError]:
    """The CRM012 warnings naming the loan the guarantee covers."""
    return [
        e
        for e in results.errors
        if e.code == ERROR_INELIGIBLE_UNFUNDED_PROTECTION and e.exposure_reference == loan_reference
    ]


@pytest.fixture(scope="module")
def b31_runs() -> dict[str, AggregatedResultBundle]:
    """One Basel 3.1 SA run per reporting date in ``_B31_RUNS``."""
    return {
        run_id: _run(
            CalculationConfig.basel_3_1(
                reporting_date=reporting_date, permission_mode=PermissionMode.STANDARDISED
            )
        )
        for run_id, reporting_date, _ in _B31_RUNS
    }


@pytest.fixture(scope="module")
def crr_run() -> AggregatedResultBundle:
    """The CRR control run."""
    return _run(
        CalculationConfig.crr(
            reporting_date=_CRR_REPORTING_DATE, permission_mode=PermissionMode.STANDARDISED
        )
    )


# ---------------------------------------------------------------------------
# Fixture adequacy — the scenarios can express the rule
# ---------------------------------------------------------------------------


def test_fixture_scenarios_express_each_rule_4_11_boundary() -> None:
    """The changeable-only rows straddle the cut-off; CANCEL is the cancel limb."""
    # Arrange
    changeable_only = [s for s in SCENARIOS if s.changeable_only]

    # Assert
    assert [s.key for s in changeable_only] == ["PRE", "EVE", "CUT", "POST", "NULL"], (
        "every boundary row must be changeable-only, or a pass could come from the cancel limb"
    )
    assert SCENARIO_BY_KEY["EVE"].inception == date(2026, 12, 31)
    assert SCENARIO_BY_KEY["CUT"].inception == INCEPTION_CUTOFF, (
        "CUT must sit ON the cut-off so a '<=' gate is caught"
    )
    assert SCENARIO_BY_KEY["NULL"].inception is None
    assert SCENARIO_BY_KEY["CANCEL"].cancellable
    assert SCENARIO_BY_KEY["CANCEL"].inception is not None
    assert SCENARIO_BY_KEY["CANCEL"].inception < INCEPTION_CUTOFF, (
        "CANCEL must be pre-2027, or it does not show the cancel limb surviving rule 4.11"
    )


# ---------------------------------------------------------------------------
# Basel 3.1 — the window and the cut-off
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("run_id", "reporting_date", "key", "recognised"), _CASES)
def test_b31_rule_4_11_recognition_by_reporting_date_and_inception(
    b31_runs: dict[str, AggregatedResultBundle],
    run_id: str,
    reporting_date: date,
    key: str,
    recognised: bool,
) -> None:
    """rwa_final is 200,000 where rule 4.11 keeps the guarantee, 1,000,000 where not."""
    # Arrange
    scenario = SCENARIO_BY_KEY[key]
    expected = RWA_RECOGNISED if recognised else RWA_NOT_RECOGNISED

    # Act
    rwa = _rwa(b31_runs[run_id], scenario.loan_reference)

    # Assert
    assert rwa == pytest.approx(expected, abs=1.0), (
        f"{key} at {reporting_date} (inception {scenario.inception}, "
        f"cancellable={scenario.cancellable}, changeable={scenario.changeable}): "
        f"expected rwa_final {expected:,.0f}, got {rwa:,.2f}"
    )


@pytest.mark.parametrize(("run_id", "reporting_date", "key", "recognised"), _CASES)
def test_b31_rule_4_11_crm012_only_where_not_recognised(
    b31_runs: dict[str, AggregatedResultBundle],
    run_id: str,
    reporting_date: date,
    key: str,
    recognised: bool,
) -> None:
    """Exactly one CRM012 names a guarantee the screen drops; none names one it keeps."""
    # Arrange
    scenario = SCENARIO_BY_KEY[key]

    # Act
    warnings = _crm012_for(b31_runs[run_id], scenario.loan_reference)

    # Assert
    assert len(warnings) == (0 if recognised else 1), (
        f"{key} at {reporting_date}: expected {0 if recognised else 1} CRM012, got "
        f"{[w.message for w in warnings]}"
    )


def test_b31_crm012_for_an_undated_guarantee_in_the_window_names_rule_4_11(
    b31_runs: dict[str, AggregatedResultBundle],
) -> None:
    """A changeable-only guarantee with no inception date says why rule 4.11 did not help."""
    # Arrange
    loan = SCENARIO_BY_KEY["NULL"].loan_reference

    # Act
    warnings = _crm012_for(b31_runs["inside-2027-06-30"], loan)

    # Assert
    assert len(warnings) == 1
    assert "4.11" in warnings[0].message
    assert "protection_inception_date" in warnings[0].message


# ---------------------------------------------------------------------------
# CRR control — no "or change" words to omit
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("key", list(_CRR_EXPECTED))
def test_crr_changeable_only_is_recognised_whatever_the_inception_date(
    crr_run: AggregatedResultBundle, key: str
) -> None:
    """CRR Art. 213(1)(c)(i) has only the cancel limb: only CANCEL is dropped."""
    # Arrange
    scenario = SCENARIO_BY_KEY[key]
    expected = RWA_RECOGNISED if _CRR_EXPECTED[key] else RWA_NOT_RECOGNISED

    # Act
    rwa = _rwa(crr_run, scenario.loan_reference)

    # Assert
    assert rwa == pytest.approx(expected, abs=1.0)
    assert len(_crm012_for(crr_run, scenario.loan_reference)) == (0 if _CRR_EXPECTED[key] else 1)


def test_every_scenario_reaches_the_sa_results(
    b31_runs: dict[str, AggregatedResultBundle],
) -> None:
    """Every run produced SA rows for every scenario (a vanished row is not a result)."""
    # Arrange
    loans = {s.loan_reference for s in SCENARIOS}

    for run_id, results in b31_runs.items():
        # Act
        assert results.sa_results is not None
        parents = set(
            results.sa_results.select("parent_exposure_reference")
            .collect()
            .get_column("parent_exposure_reference")
            .to_list()
        )

        # Assert
        assert loans <= parents, f"{run_id}: missing {sorted(loans - parents)}"


# ---------------------------------------------------------------------------
# IRB route — Art. 183(1A)(b), on the P1.122(a) F-IRB borrower
# ---------------------------------------------------------------------------

_P1122A_DIR = Path(__file__).parent.parent.parent / "fixtures" / "p1_122a" / "data"


def _p1122a_irb_run(inception: date | None) -> AggregatedResultBundle:
    """P1.122(a) at 2027-06-30 with its guarantee made changeable-only and dated."""
    guarantees = pl.read_parquet(_P1122A_DIR / "guarantee.parquet").with_columns(
        pl.lit(False).alias("is_unilaterally_cancellable"),
        pl.lit(True).alias("is_unilaterally_changeable"),
        pl.lit(inception, dtype=pl.Date).alias("protection_inception_date"),
    )
    bundle = make_raw_bundle(
        facilities=pl.scan_parquet(_P1122A_DIR / "facility.parquet"),
        loans=pl.scan_parquet(_P1122A_DIR / "loan.parquet"),
        counterparties=pl.scan_parquet(_P1122A_DIR / "counterparty.parquet"),
        guarantees=guarantees,
        ratings=pl.scan_parquet(_P1122A_DIR / "rating.parquet"),
        model_permissions=pl.scan_parquet(_P1122A_DIR / "model_permission.parquet"),
    )
    config = CalculationConfig.basel_3_1(
        reporting_date=date(2027, 6, 30), permission_mode=PermissionMode.IRB
    )
    return PipelineOrchestrator().run_with_data(bundle, config)


def _irb_loan_rows(results: AggregatedResultBundle) -> pl.DataFrame:
    assert results.irb_results is not None
    return results.irb_results.filter(
        pl.col("parent_exposure_reference") == P1122A_LOAN_REF
    ).collect()


def test_irb_pre_2027_changeable_only_guarantee_is_substituted_in_the_window() -> None:
    """F-IRB borrower: the covered leg takes the guarantor's 75% (P1.122(a)), no CRM012."""
    # Act
    results = _p1122a_irb_run(date(2026, 6, 1))
    rows = _irb_loan_rows(results)

    # Assert
    assert rows.height > 0, "the F-IRB loan must reach the IRB results"
    assert float(rows["rwa_final"].sum()) == pytest.approx(P1122A_RWA_SUBSTITUTED, abs=1.0)
    assert float(rows["guaranteed_portion"].fill_null(0.0).sum()) == pytest.approx(
        1_000_000.0, abs=1.0
    ), "the covered leg carries the cover — so the sibling test's zero is not vacuous"
    assert _crm012_for(results, P1122A_LOAN_REF) == []


def test_irb_undated_changeable_only_guarantee_is_dropped_in_the_window() -> None:
    """F-IRB borrower: no inception date -> not grandfathered, CRM012, no covered leg."""
    # Act
    results = _p1122a_irb_run(None)
    rows = _irb_loan_rows(results)

    # Assert
    assert rows.height > 0, "the F-IRB loan must reach the IRB results"
    assert len(_crm012_for(results, P1122A_LOAN_REF)) == 1
    assert float(rows["guaranteed_portion"].fill_null(0.0).sum()) == 0.0
