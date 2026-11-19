"""
P1.30(e) / GT-03: tranched (Art. 234) protection is not substituted.

Pipeline position:
    Loader -> HierarchyResolver -> Classifier -> CRMProcessor -> SACalculator -> Aggregator

What this pins:
- A guarantee covering the mezzanine band [200,000, 600,000) of a 1,000,000 loan
  is NOT recognised in either regime: no guarantor sub-row, the loan keeps the
  obligor's 100%, RWA 1,000,000, and one CRM027 names the guarantee.
- Control: the same guarantee with the band columns left null (a pro-rata share)
  IS recognised — 800,000 (CRR) / 720,000 (Basel 3.1) — so the outcome turns on
  the tranching columns alone, not on some other eligibility gate.

Rule (PS1/26 Appendix 1; CRR Art. 234 / 235(2) read the same in substance):
    Art. 234(1): "Where an institution transfers a part of the risk of a loan in
    one or more tranches, the institution shall comply with the requirements set
    out in Chapter 5 of Title II of Part Three of CRR."
    Art. 235(2): "Where the protected amount (GA) is less than the exposure (E),
    the institution may apply the formula specified in paragraphs 1 and 1A only
    where the protected and unprotected parts of the exposure are of equal
    seniority."

The engine does not run Chapter 5 for such protection, so the exposure keeps
its unprotected requirement — the Art. 268(1) upper bound of the Chapter 5
result.

Why this test was rewritten (LESSONS C1): it previously pinned the P1.30(e)
design — a three-row split ``__REM_FL`` / ``__G_`` / ``__REM_SEN`` with the
guarantor's weight substituted on the mezzanine band, RWA 800,000 (CRR) and
720,000 (Basel 3.1). Art. 235(2) forbids that substitution, because the band is
not of equal seniority with the retained first-loss and senior slices (GT-03 of
the guarantees review; verifier re-measured 8.0 / 7.2 against a correct 10.0 on
a 10 loan).

References:
    - CRR Art. 234 / PS1/26 Art. 234(1); CRR / PS1/26 Art. 235(2); CRR Art. 268(1)
    - tests/fixtures/p1_30e/p1_30e.py: fixture builder and scenario constants
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl
import pytest
from tests.fixtures.p1_30e.p1_30e import (
    EXPECTED_CONTROL_RWA,
    EXPECTED_EAD_TOTAL,
    EXPECTED_RWA_TOTAL,
    GUARANTEE_REF,
    GUARANTOR_REF,
    LOAN_REF,
)
from tests.fixtures.raw_bundle import make_raw_bundle

from rwa_calc.contracts.bundles import AggregatedResultBundle, RawDataBundle
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.contracts.errors import ERROR_TRANCHED_PROTECTION_NOT_RECOGNISED
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator

_FIXTURES_DIR = Path(__file__).parent.parent.parent / "fixtures" / "p1_30e"

# CRR inside its validity window; Basel 3.1 after 1 January 2027. The loan runs
# 2026-01-02 to 2031-01-02 and the guarantee matches it, so no Art. 239(3) scaling.
_REPORTING_DATES = {"crr": date(2026, 6, 1), "b31": date(2027, 6, 1)}


def _make_bundle(*, tranched: bool) -> RawDataBundle:
    """The P1.30(e) parquet fixtures; ``tranched=False`` nulls the band columns."""
    guarantees = pl.scan_parquet(_FIXTURES_DIR / "guarantee.parquet")
    if not tranched:
        guarantees = guarantees.with_columns(
            pl.lit(None, dtype=pl.Float64).alias("attachment_amount"),
            pl.lit(None, dtype=pl.Float64).alias("detachment_amount"),
        )
    return make_raw_bundle(
        facilities=pl.LazyFrame(
            schema={"facility_reference": pl.String, "counterparty_reference": pl.String}
        ),
        loans=pl.scan_parquet(_FIXTURES_DIR / "loan.parquet"),
        counterparties=pl.scan_parquet(_FIXTURES_DIR / "counterparty.parquet"),
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
        ratings=pl.scan_parquet(_FIXTURES_DIR / "rating.parquet"),
        guarantees=guarantees,
    )


def _run(regime: str, *, tranched: bool) -> AggregatedResultBundle:
    factory = CalculationConfig.crr if regime == "crr" else CalculationConfig.basel_3_1
    config = factory(
        reporting_date=_REPORTING_DATES[regime], permission_mode=PermissionMode.STANDARDISED
    )
    return PipelineOrchestrator().run_with_data(_make_bundle(tranched=tranched), config)


def _loan_rows(result: AggregatedResultBundle) -> pl.DataFrame:
    assert result.sa_results is not None, "SA results must not be None for SA-only config"
    return result.sa_results.collect().filter(pl.col("parent_exposure_reference") == LOAN_REF)


class TestArt234TranchedProtectionNotSubstituted:
    """GT-03: the mezzanine band [a, d) gets no risk-weight substitution."""

    @pytest.fixture(scope="class", params=["crr", "b31"])
    def regime(self, request: pytest.FixtureRequest) -> str:
        return request.param

    @pytest.fixture(scope="class")
    def tranched(self, regime: str) -> AggregatedResultBundle:
        return _run(regime, tranched=True)

    def test_control_pro_rata_share_is_recognised(self, regime: str) -> None:
        """Adequacy: without the band the same guarantee substitutes on 400,000.

        400,000 x guarantor weight + 600,000 x 100% = 800,000 (CRR) / 720,000 (B31).
        Were this not recognised, the tranched assertions below would prove nothing.
        """
        rows = _loan_rows(_run(regime, tranched=False))

        assert rows.filter(pl.col("guarantor_reference") == GUARANTOR_REF).height == 1
        assert rows["rwa_final"].sum() == pytest.approx(EXPECTED_CONTROL_RWA[regime], rel=1e-9)

    def test_no_guarantor_row_is_emitted(
        self, tranched: AggregatedResultBundle, regime: str
    ) -> None:
        rows = _loan_rows(tranched)

        assert rows.height == 1
        assert rows["guarantor_reference"].is_null().all()
        assert rows["guaranteed_portion"].fill_null(0.0).sum() == pytest.approx(0.0)

    def test_rwa_is_the_unprotected_requirement(
        self, tranched: AggregatedResultBundle, regime: str
    ) -> None:
        """1,000,000 at the obligor's 100% (was 800,000 CRR / 720,000 B31)."""
        rows = _loan_rows(tranched)

        assert rows["ead_final"].sum() == pytest.approx(EXPECTED_EAD_TOTAL, rel=1e-9)
        assert rows["rwa_final"].sum() == pytest.approx(EXPECTED_RWA_TOTAL, rel=1e-9)

    def test_one_crm027_names_the_guarantee(
        self, tranched: AggregatedResultBundle, regime: str
    ) -> None:
        found = [e for e in tranched.errors if e.code == ERROR_TRANCHED_PROTECTION_NOT_RECOGNISED]

        assert len(found) == 1
        assert f"'{GUARANTEE_REF}'" in found[0].message
        assert found[0].exposure_reference == LOAN_REF
