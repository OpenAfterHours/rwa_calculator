"""
P1.259 — PS1/26 Art. 138(1)(g) end to end: the SA risk weight of an institution
exposure is not set by an assessment that incorporates implicit government support.

Pipeline position:
    Loader -> HierarchyResolver (Art. 138 selection / short-term override)
    -> Classifier -> CRMProcessor (guarantor substitution) -> SACalculator

What this pins (Basel 3.1; CRR is the leak detector):
    PS1/26 Art. 138(1)(g), ps126app1.pdf printed pp. 70-71, verbatim:
    "an institution shall not use a credit assessment that incorporates
    assumptions of implicit government support for the purposes of assigning a
    risk weight to an exposure to an institution, unless the respective credit
    assessment applies to an institution owned by or set up and sponsored by
    central governments, regional governments or local authorities."
    UK CRR Art. 138 has limbs (a)-(f) only.

    The limb moves institution weights BOTH ways, so the scenario holds legs of
    each direction (owner sign-off, P1.259):

    - RAISING  — multi-agency (CQS1 flagged x2 + CQS3 clean): ECRA CQS1 -> CQS3.
    - RAISING  — same agency, two long-term rows (a NEWER support-uplifted CQS1
      and an OLDER stand-alone CQS3): ECRA CQS1 -> CQS3. (g) acts before the
      per-agency "most recent" reduction, so the agency's clean assessment is
      used; reducing first would leave the bank unrated (SCRA).
    - RAISING  — sole flagged CQS2, SCRA grade B: ECRA CQS2 -> SCRA B.
    - REDUCING — sole flagged CQS4, SCRA grade A (GBP, so the Art. 121(6)
      foreign-currency sovereign floor stays out): ECRA CQS4 -> SCRA A.
    - REDUCING — short-term: flagged short-term CQS3 beside a clean long-term
      CQS1, 73-day loan: Table 4A CQS3 -> Table 4 CQS1.
    - RAISING  — short-term: flagged short-term CQS1 beside a clean long-term
      CQS4: Table 4A CQS1 -> Table 4 CQS4.
    - PROPAGATION — an unrated corporate guaranteed in full by the multi-agency
      bank: the substituted weight is the guarantor's, so it moves with it.
    - EXEMPT — the multi-agency ratings on a government-owned / sponsored bank.
    - OUT OF SCOPE — a corporate with a flagged CQS1.

    A second run grants an institution F-IRB model permission (PermissionMode.IRB):

    - OUT OF SCOPE — an INTERNAL rating flagged True. Art. 138 governs ECAI
      credit assessments only, so the bank keeps its internal PD and model id
      and stays on F-IRB in both regimes.
    - OUTPUT FLOOR (REDUCING, LESSONS D1) — an F-IRB bank whose only external
      assessment (CQS4) is flagged, SCRA grade A: the SA-equivalent the Basel
      3.1 output floor reads (``sa_rwa``) falls from ECRA CQS4 to SCRA A.

Every expected weight is read from the regime's resolved rulepack, never typed.

References:
- PS1/26 Art. 138(1)(g); Art. 120(2), (2B) Tables 4 / 4A; Art. 120A / 121 SCRA
- PS1/26 Art. 235: guarantee substitution
- PS1/26 Art. 92(2A) / 92(3A): output floor S-TREA (SA-equivalent of modelled exposures)
- CRR Art. 120 Table 3; Art. 131 Table 7
"""

from __future__ import annotations

import functools
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import polars as pl
import pytest

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.contracts.config import CalculationConfig, PermissionMode
from rwa_calc.domain.enums import ApproachType
from rwa_calc.engine.pipeline import PipelineOrchestrator
from rwa_calc.rulebook.resolve import ResolvedRulepack, resolve
from tests.fixtures.raw_bundle import make_raw_bundle

_REPORTING_DATE = date(2027, 1, 31)
_VALUE_DATE = date(2027, 1, 1)
_SHORT_MATURITY = date(2027, 3, 15)  # 73 days: inside the Art. 120(2) / (2B) window
_LONG_MATURITY = date(2030, 1, 1)
_RATING_DATE = date(2027, 1, 2)
_OLDER_RATING_DATE = date(2026, 12, 1)
_DRAWN = 1_000_000.0

_CP_MULTI = "CP259A_BANK_MULTI"
_CP_SAME_AGENCY = "CP259A_BANK_SAME_AGENCY"
_CP_SCRA_B = "CP259A_BANK_SCRA_B"
_CP_SCRA_A = "CP259A_BANK_SCRA_A"
_CP_ST_DOWN = "CP259A_BANK_ST_DOWN"
_CP_ST_UP = "CP259A_BANK_ST_UP"
_CP_GOV = "CP259A_BANK_GOV"
_CP_CORP = "CP259A_CORP_FLAGGED"
_CP_BORROWER = "CP259A_CORP_BORROWER"

_LOAN_GUARANTEED = f"LN_{_CP_BORROWER}"

# --- IRB run: one institution F-IRB model, two banks rated by it ---
_CP_IRB_INTERNAL = "CP259A_BANK_IRB_INTERNAL"  # internal rating flagged True + clean CQS2
_CP_IRB_FLOOR = "CP259A_BANK_IRB_FLOOR"  # clean internal + flagged CQS4 only, SCRA A
_MODEL_FIRB = "M259A_INST_FIRB"
_INTERNAL_PD = 0.004


@dataclass(frozen=True)
class _Run:
    """One regime's SA output and resolved pack."""

    regime: str
    pack: ResolvedRulepack
    sa: pl.DataFrame


@pytest.fixture(scope="module", params=["crr", "b31"])
def run(request: pytest.FixtureRequest) -> _Run:
    """Run the P1.259 bundle once per regime through the full SA pipeline."""
    regime: str = request.param
    config = _config(regime)

    result = PipelineOrchestrator().run_with_data(_bundle(), config)

    assert result.sa_results is not None, f"{regime}: SA results missing"
    return _Run(
        regime=regime, pack=resolve(regime, _REPORTING_DATE), sa=result.sa_results.collect()
    )


def _expected_rw(run: _Run, counterparty: str) -> Decimal:
    """The pack weight each leg must carry, per regime."""
    p = run.pack
    if run.regime == "crr":
        crr = {
            _CP_MULTI: p.lookup("institution_rw_crr").entries[1],
            _CP_SAME_AGENCY: p.lookup("institution_rw_crr").entries[1],
            _CP_SCRA_B: p.lookup("institution_rw_crr").entries[2],
            _CP_SCRA_A: p.lookup("institution_rw_crr").entries[4],
            _CP_ST_DOWN: p.lookup("crr_short_term_ecai_risk_weights").entries[3],
            _CP_ST_UP: p.lookup("crr_short_term_ecai_risk_weights").entries[1],
            _CP_GOV: p.lookup("institution_rw_crr").entries[1],
            _CP_CORP: p.lookup("corporate_risk_weights").entries[1],
        }
        return crr[counterparty]
    b31 = {
        _CP_MULTI: p.lookup("institution_rw_b31_ecra").entries[3],
        _CP_SAME_AGENCY: p.lookup("institution_rw_b31_ecra").entries[3],
        _CP_SCRA_B: p.lookup("b31_scra_risk_weights").entries["B"],
        _CP_SCRA_A: p.lookup("b31_scra_risk_weights").entries["A"],
        _CP_ST_DOWN: p.lookup("b31_ecra_short_term_risk_weights").entries[1],
        _CP_ST_UP: p.lookup("b31_ecra_short_term_risk_weights").entries[4],
        _CP_GOV: p.lookup("institution_rw_b31_ecra").entries[1],
        _CP_CORP: p.lookup("b31_corporate_risk_weights").entries[1],
    }
    return b31[counterparty]


_DIRECT_LEGS = (
    _CP_MULTI,
    _CP_SAME_AGENCY,
    _CP_SCRA_B,
    _CP_SCRA_A,
    _CP_ST_DOWN,
    _CP_ST_UP,
    _CP_GOV,
    _CP_CORP,
)


def test_p1_259_scenario_legs_move_in_both_directions_under_b31() -> None:
    """Adequacy: the B31 legs include a raising AND a reducing one, or one direction is untested.

    Compares the B31 expectation with what the same assessment would give had
    (g) not been applied — both read from the pack.
    """
    # Arrange
    b31 = resolve("b31", _REPORTING_DATE)
    ecra = b31.lookup("institution_rw_b31_ecra").entries
    table_4a = b31.lookup("b31_ecra_short_term_ecai_risk_weights").entries
    scra = b31.lookup("b31_scra_risk_weights").entries
    table_4 = b31.lookup("b31_ecra_short_term_risk_weights").entries

    # Act
    moves = {
        _CP_MULTI: ecra[3] - ecra[1],
        _CP_SAME_AGENCY: ecra[3] - ecra[1],
        _CP_SCRA_B: scra["B"] - ecra[2],
        _CP_SCRA_A: scra["A"] - ecra[4],
        _CP_ST_DOWN: table_4[1] - table_4a[3],
        _CP_ST_UP: table_4[4] - table_4a[1],
    }

    # Assert
    assert any(m > 0 for m in moves.values()), f"no RWA-raising leg: {moves}"
    assert any(m < 0 for m in moves.values()), f"no RWA-reducing leg: {moves}"
    assert all(m != 0 for m in moves.values()), f"a leg that does not move proves nothing: {moves}"


@pytest.mark.parametrize("counterparty", _DIRECT_LEGS)
def test_p1_259_institution_risk_weight_disregards_implicit_support_assessments(
    run: _Run, counterparty: str
) -> None:
    """Each leg's SA risk weight is the pack weight of the assessment Art. 138 may use."""
    # Arrange
    expected = float(_expected_rw(run, counterparty))

    # Act
    row = _row(run, f"LN_{counterparty}")

    # Assert
    assert row["risk_weight"] == pytest.approx(expected, abs=1e-9), (
        f"{run.regime}: {counterparty} risk_weight expected {expected:.2%}, "
        f"got {row['risk_weight']:.2%} (cqs={row['cqs']!r})"
    )
    assert row["rwa_final"] == pytest.approx(_DRAWN * expected, rel=1e-9), (
        f"{run.regime}: {counterparty} rwa_final expected {_DRAWN * expected:,.0f}, "
        f"got {row['rwa_final']:,.0f}"
    )


def test_p1_259_guarantor_substitution_uses_the_guarantors_disregarded_rating(run: _Run) -> None:
    """The guaranteed leg takes the guarantor's weight — after (g) under B31, before it under CRR.

    Under substitution the risk weight is that of an exposure to the
    guarantor (Art. 235), so (g) bites on the guarantor's assessments too.
    """
    # Arrange
    legs = run.sa.filter(
        pl.col("exposure_reference").str.starts_with(_LOAN_GUARANTEED)
        & (pl.col("guaranteed_portion").fill_null(0.0) > 0)
    )
    assert legs.height == 1, f"{run.regime}: expected one guaranteed leg, got {legs.height}"
    expected = float(_expected_rw(run, _CP_MULTI))
    expected_cqs = 1 if run.regime == "crr" else 3

    # Act
    leg = legs.row(0, named=True)

    # Assert
    assert leg["guarantor_cqs"] == expected_cqs, (
        f"{run.regime}: guarantor_cqs expected {expected_cqs}, got {leg['guarantor_cqs']!r}"
    )
    assert leg["risk_weight"] == pytest.approx(expected, abs=1e-9), (
        f"{run.regime}: guaranteed-leg risk_weight expected {expected:.2%}, "
        f"got {leg['risk_weight']:.2%}"
    )


@dataclass(frozen=True)
class _IrbRun:
    """One regime's aggregated output of the IRB-permissioned run."""

    regime: str
    pack: ResolvedRulepack
    results: pl.DataFrame


@pytest.fixture(scope="module", params=["crr", "b31"])
def irb_run(request: pytest.FixtureRequest) -> _IrbRun:
    """Run the IRB-permissioned bundle once per regime through the full pipeline."""
    return _run_irb(request.param)


def test_p1_259_flagged_internal_rating_keeps_the_irb_model_route(irb_run: _IrbRun) -> None:
    """A flagged INTERNAL rating is not disregarded: the bank stays on F-IRB with its own PD.

    Art. 138(1)(g) reaches a "credit assessment" — an ECAI's. Dropping the
    internal row would strip the model id the permission routes on, sending
    the exposure to SA without any error.
    """
    # Arrange
    regime = irb_run.regime

    # Act
    row = _result_row(irb_run, f"LN_{_CP_IRB_INTERNAL}")

    # Assert
    got = (row["approach_applied"], row["pd"])
    assert got == (ApproachType.FIRB.value, _INTERNAL_PD), (
        f"{regime}: {_CP_IRB_INTERNAL} (approach_applied, pd) expected "
        f"{(ApproachType.FIRB.value, _INTERNAL_PD)}, got {got}"
    )


def test_p1_259_irb_bank_carries_the_disregarded_external_cqs(irb_run: _IrbRun) -> None:
    """The F-IRB bank's flagged CQS4 is disregarded under B31 and kept under CRR."""
    # Arrange
    expected_cqs = 4 if irb_run.regime == "crr" else None

    # Act
    row = _result_row(irb_run, f"LN_{_CP_IRB_FLOOR}")

    # Assert
    assert row["approach_applied"] == ApproachType.FIRB.value, (
        f"{irb_run.regime}: {_CP_IRB_FLOOR} must be F-IRB, got {row['approach_applied']!r}"
    )
    assert row["cqs"] == expected_cqs, (
        f"{irb_run.regime}: {_CP_IRB_FLOOR} cqs expected {expected_cqs!r}, got {row['cqs']!r}"
    )


def test_p1_259_output_floor_sa_equivalent_uses_scra_after_disregard() -> None:
    """B31: the F-IRB bank's SA-equivalent (``sa_rwa``) is SCRA A, not the flagged ECRA CQS4.

    The SA branch runs for IRB rows too, so the S-TREA leg of the output floor
    reads the hierarchy ``cqs`` (LESSONS D1). With its only assessment
    disregarded the bank is unrated and weighted by its SCRA grade — the
    RWA-REDUCING direction the owner signed off. CRR has no output floor.
    """
    # Arrange
    b31 = _run_irb("b31")
    scra_a = b31.pack.lookup("b31_scra_risk_weights").entries["A"]
    ecra_cqs4 = b31.pack.lookup("institution_rw_b31_ecra").entries[4]
    assert scra_a != ecra_cqs4, "adequacy: the two weights must differ, or the leg cannot fail"
    expected = _DRAWN * float(scra_a)

    # Act
    row = _result_row(b31, f"LN_{_CP_IRB_FLOOR}")

    # Assert
    assert row["sa_rwa"] == pytest.approx(expected, rel=1e-9), (
        f"b31: {_CP_IRB_FLOOR} sa_rwa expected {expected:,.0f} (SCRA A), got "
        f"{row['sa_rwa']:,.0f} — {_DRAWN * float(ecra_cqs4):,.0f} is the flagged ECRA CQS4"
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _config(
    regime: str, permission_mode: PermissionMode = PermissionMode.STANDARDISED
) -> CalculationConfig:
    """Config for the regime (SA-only unless a permission mode is given)."""
    if regime == "crr":
        return CalculationConfig.crr(
            reporting_date=_REPORTING_DATE, permission_mode=permission_mode
        )
    return CalculationConfig.basel_3_1(
        reporting_date=_REPORTING_DATE, permission_mode=permission_mode
    )


@functools.cache
def _run_irb(regime: str) -> _IrbRun:
    """Run the IRB-permissioned bundle through PipelineOrchestrator (once per regime)."""
    result = PipelineOrchestrator().run_with_data(
        _irb_bundle(), _config(regime, PermissionMode.IRB)
    )
    return _IrbRun(
        regime=regime,
        pack=resolve(regime, _REPORTING_DATE),
        results=result.results.collect(),
    )


def _irb_bundle() -> RawDataBundle:
    """Two banks rated by one institution F-IRB model, each with one loan."""
    counterparties = pl.DataFrame(
        [
            _counterparty(_CP_IRB_INTERNAL, "bank"),
            _counterparty(_CP_IRB_FLOOR, "bank", scra_grade="A"),
        ]
    )
    loans = pl.DataFrame([_loan(cp, _LONG_MATURITY) for cp in (_CP_IRB_INTERNAL, _CP_IRB_FLOOR)])
    ratings = pl.DataFrame(
        [
            _internal_rating(_CP_IRB_INTERNAL, flagged=True),
            _rating(_CP_IRB_INTERNAL, "MOODYS", 2, flagged=False),
            _internal_rating(_CP_IRB_FLOOR, flagged=None),
            _rating(_CP_IRB_FLOOR, "MOODYS", 4, flagged=True),
        ],
        schema_overrides={
            "cqs": pl.Int8,
            "pd": pl.Float64,
            "model_id": pl.String,
            "rating_incorporates_government_support": pl.Boolean,
        },
    )
    model_permissions = pl.DataFrame(
        [{"model_id": _MODEL_FIRB, "exposure_class": "institution", "approach": "foundation_irb"}]
    )
    return make_raw_bundle(
        facilities=pl.LazyFrame(
            schema={"facility_reference": pl.String, "counterparty_reference": pl.String}
        ),
        loans=loans,
        counterparties=counterparties,
        facility_mappings=pl.LazyFrame(
            schema={
                "parent_facility_reference": pl.String,
                "child_reference": pl.String,
                "child_type": pl.String,
            }
        ),
        ratings=ratings,
        model_permissions=model_permissions,
    )


def _bundle() -> RawDataBundle:
    """Nine obligors, one loan each, and one full guarantee by the multi-agency bank."""
    counterparties = pl.DataFrame(
        [
            _counterparty(_CP_MULTI, "bank"),
            _counterparty(_CP_SAME_AGENCY, "bank"),
            _counterparty(_CP_SCRA_B, "bank", scra_grade="B"),
            _counterparty(_CP_SCRA_A, "bank", scra_grade="A"),
            _counterparty(_CP_ST_DOWN, "bank"),
            _counterparty(_CP_ST_UP, "bank"),
            _counterparty(_CP_GOV, "bank", government_owned=True),
            _counterparty(_CP_CORP, "corporate"),
            _counterparty(_CP_BORROWER, "corporate"),
        ]
    )
    short_term = {_CP_ST_DOWN, _CP_ST_UP}
    loans = pl.DataFrame(
        [
            _loan(cp, _SHORT_MATURITY if cp in short_term else _LONG_MATURITY)
            for cp in (*_DIRECT_LEGS, _CP_BORROWER)
        ]
    )
    ratings = pl.DataFrame(
        [
            _rating(_CP_MULTI, "MOODYS", 1, flagged=True),
            _rating(_CP_MULTI, "SP", 1, flagged=True),
            _rating(_CP_MULTI, "FITCH", 3, flagged=False),
            _rating(_CP_SAME_AGENCY, "MOODYS", 1, flagged=True, tag="SUPPORT"),
            _rating(
                _CP_SAME_AGENCY,
                "MOODYS",
                3,
                flagged=False,
                rating_date=_OLDER_RATING_DATE,
                tag="STANDALONE",
            ),
            _rating(_CP_SCRA_B, "MOODYS", 2, flagged=True),
            _rating(_CP_SCRA_A, "MOODYS", 4, flagged=True),
            _rating(_CP_ST_DOWN, "MOODYS", 1, flagged=False),
            _rating(_CP_ST_DOWN, "MOODYS", 3, flagged=True, short_term=True),
            _rating(_CP_ST_UP, "MOODYS", 4, flagged=False),
            _rating(_CP_ST_UP, "MOODYS", 1, flagged=True, short_term=True),
            _rating(_CP_GOV, "MOODYS", 1, flagged=True),
            _rating(_CP_GOV, "SP", 1, flagged=True),
            _rating(_CP_GOV, "FITCH", 3, flagged=False),
            _rating(_CP_CORP, "MOODYS", 1, flagged=True),
        ],
        schema_overrides={"rating_incorporates_government_support": pl.Boolean},
    )
    guarantees = pl.DataFrame(
        [
            {
                "guarantee_reference": "GTE_P1259",
                "guarantee_type": "guarantee",
                "guarantor": _CP_MULTI,
                "currency": "GBP",
                "maturity_date": date(2030, 12, 31),
                "amount_covered": _DRAWN,
                "beneficiary_type": "loan",
                "beneficiary_reference": _LOAN_GUARANTEED,
                "protection_type": "guarantee",
                "includes_restructuring": True,
            }
        ]
    )
    return make_raw_bundle(
        facilities=pl.LazyFrame(
            schema={"facility_reference": pl.String, "counterparty_reference": pl.String}
        ),
        loans=loans,
        counterparties=counterparties,
        facility_mappings=pl.LazyFrame(
            schema={
                "parent_facility_reference": pl.String,
                "child_reference": pl.String,
                "child_type": pl.String,
            }
        ),
        ratings=ratings,
        guarantees=guarantees,
    )


def _counterparty(
    reference: str,
    entity_type: str,
    *,
    government_owned: bool = False,
    scra_grade: str | None = None,
) -> dict[str, object]:
    return {
        "counterparty_reference": reference,
        "counterparty_name": reference,
        "entity_type": entity_type,
        "country_code": "GB",
        "local_currency": "GBP",
        "annual_revenue": 100_000_000.0,
        "total_assets": 100_000_000.0,
        "scra_grade": scra_grade,
        "is_government_owned_or_sponsored": government_owned,
    }


def _loan(counterparty: str, maturity: date) -> dict[str, object]:
    return {
        "loan_reference": f"LN_{counterparty}",
        "counterparty_reference": counterparty,
        "currency": "GBP",
        "value_date": _VALUE_DATE,
        "maturity_date": maturity,
        "drawn_amount": _DRAWN,
        "interest": 0.0,
        "seniority": "senior",
    }


def _rating(
    counterparty: str,
    agency: str,
    cqs: int,
    *,
    flagged: bool | None,
    short_term: bool = False,
    rating_date: date = _RATING_DATE,
    tag: str = "",
) -> dict[str, object]:
    suffix = "ST" if short_term else "LT"
    return {
        "rating_reference": f"RTG_{counterparty}_{agency}_{suffix}{tag}",
        "counterparty_reference": counterparty,
        "rating_type": "external",
        "rating_agency": agency,
        "rating_value": f"cqs{cqs}",
        "cqs": cqs,
        "rating_date": rating_date,
        "is_solicited": True,
        "is_short_term": short_term,
        "scope_type": "loan" if short_term else None,
        "scope_id": f"LN_{counterparty}" if short_term else None,
        "rating_incorporates_government_support": flagged,
    }


def _internal_rating(counterparty: str, *, flagged: bool | None) -> dict[str, object]:
    return {
        "rating_reference": f"RTG_{counterparty}_INTERNAL",
        "counterparty_reference": counterparty,
        "rating_type": "internal",
        "rating_agency": None,
        "rating_value": None,
        "cqs": None,
        "pd": _INTERNAL_PD,
        "model_id": _MODEL_FIRB,
        "rating_date": _RATING_DATE,
        "is_solicited": True,
        "is_short_term": False,
        "scope_type": None,
        "scope_id": None,
        "rating_incorporates_government_support": flagged,
    }


def _result_row(run: _IrbRun, exposure_reference: str) -> dict[str, object]:
    rows = run.results.filter(pl.col("exposure_reference") == exposure_reference).to_dicts()
    assert len(rows) == 1, (
        f"{run.regime}: expected one result row for {exposure_reference}, got {len(rows)}"
    )
    return rows[0]


def _row(run: _Run, exposure_reference: str) -> dict[str, object]:
    rows = run.sa.filter(pl.col("exposure_reference") == exposure_reference).to_dicts()
    assert len(rows) == 1, (
        f"{run.regime}: expected one row for {exposure_reference}, got {len(rows)}"
    )
    return rows[0]
