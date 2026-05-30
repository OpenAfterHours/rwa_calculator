"""
P1.94b — B31 Art. 123B(2): hedge_coverage_ratio below 0.90 threshold fires multiplier.

Acceptance scenario verifying that the 1.5x Art. 123B currency-mismatch multiplier
fires when is_hedged=False AND hedge_coverage_ratio is below the 0.90 Art. 123B(2)
partial-hedge threshold.

Pipeline position:
    SACalculator.apply_currency_mismatch_multiplier  (namespace.py)

Scenario design:
    Single arm: retail_other EUR-denominated loan, natural-person borrower,
    GBP income currency, EAD = EUR 100,000.
        - is_hedged=False (hedge gate is open)
        - hedge_coverage_ratio=0.85 (below 0.90 Art. 123B(2) threshold)
          → partial hedge is insufficient → Art. 123B multiplier fires

    Arm (P194B_PARTIAL_HEDGE):
        Base SA retail RW = 75%  (PRA PS1/26 Art. 123(1))
        is_hedged=False + currency mismatch (EUR vs GBP income)
            → hedge gate is open
        hedge_coverage_ratio=0.85 < 0.90 Art. 123B(2) threshold
            → partial hedge insufficient → Art. 123B multiplier fires: 1.5 × 75% = 112.5%
        Expected: risk_weight ≈ 1.125, rwa ≈ 112,500,
                  currency_mismatch_multiplier_applied = True

Schema contract test (load-bearing failing assertion for engine-implementer Wave 4):
    LOAN_SCHEMA must include hedge_coverage_ratio as pl.Float64 AFTER the engine fix.
    Pre-fix (current): hedge_coverage_ratio is NOT in LOAN_SCHEMA.
    Post-fix: engine-implementer adds it to LOAN_SCHEMA in Wave 4.

Pre-fix failure modes (Wave 3):
    1. test_loan_schema_includes_hedge_coverage_ratio: AssertionError —
       "hedge_coverage_ratio" not in LOAN_SCHEMA (schema not yet extended).
    2. test_b31_retail_partial_hedge_below_90pct_fires_currency_mismatch_multiplier:
       May pass if P1.94a's is_hedged=False arm already fires the multiplier
       unconditionally (the multiplier fires regardless of hedge_coverage_ratio).
       If the engine does NOT yet check hedge_coverage_ratio, this behavioural test
       may pass by accident — but the schema test provides the load-bearing failure.

References:
    - PRA PS1/26 Art. 123(1): retail non-mortgage SA risk weight = 75%.
    - PRA PS1/26 Art. 123B: 1.5x currency-mismatch multiplier for retail exposures
      where loan currency != borrower income currency AND is_hedged = False.
    - PRA PS1/26 Art. 123B(2): hedge must cover >= 90% of the notional to qualify
      as a full hedge that suppresses the multiplier.
    - BCBS CRE20.89-93: currency mismatch add-on for unhedged/partially-hedged FX retail.
    - tests/fixtures/p1_94b/p1_94b.py: fixture constants and bundle builder.
    - tests/acceptance/basel31/test_p1_94a_is_hedged_gates_currency_mismatch.py:
      sibling scenario for is_hedged boolean gate.
"""

from __future__ import annotations

from datetime import date
from typing import cast

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig, PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.fixtures.p1_94b.p1_94b import (
    CURRENCY_MISMATCH_MULTIPLIER,
    HEDGE_COVERAGE_RATIO,
    HEDGE_COVERAGE_THRESHOLD,
    LOAN_REF,
    RW_PARTIAL_HEDGE,
    RWA_PARTIAL_HEDGE,
    SA_RETAIL_BASE_RW,
    load_p1_94b_bundle,
)

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

_REPORTING_DATE = date(2027, 1, 4)

# Absolute tolerances
_RW_TOL = 1e-6  # risk_weight (dimensionless ratio)
_RWA_TOL = 0.50  # £0.50 on rwa_final
_EAD_TOL = 0.50  # £0.50 on ead_final

# Expected EAD (drawn amount from fixture)
_EAD = 100_000.0

# Expected exposure class
_EXPOSURE_CLASS = "retail_other"


# ---------------------------------------------------------------------------
# Module-scoped Basel 3.1 config
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def b31_config() -> CalculationConfig:
    """Basel 3.1 SA-only config with 2027-01-04 reporting date (post-effective date).

    enforce_retail_granularity=False so the single-obligor currency-mismatch
    fixture keeps its retail_other classification — the Art. 123A(1)(b)(ii) 0.2%
    granularity limb (P5.15) is out of scope here and is covered by test_p5_15_*.
    """
    return CalculationConfig.basel_3_1(
        reporting_date=_REPORTING_DATE,
        permission_mode=PermissionMode.STANDARDISED,
        enforce_retail_granularity=False,
    )


# ---------------------------------------------------------------------------
# Module-scoped pipeline results
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def p1_94b_sa_results(b31_config: CalculationConfig) -> pl.DataFrame:
    """
    Run P1.94b bundle through the Basel 3.1 SA pipeline and return SA results.

    Arrange: 1 counterparty (natural person, GB, borrower_income_currency=GBP),
             1 loan (P194B_PARTIAL_HEDGE, EUR 100,000, is_hedged=False,
             hedge_coverage_ratio=0.85). B31 SA-only config, 2027-01-04.
    Act:     PipelineOrchestrator().run_with_data(bundle, config).sa_results.
    Return:  Collected SA results DataFrame for all test assertions.
    """
    bundle = load_p1_94b_bundle()
    results = PipelineOrchestrator().run_with_data(bundle, b31_config)
    assert results.sa_results is not None, (
        "SA results should not be None — check PermissionMode.STANDARDISED config "
        "and that the bundle contains a valid loan row."
    )
    return cast(pl.DataFrame, results.sa_results.collect())


@pytest.fixture(scope="module")
def p194b_row(p1_94b_sa_results: pl.DataFrame) -> dict:
    """
    Return the single SA result row for P194B_PARTIAL_HEDGE.

    Filters on exposure_reference == LOAN_REF (P194B_PARTIAL_HEDGE).
    Asserts exactly one row is returned so all downstream tests operate on
    a single well-defined result.
    """
    rows = p1_94b_sa_results.filter(pl.col("exposure_reference") == LOAN_REF).to_dicts()
    assert len(rows) == 1, (
        f"Expected exactly 1 SA result row for exposure_reference={LOAN_REF!r}, "
        f"got {len(rows)}. "
        f"Rows in SA results: "
        f"{p1_94b_sa_results.select(['exposure_reference']).to_dicts()}"
    )
    return rows[0]


# ===========================================================================
# Schema contract test — load-bearing failing assertion (Wave 4 driver)
# ===========================================================================


def test_loan_schema_includes_hedge_coverage_ratio() -> None:
    """
    LOAD-BEARING SCHEMA TEST — FAILS pre-fix (Wave 3).

    LOAN_SCHEMA must declare hedge_coverage_ratio as pl.Float64 after the
    engine-implementer adds it in Wave 4.

    Pre-fix failure: "hedge_coverage_ratio" not in LOAN_SCHEMA.
    Post-fix expected: "hedge_coverage_ratio" in LOAN_SCHEMA with dtype pl.Float64.

    Arrange: import LOAN_SCHEMA from rwa_calc.data.schemas.
    Act:     check schema key presence and dtype.
    Assert:
        - "hedge_coverage_ratio" in LOAN_SCHEMA.
        - LOAN_SCHEMA["hedge_coverage_ratio"].dtype == pl.Float64.

    This test drives the engine-implementer to add the column declaration to
    LOAN_SCHEMA so the loader can correctly type-coerce the new parquet column
    and the SA namespace can read it as a Float64 expression.
    """
    from rwa_calc.data.schemas import LOAN_SCHEMA

    # Primary assertion — FAILS today (schema not yet extended)
    assert "hedge_coverage_ratio" in LOAN_SCHEMA, (
        "LOAN_SCHEMA does not yet declare 'hedge_coverage_ratio'. "
        "The engine-implementer must add it (pl.Float64, required=False, default=1.0) "
        "in Wave 4 to support the Art. 123B(2) partial-hedge coverage threshold gate. "
        f"Current LOAN_SCHEMA keys: {list(LOAN_SCHEMA.keys())}"
    )

    # Dtype assertion (only reached once key is present)
    actual_dtype = LOAN_SCHEMA["hedge_coverage_ratio"].dtype
    assert actual_dtype == pl.Float64, (
        f"LOAN_SCHEMA['hedge_coverage_ratio'].dtype = {actual_dtype!r}. "
        f"Expected pl.Float64 (hedge coverage is a proportion, e.g. 0.85)."
    )


# ===========================================================================
# Behavioural acceptance test — Art. 123B(2) hedge-coverage threshold gate
# ===========================================================================


class TestB31P194BPartialHedgeBelowThreshold:
    """
    P1.94b: hedge_coverage_ratio=0.85 is below the 0.90 Art. 123B(2) threshold.

    A retail_other EUR loan with is_hedged=False and hedge_coverage_ratio < 0.90
    is treated as effectively un-hedged: the Art. 123B 1.5x currency-mismatch
    multiplier must fire.

    Expected post-fix:
        risk_weight = 0.75 × 1.50 = 1.125  (Art. 123(1) base × Art. 123B multiplier)
        rwa_final   = 100,000 × 1.125 = 112,500
        ead_final   = 100,000
        currency_mismatch_multiplier_applied = True
        exposure_class = "retail_other"

    The fixture-builder report notes that hedge_coverage_ratio is a new column
    appended to the loans parquet but not yet in production LOAN_SCHEMA.
    The schema test above (test_loan_schema_includes_hedge_coverage_ratio) is the
    primary load-bearing failure.  This behavioural test may currently pass because
    P1.94a's is_hedged=False arm already fires the multiplier unconditionally.
    """

    def test_b31_retail_partial_hedge_below_90pct_fires_currency_mismatch_multiplier(
        self, p194b_row: dict
    ) -> None:
        """
        LOAD-BEARING BEHAVIOURAL TEST.

        hedge_coverage_ratio=0.85 < 0.90 threshold → Art. 123B multiplier fires.

        Arrange: P194B_PARTIAL_HEDGE — retail_other, EUR 100,000, GBP income,
                 is_hedged=False, hedge_coverage_ratio=0.85, B31 framework.
        Act:     Full SA pipeline via PipelineOrchestrator.
        Assert:
            risk_weight  ≈ 1.125  (75% × 1.5 — multiplier fires, ratio < 0.90)
            rwa_final    ≈ 112,500.0
            ead_final    ≈ 100,000.0
            currency_mismatch_multiplier_applied == True
            exposure_class == "retail_other"

        Pre-fix: if the engine has no hedge_coverage_ratio gate, the multiplier
        fires because is_hedged=False — this test may pass by accident on the
        pre-fix engine.  The schema test is the primary load-bearing failure.
        Post-fix: multiplier fires because ratio (0.85) < threshold (0.90).
        """
        # Assert risk_weight
        rw = float(p194b_row["risk_weight"])
        assert rw == pytest.approx(RW_PARTIAL_HEDGE, abs=_RW_TOL), (
            f"P1.94b (P194B_PARTIAL_HEDGE): risk_weight {rw:.6f} != "
            f"expected {RW_PARTIAL_HEDGE:.6f} "
            f"(= {SA_RETAIL_BASE_RW:.2f} × {CURRENCY_MISMATCH_MULTIPLIER:.2f}). "
            f"Art. 123B multiplier must fire because hedge_coverage_ratio "
            f"({HEDGE_COVERAGE_RATIO:.2f}) < threshold ({HEDGE_COVERAGE_THRESHOLD:.2f})."
        )

        # Assert rwa_final
        rwa = float(p194b_row["rwa_final"])
        assert rwa == pytest.approx(RWA_PARTIAL_HEDGE, abs=_RWA_TOL), (
            f"P1.94b (P194B_PARTIAL_HEDGE): rwa_final {rwa:,.2f} != "
            f"expected {RWA_PARTIAL_HEDGE:,.2f}. "
            f"EAD = {_EAD:,.0f} × risk_weight {RW_PARTIAL_HEDGE:.4f}."
        )

        # Assert ead_final
        ead = float(p194b_row["ead_final"])
        assert ead == pytest.approx(_EAD, abs=_EAD_TOL), (
            f"P1.94b (P194B_PARTIAL_HEDGE): ead_final {ead:,.2f} != expected {_EAD:,.2f}."
        )

        # Assert currency_mismatch_multiplier_applied
        applied = p194b_row.get("currency_mismatch_multiplier_applied")
        assert applied is not None, (
            "currency_mismatch_multiplier_applied column absent from SA results. "
            "The engine must emit this column "
            "(see namespace.py apply_currency_mismatch_multiplier)."
        )
        assert applied is True or applied == True, (  # noqa: E712
            f"P1.94b (P194B_PARTIAL_HEDGE): "
            f"currency_mismatch_multiplier_applied = {applied!r}. "
            f"Expected True — is_hedged=False with hedge_coverage_ratio "
            f"({HEDGE_COVERAGE_RATIO:.2f}) < threshold ({HEDGE_COVERAGE_THRESHOLD:.2f}) "
            f"must trigger Art. 123B 1.5x multiplier."
        )

        # Assert exposure_class
        ec = p194b_row.get("exposure_class")
        assert ec == _EXPOSURE_CLASS, (
            f"P1.94b (P194B_PARTIAL_HEDGE): exposure_class = {ec!r}. "
            f"Expected {_EXPOSURE_CLASS!r} (natural person, non-mortgage retail)."
        )
