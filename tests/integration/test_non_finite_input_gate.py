"""
Integration — non-finite raw inputs are gated at the pipeline entry (DQ011).

End-to-end reproduction of the reported failure mode: an IRB borrower
guaranteed by a standardised (SA) counterparty whose guarantee/loan/rating
inputs carry NaN. Pre-gate, the NaN flowed through the CRM guarantee split
into ``rwa_final`` on the ``__G_``/``__REM`` legs (AGG001 — "excluded from
portfolio totals"), and under Basel 3.1 the portfolio output floor spread the
NaN to EVERY row's ``rwa_final``.

Post-gate contract, both regimes:
- every non-finite input value is nulled at entry and surfaced as DQ011;
- no AGG001/AGG002 fires — every ``rwa_final``/``ead_final``/``risk_weight``
  in the results frame is finite;
- the healthy guaranteed exposure still receives Art. 235 RWSM substitution
  (guarantor CQS 2 corporate -> 50% RW);
- the by-class/by-approach summary totals stay finite.

References:
- CRR Art. 213/235: guarantee substitution (the healthy-leg pin)
- PRA PS1/26 Art. 92 para 2A: portfolio output floor (the B31 blast radius)
- contracts/validation.py::scrub_non_finite_values (the gate under test)
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig, PermissionMode
from rwa_calc.contracts.errors import ERROR_NON_FINITE_RAW_INPUT
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import (
    COUNTERPARTY_SCHEMA,
    FACILITY_MAPPING_SCHEMA,
    GUARANTEE_SCHEMA,
    LENDING_MAPPING_SCHEMA,
    LOAN_SCHEMA,
    MODEL_PERMISSIONS_SCHEMA,
    RATINGS_SCHEMA,
)
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.fixtures.raw_bundle import make_raw_bundle

NAN = float("nan")
VALUE_DATE = date(2025, 1, 2)
MATURITY_DATE = date(2030, 1, 2)


def _cp(ref: str, entity_type: str = "company") -> dict:
    return {
        "counterparty_reference": ref,
        "counterparty_name": ref,
        "entity_type": entity_type,
        "country_code": "GB",
        "annual_revenue": 100_000_000.0,
        "default_status": False,
    }


def _loan(ref: str, cp: str, drawn: float, eff_m: float = 5.0) -> dict:
    return {
        "loan_reference": ref,
        "product_type": "term_loan",
        "book_code": "BOOK",
        "counterparty_reference": cp,
        "value_date": VALUE_DATE,
        "maturity_date": MATURITY_DATE,
        "currency": "GBP",
        "drawn_amount": drawn,
        "interest": 0.0,
        "seniority": "senior",
        "effective_maturity": eff_m,
    }


def _gte(ref: str, loan_ref: str, amount: float | None, pct: float | None) -> dict:
    return {
        "guarantee_reference": ref,
        "guarantee_type": "guarantee",
        "guarantor": "CP_GUARANTOR",
        "currency": "GBP",
        "maturity_date": MATURITY_DATE,
        "amount_covered": amount,
        "percentage_covered": pct,
        "beneficiary_type": "loan",
        "beneficiary_reference": loan_ref,
        "protection_type": "guarantee",
        "includes_restructuring": True,
        "original_maturity_years": 5.0,
        "guarantor_seniority": "senior",
    }


def _rating(ref: str, cp: str, *, pd: float | None, cqs: int | None, model: str | None) -> dict:
    return {
        "rating_reference": ref,
        "counterparty_reference": cp,
        "rating_type": "internal" if model else "external",
        "rating_agency": "internal" if model else "Moody's",
        "rating_value": "BB",
        "cqs": cqs,
        "pd": pd,
        "rating_date": VALUE_DATE,
        "is_solicited": model is None,
        "model_id": model,
    }


def _build_bundle():
    """FIRB borrowers + SA guarantor; NaN in guarantee, maturity, and PD inputs."""
    counterparties = pl.DataFrame(
        [
            _cp("CP_BORROWER"),
            _cp("CP_BORROWER_PDNAN"),
            _cp("CP_GUARANTOR"),
        ],
        schema=dtypes_of(COUNTERPARTY_SCHEMA),
    )
    loans = pl.DataFrame(
        [
            _loan("L_CLEAN", "CP_BORROWER", 1_000_000.0),
            _loan("L_NAN_GTE", "CP_BORROWER", 1_000_000.0),
            _loan("L_NAN_MAT", "CP_BORROWER", 1_000_000.0, eff_m=NAN),
            _loan("L_NAN_PD", "CP_BORROWER_PDNAN", 1_000_000.0),
        ],
        schema=dtypes_of(LOAN_SCHEMA),
    )
    guarantees = pl.DataFrame(
        [
            _gte("G_CLEAN", "L_CLEAN", 1_000_000.0, 1.0),
            _gte("G_NAN", "L_NAN_GTE", NAN, None),
            _gte("G_MAT", "L_NAN_MAT", 1_000_000.0, 1.0),
            _gte("G_PD", "L_NAN_PD", 1_000_000.0, 1.0),
        ],
        schema=dtypes_of(GUARANTEE_SCHEMA),
    )
    ratings = pl.DataFrame(
        [
            _rating("R_B", "CP_BORROWER", pd=0.02, cqs=None, model="MODEL_FIRB"),
            _rating("R_BPD", "CP_BORROWER_PDNAN", pd=NAN, cqs=None, model="MODEL_FIRB"),
            _rating("R_G", "CP_GUARANTOR", pd=None, cqs=2, model=None),
        ],
        schema=dtypes_of(RATINGS_SCHEMA),
    )
    model_permissions = pl.DataFrame(
        [
            {
                "model_id": "MODEL_FIRB",
                "exposure_class": "corporate",
                "approach": "foundation_irb",
                "country_codes": None,
                "excluded_book_codes": None,
            }
        ],
        schema=dtypes_of(MODEL_PERMISSIONS_SCHEMA),
    )
    return make_raw_bundle(
        loans=loans.lazy(),
        counterparties=counterparties.lazy(),
        facility_mappings=pl.LazyFrame(schema=dtypes_of(FACILITY_MAPPING_SCHEMA)),
        lending_mappings=pl.LazyFrame(schema=dtypes_of(LENDING_MAPPING_SCHEMA)),
        guarantees=guarantees.lazy(),
        ratings=ratings.lazy(),
        model_permissions=model_permissions.lazy(),
    )


@pytest.fixture(scope="module")
def crr_result():
    config = CalculationConfig.crr(
        reporting_date=date(2025, 12, 31), permission_mode=PermissionMode.IRB
    )
    return PipelineOrchestrator().run_with_data(_build_bundle(), config)


@pytest.fixture(scope="module")
def b31_result():
    config = CalculationConfig.basel_3_1(
        reporting_date=date(2027, 6, 30), permission_mode=PermissionMode.IRB
    )
    return PipelineOrchestrator().run_with_data(_build_bundle(), config)


def _assert_outputs_finite(result) -> None:
    df = result.results.collect()
    for col in ("rwa_final", "ead_final", "risk_weight"):
        bad = df.filter((~pl.col(col).is_finite()).fill_null(value=False))
        refs = bad.get_column("exposure_reference").to_list()
        assert not refs, f"non-finite {col} for {refs}"


class TestGateUnderCRR:
    def test_dq011_flags_every_poisoned_input(self, crr_result) -> None:
        """One DQ011 per affected input column, naming table and column."""
        dq011 = [e for e in crr_result.errors if e.code == ERROR_NON_FINITE_RAW_INPUT]
        by_field = {e.field_name: e for e in dq011}
        assert {"amount_covered", "effective_maturity", "pd"} <= set(by_field)
        assert "guarantees" in by_field["amount_covered"].message
        assert "loans" in by_field["effective_maturity"].message
        assert "ratings" in by_field["pd"].message

    def test_no_agg001_or_agg002(self, crr_result) -> None:
        """The aggregator net stays silent — nothing non-finite reaches it."""
        codes = {e.code for e in crr_result.errors}
        assert "AGG001" not in codes
        assert "AGG002" not in codes

    def test_all_final_outputs_finite(self, crr_result) -> None:
        _assert_outputs_finite(crr_result)

    def test_healthy_guaranteed_leg_still_substitutes(self, crr_result) -> None:
        """Art. 235 RWSM on the clean leg: CQS2 corporate guarantor -> 50%, 500k."""
        df = crr_result.results.collect()
        leg = df.filter(pl.col("exposure_reference") == "L_CLEAN__G_CP_GUARANTOR")
        assert leg.height == 1
        assert leg.get_column("rwa_final")[0] == pytest.approx(500_000.0, rel=1e-9)

    def test_summary_totals_finite(self, crr_result) -> None:
        summary = crr_result.summary_by_class.collect()
        assert summary.get_column("total_ead").is_finite().all()
        assert summary.get_column("total_rwa").is_finite().all()


class TestGateUnderB31:
    """The B31 arm additionally pins the output floor: no portfolio-wide NaN."""

    def test_no_agg001(self, b31_result) -> None:
        codes = {e.code for e in b31_result.errors}
        assert "AGG001" not in codes, (
            "one poisoned input must not blank the whole B31 portfolio via the floor"
        )

    def test_all_final_outputs_finite(self, b31_result) -> None:
        _assert_outputs_finite(b31_result)

    def test_floor_summary_finite(self, b31_result) -> None:
        import math

        summary = b31_result.output_floor_summary
        assert summary is not None
        for field in ("u_trea", "s_trea", "shortfall", "total_rwa_post_floor"):
            assert math.isfinite(getattr(summary, field)), f"{field} must stay finite"

    def test_healthy_guaranteed_leg_still_substitutes(self, b31_result) -> None:
        df = b31_result.results.collect()
        leg = df.filter(pl.col("exposure_reference") == "L_CLEAN__G_CP_GUARANTOR")
        assert leg.height == 1
        assert leg.get_column("rwa_final")[0] == pytest.approx(500_000.0, rel=1e-9)
