"""
P1.358 — outcome: an ECB guarantee is priced at Art. 114(3)'s 0%, end to end.

Pipeline position:
    Loader -> HierarchyResolver -> Classifier -> CRMProcessor (guarantee split)
        -> SA / IRB guarantee substitution -> OutputAggregator (output floor)

Why this exists: ``tests/unit/test_p1_358_ecb_guarantor_art_114_3.py`` pins the
guarantor risk-weight chain and both substitution functions on hand-built frames.
This file pins what a firm actually sees — the covered leg's RWEA on an SA loan
and on an F-IRB loan, and, under Basel 3.1, the covered leg's SA-equivalent
(``sa_rwa``), which is the output floor's S-TREA input (PS1/26 Art. 92(2A)). The
SA-equivalent is produced by running the SA guarantee substitution over every
row (``engine/sa/calculator.py``), so it moves with the same chain (LESSONS D1).

The rule: CRR Art. 114(3) "Exposures to the ECB shall be assigned a 0 % risk
weight"; PS1/26 Art. 114(3) "Exposures to the European Central Bank shall be
assigned a 0% risk weight." Art. 235(1) prices the covered part at the risk
weight of a (comparable) direct exposure to the protection provider; Art. 235(3)
conditions only the 114(4) / 114(7) treatments on currency and funding.

Shape (P1.227's borrowers and model permission; every loan GBP 1,000,000 drawn,
senior, 2027-01-01 to 2030-01-01; every guarantee GBP 500,000, i.e. 50%):

    loan              borrower                          guarantor (unrated, no country)
    LN_P358_SA_ECB    unrated large corporate, SA        ECB         (central_bank_ecb)
    LN_P358_SA_CB     unrated large corporate, SA        central bank (control)
    LN_P358_IRB_ECB   CP_P227_B_IRB, F-IRB, PD 1.50%     ECB
    LN_P358_IRB_CB    CP_P227_B_IRB, F-IRB, PD 1.50%     central bank (control)

Each guaranteed loan splits into a covered leg (EAD 500,000) and an uncovered
remainder (EAD 500,000).

Hand-calculation (reporting date 2027-02-01, both regimes, PermissionMode.IRB):
- SA borrower: unrated corporate, CRR Art. 122(2) / PS1/26 Art. 122(2) -> 100%.
- F-IRB borrower: the P1.395 derivation (PD 1.50%, M = 2.91507 y) gives 1,000,000
  of EAD an RWEA of 1,175,736.91 (CRR, LGD 45%, x 1.06) / 985,942.90 (B31, LGD
  40%), i.e. 587,868.455 / 492,971.45 per 500,000 leg. Its SA-equivalent is the
  unrated corporate 100%.
- ECB guarantor: 0% (Art. 114(3)). Covered legs:
    SA     0 < 100%         -> substituted, RWEA 0
    F-IRB  0 < IRB RW       -> substituted, RWEA 0 (CRR and B31)
    B31 sa_rwa (floor input) 0 < 100% -> 0
- Central-bank control: unrated, Art. 114(1) 100%. Covered legs:
    SA     100% !< 100%     -> declined, RWEA 500,000
    F-IRB  CRR 100% < 117.57% -> substituted at 100%, RWEA 500,000
           B31 100% !< 98.59% -> declined, RWEA 492,971.45
    B31 sa_rwa 500,000

Pre-fix the ECB legs priced exactly as the control (Table 1 unrated 100%): SA
loan RWEA 1,000,000; F-IRB covered leg 500,000 (CRR) / 492,971.45 (B31); B31
covered-leg sa_rwa 500,000 and S-TREA 2,000,000.

References:
- CRR Art. 114(3), 201(1)(a), 235(1)/(3); PS1/26 Art. 114(3), 201(1)(a),
  235(1)(a)/(3), 92(2A)
- tests/fixtures/p1_227/p1_227.py (borrowers, internal rating, model permission)
- tests/acceptance/test_p1_395_flagged_natural_person_guarantor_pipeline.py
  (the F-IRB RWEA derivation reused here)
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.bundles import OutputFloorSummary, RawDataBundle
from rwa_calc.contracts.config import CalculationConfig, PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.fixtures.p1_227.p1_227 import (
    CP_B_IRB_REF,
    CP_B_REF,
    GUARANTEE_G2_REF,
    LOAN_G2_REF,
    LOAN_G3_REF,
    create_p227_counterparties,
    create_p227_guarantees,
    create_p227_loans,
    create_p227_model_permission,
    create_p227_ratings,
)
from tests.fixtures.raw_bundle import make_raw_bundle

_REPORTING_DATE = date(2027, 2, 1)
_REGIMES: tuple[str, ...] = ("crr", "b31")

_SA_BORROWER = "CP_P358_SA"
_ECB = "CP_P358_ECB"
_CENTRAL_BANK = "CP_P358_CB"
_GUARANTORS: dict[str, str] = {_ECB: "central_bank_ecb", _CENTRAL_BANK: "central_bank"}

_LOAN_EAD = 1_000_000.0
_COVERED = 500_000.0

#: F-IRB RWEA per 500,000 leg (P1.395 derivation, halved).
_IRB_LEG_RWEA: dict[str, float] = {"crr": 587_868.455, "b31": 492_971.45}
#: Unrated corporate SA weight, both regimes.
_SA_BORROWER_RW = 1.00
#: Art. 114(3).
_ECB_RW = 0.0
#: Art. 114(1), unrated.
_CENTRAL_BANK_RW = 1.00


def _loan(leg: str, guarantor: str) -> str:
    return f"LN_P358_{leg}_{'ECB' if guarantor == _ECB else 'CB'}"


def _build_bundle() -> RawDataBundle:
    """Two borrowers, two unrated central-bank guarantors, four 50%-guaranteed loans."""
    counterparties = create_p227_counterparties()
    loans = create_p227_loans()
    guarantees = create_p227_guarantees()

    corporate = counterparties.filter(pl.col("counterparty_reference") == CP_B_REF)
    sa_borrower = corporate.with_columns(pl.lit(_SA_BORROWER).alias("counterparty_reference"))
    irb_borrower = counterparties.filter(pl.col("counterparty_reference") == CP_B_IRB_REF)
    guarantors = [
        corporate.with_columns(
            pl.lit(ref).alias("counterparty_reference"),
            pl.lit(entity_type).alias("entity_type"),
            pl.lit(None).cast(pl.String).alias("country_code"),
            pl.lit(None).cast(pl.Float64).alias("annual_revenue"),
            pl.lit(None).cast(pl.Float64).alias("total_assets"),
        )
        for ref, entity_type in _GUARANTORS.items()
    ]

    loan_template = {
        "SA": (loans.filter(pl.col("loan_reference") == LOAN_G2_REF), _SA_BORROWER),
        "IRB": (loans.filter(pl.col("loan_reference") == LOAN_G3_REF), CP_B_IRB_REF),
    }
    guarantee_template = guarantees.filter(pl.col("guarantee_reference") == GUARANTEE_G2_REF)
    new_loans: list[pl.DataFrame] = []
    new_guarantees: list[pl.DataFrame] = []
    for leg, (template, borrower) in loan_template.items():
        for guarantor in _GUARANTORS:
            loan = _loan(leg, guarantor)
            new_loans.append(
                template.with_columns(
                    pl.lit(loan).alias("loan_reference"),
                    pl.lit(borrower).alias("counterparty_reference"),
                )
            )
            new_guarantees.append(
                guarantee_template.with_columns(
                    pl.lit(f"GUAR_{loan}").alias("guarantee_reference"),
                    pl.lit(guarantor).alias("guarantor"),
                    pl.lit(loan).alias("beneficiary_reference"),
                    pl.lit(_COVERED).alias("amount_covered"),
                    pl.lit(_COVERED / _LOAN_EAD).alias("percentage_covered"),
                )
            )

    # Only the F-IRB borrower is rated (internally); the SA borrower and both
    # guarantors are genuinely unrated.
    ratings = create_p227_ratings().filter(pl.col("counterparty_reference") == CP_B_IRB_REF)

    return make_raw_bundle(
        facilities=pl.LazyFrame(
            schema={"facility_reference": pl.String, "counterparty_reference": pl.String}
        ),
        loans=pl.concat(new_loans).lazy(),
        counterparties=pl.concat(
            [sa_borrower, irb_borrower, *guarantors], how="diagonal_relaxed"
        ).lazy(),
        facility_mappings=pl.LazyFrame(
            schema={
                "parent_facility_reference": pl.String,
                "child_reference": pl.String,
                "child_type": pl.String,
            }
        ),
        lending_mappings=pl.LazyFrame(
            schema={
                "parent_counterparty_reference": pl.String,
                "child_counterparty_reference": pl.String,
            }
        ),
        ratings=ratings.lazy(),
        guarantees=pl.concat(new_guarantees).lazy(),
        model_permissions=create_p227_model_permission().lazy(),
    )


@dataclass(frozen=True)
class _Run:
    results: pl.DataFrame
    floor: OutputFloorSummary | None


def _config(regime: str) -> CalculationConfig:
    if regime == "crr":
        return CalculationConfig.crr(
            reporting_date=_REPORTING_DATE, permission_mode=PermissionMode.IRB
        )
    return CalculationConfig.basel_3_1(
        reporting_date=_REPORTING_DATE, permission_mode=PermissionMode.IRB
    )


@pytest.fixture(scope="module")
def runs() -> Iterator[dict[str, _Run]]:
    """One full pipeline run per regime."""
    bundle = _build_bundle()
    out: dict[str, _Run] = {}
    for regime in _REGIMES:
        result = PipelineOrchestrator().run_with_data(bundle, _config(regime))
        assert result.results is not None
        out[regime] = _Run(result.results.collect(), result.output_floor_summary)
    yield out


def _legs(results: pl.DataFrame, loan: str) -> tuple[dict, dict]:
    """The (covered, uncovered) legs of one loan, with adequacy asserted."""
    rows = results.filter(pl.col("parent_exposure_reference") == loan)
    covered = rows.filter(pl.col("guaranteed_portion") > 0)
    uncovered = rows.filter(pl.col("guaranteed_portion").fill_null(0.0) <= 0)
    assert covered.height == 1, f"{loan}: expected one covered leg, got {covered.height}"
    assert uncovered.height == 1, f"{loan}: expected one uncovered leg, got {uncovered.height}"
    covered_row, uncovered_row = covered.row(0, named=True), uncovered.row(0, named=True)
    assert covered_row["ead_final"] == pytest.approx(_COVERED), (
        f"{loan}: the covered leg must carry 500,000 of EAD or the RWEA claims are vacuous"
    )
    assert uncovered_row["ead_final"] == pytest.approx(_LOAN_EAD - _COVERED)
    return covered_row, uncovered_row


@pytest.mark.parametrize("regime", _REGIMES)
def test_sa_loan_ecb_covered_leg_is_zero_weighted(runs: dict[str, _Run], regime: str) -> None:
    """SA: the ECB-covered half carries no RWEA; the loan totals 500,000.

    Pre-fix: guarantor RW 100% = borrower RW, declined; loan RWEA 1,000,000.
    """
    covered, uncovered = _legs(runs[regime].results, _loan("SA", _ECB))

    assert covered["approach_applied"] == "standardised"
    assert covered["guarantor_rw"] == pytest.approx(_ECB_RW, abs=1e-12)
    assert covered["guarantee_status"] == "SA_RW_SUBSTITUTION"
    assert covered["rwa_final"] == pytest.approx(0.0, abs=1e-6), (
        f"{regime}: Art. 114(3) via Art. 235(1) prices the covered leg at 0%; "
        f"got RWEA {covered['rwa_final']:,.2f}"
    )
    assert uncovered["rwa_final"] == pytest.approx(500_000.0, rel=1e-9)


@pytest.mark.parametrize("regime", _REGIMES)
def test_firb_loan_ecb_covered_leg_is_zero_weighted(runs: dict[str, _Run], regime: str) -> None:
    """F-IRB, risk-weight substitution: the ECB-covered leg's RWEA is 0.

    Pre-fix: 500,000 (CRR, substituted at 100%) / 492,971.45 (B31, declined).
    The uncovered leg keeps the borrower's own IRB RWEA either way.
    """
    covered, uncovered = _legs(runs[regime].results, _loan("IRB", _ECB))

    assert covered["approach_applied"] == "foundation_irb"
    assert covered["guarantor_approach"] == "sa"
    assert covered["guarantor_rw"] == pytest.approx(_ECB_RW, abs=1e-12)
    assert covered["guarantee_status"] == "SA_RW_SUBSTITUTION"
    assert covered["rwa_final"] == pytest.approx(0.0, abs=1e-6), (
        f"{regime}: the ECB-covered F-IRB leg should carry no RWEA; got {covered['rwa_final']:,.2f}"
    )
    assert uncovered["rwa_final"] == pytest.approx(_IRB_LEG_RWEA[regime], rel=1e-6)


def test_b31_output_floor_sa_equivalent_of_the_ecb_covered_leg_is_zero(
    runs: dict[str, _Run],
) -> None:
    """Basel 3.1: the floor's SA-equivalent of the ECB-covered F-IRB leg is 0.

    PS1/26 Art. 92(2A) floors U-TREA at a share of S-TREA, the same exposures
    under the SA — including SA credit risk mitigation. Pre-fix: 500,000.
    """
    covered, uncovered = _legs(runs["b31"].results, _loan("IRB", _ECB))

    assert covered["sa_rwa"] == pytest.approx(0.0, abs=1e-6), (
        f"the covered leg's SA-equivalent should be 0 (ECB 0%); got {covered['sa_rwa']:,.2f}"
    )
    assert uncovered["sa_rwa"] == pytest.approx(500_000.0 * _SA_BORROWER_RW, rel=1e-9)


def test_b31_output_floor_totals(runs: dict[str, _Run]) -> None:
    """Basel 3.1 S-TREA and U-TREA over the two F-IRB loans, absolute.

    S-TREA = ECB loan (0 + 500,000) + control loan (500,000 + 500,000) = 1,500,000
    (pre-fix 2,000,000). U-TREA = ECB loan (0 + 492,971.45) + control loan
    (2 x 492,971.45) = 1,478,914.35 (pre-fix 1,971,885.80).
    """
    floor = runs["b31"].floor
    assert floor is not None, "a Basel 3.1 IRB run must publish an output-floor summary"

    assert floor.s_trea == pytest.approx(1_500_000.0, rel=1e-9)
    assert floor.u_trea == pytest.approx(3 * _IRB_LEG_RWEA["b31"], rel=1e-6)


@pytest.mark.parametrize("regime", _REGIMES)
@pytest.mark.parametrize("leg", ["SA", "IRB"])
def test_a_generic_central_bank_guarantor_is_unchanged(
    runs: dict[str, _Run], regime: str, leg: str
) -> None:
    """Control: an unrated non-ECB central bank keeps Art. 114(1)'s 100%.

    This is also the adequacy check for the ECB tests: the two guarantors differ
    only in entity type, so a difference between them is the Art. 114(3) branch.
    """
    covered, _ = _legs(runs[regime].results, _loan(leg, _CENTRAL_BANK))

    assert covered["guarantor_rw"] == pytest.approx(_CENTRAL_BANK_RW, abs=1e-12)
    if leg == "SA":
        expected_rwea = 500_000.0  # declined: 100% is not below the borrower's 100%
    elif regime == "crr":
        expected_rwea = 500_000.0  # substituted at 100% < 117.57% IRB RW
    else:
        expected_rwea = _IRB_LEG_RWEA["b31"]  # declined: 100% is not below 98.59%
    assert covered["rwa_final"] == pytest.approx(expected_rwea, rel=1e-6)
    if regime == "b31" and leg == "IRB":
        assert covered["sa_rwa"] == pytest.approx(500_000.0, rel=1e-9)
