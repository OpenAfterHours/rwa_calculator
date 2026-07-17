"""
P1.229 (Basel 3.1) — Art. 235(3): the domestic-CGCB 0% extension requires the
exposure to be BOTH denominated AND *funded* in the guarantor's domestic
currency.

Twin of tests/acceptance/crr/test_p1_229_art_235_3_funding_currency.py. Art.
235(3) and the Art. 114(4)/(7) 0% extension read the same in both regimes, and
the DE sovereign CQS-3 CGCB risk weight is 50% in both packs (b31 inherits
cgcb_risk_weights from the common/crr pack), so the expected values are
identical — only the config (framework + go-live reporting date) differs.

Pipeline position:
    Loader -> HierarchyResolver -> Classifier -> CRMProcessor -> SACalculator -> Aggregator

References:
    - PS1/26 Art. 235(3) / Art. 114(4)/(7): denominated-and-funded 0% condition.
    - tests/fixtures/p1_229/p1_229.py: fixture builder + full hand-calculation.
    - docs/plans/compliance-audit-crr-111-241-rectification.md §5 WS2, P1.229.
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig, PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.fixtures.p1_229.p1_229 import (
    EXPECTED_RW_MATCHED,
    EXPECTED_RW_MISMATCH_POSTFIX,
    EXPECTED_RW_MISMATCH_PREFIX,
    EXPECTED_RW_NULL,
    LOAN_MATCHED_REF,
    LOAN_MISMATCH_REF,
    LOAN_NULL_REF,
    build_p229_bundle,
)


def _run_sa() -> pl.DataFrame:
    """Run the P1.229 fixture through the Basel 3.1 SA pipeline; return SA results."""
    config = CalculationConfig.basel_3_1(
        reporting_date=date(2027, 6, 30),
        permission_mode=PermissionMode.STANDARDISED,
    )
    results = PipelineOrchestrator().run_with_data(build_p229_bundle(), config)
    assert results.sa_results is not None, "SA results should not be None under STANDARDISED"
    return results.sa_results.collect()


def _guaranteed_row(df: pl.DataFrame, loan_ref: str) -> dict:
    """Return the single guaranteed-portion (__G_) sub-row for a loan."""
    rows = df.filter(
        (pl.col("parent_exposure_reference") == loan_ref)
        & pl.col("exposure_reference").str.contains("__G_")
    ).to_dicts()
    assert len(rows) == 1, (
        f"P1.229: expected exactly 1 guaranteed-portion row for {loan_ref}, got {len(rows)}. "
        f"All rows: {df.select(['exposure_reference', 'parent_exposure_reference']).to_dicts()}"
    )
    return rows[0]


class TestP1229Art2353FundingCurrencyB31:
    """P1.229 Basel 3.1: the Art. 235(3) funding limb on the domestic-CGCB 0% extension."""

    @pytest.fixture(scope="class")
    def sa_results(self) -> pl.DataFrame:
        return _run_sa()

    # ---- DISCRIMINATING: FAILS pre-fix -------------------------------------

    def test_usd_funded_eur_guaranteed_gets_sovereign_50pct_not_zero(
        self, sa_results: pl.DataFrame
    ) -> None:
        """
        Headline: a USD-funded, EUR-guaranteed loan from a DE sovereign (CQS 3)
        must receive the guarantor's 50% CGCB risk weight on the guaranteed
        portion — the 0% extension is denied because the exposure is not funded
        in EUR (PS1/26 Art. 235(3)).

        PRE-FIX: risk_weight = 0.00 (funding limb absent) -> test FAILS.
        POST-FIX: risk_weight = 0.50.
        """
        row = _guaranteed_row(sa_results, LOAN_MISMATCH_REF)
        actual = row["risk_weight"]
        assert actual == pytest.approx(EXPECTED_RW_MISMATCH_POSTFIX, abs=1e-9), (
            f"P1.229 B31: USD-funded EUR-guaranteed guaranteed-portion risk_weight "
            f"should be {EXPECTED_RW_MISMATCH_POSTFIX:.2f} (DE sovereign CQS 3 — 0% "
            f"extension denied, exposure not funded in EUR per Art. 235(3)). "
            f"Got {actual:.4f}. Pre-fix value ~{EXPECTED_RW_MISMATCH_PREFIX:.2f} means "
            f"the funding limb is missing and the 0% short-circuit fired wrongly."
        )

    # ---- REGRESSION CONTROLS: pass pre- and post-fix -----------------------

    def test_eur_funded_eur_guaranteed_keeps_zero(self, sa_results: pl.DataFrame) -> None:
        """
        Control: a EUR-funded, EUR-guaranteed loan from the DE sovereign is BOTH
        denominated and funded in EUR, so the 0% extension legitimately applies.
        Must stay 0.00 before and after the fix.
        """
        row = _guaranteed_row(sa_results, LOAN_MATCHED_REF)
        actual = row["risk_weight"]
        assert actual == pytest.approx(EXPECTED_RW_MATCHED, abs=1e-9), (
            f"P1.229 B31: EUR-funded EUR-guaranteed guaranteed-portion risk_weight "
            f"should be {EXPECTED_RW_MATCHED:.2f} (denominated AND funded in EUR — "
            f"0% extension applies). Got {actual:.4f}."
        )

    def test_null_funding_currency_is_permissive(self, sa_results: pl.DataFrame) -> None:
        """
        Null policy: a null funding currency is PERMISSIVE — it falls back to the
        exposure's EUR denomination, which matches the domestic currency, so the
        0% extension still applies (mirrors the Art. 237(2)(a) null fallback /
        P1.10 precedent; preserves datasets that do not report a separate funding
        currency). Must stay 0.00 before and after the fix.
        """
        row = _guaranteed_row(sa_results, LOAN_NULL_REF)
        actual = row["risk_weight"]
        assert actual == pytest.approx(EXPECTED_RW_NULL, abs=1e-9), (
            f"P1.229 B31: null-funding guaranteed-portion risk_weight should be "
            f"{EXPECTED_RW_NULL:.2f} (permissive denomination fallback -> EUR match). "
            f"Got {actual:.4f}."
        )

    def test_mismatch_loan_ead_fully_on_guaranteed_portion(self, sa_results: pl.DataFrame) -> None:
        """EAD integrity: the 100%-coverage guarantee places the whole EAD on the
        guaranteed portion (the substitution split fired), so the discriminating
        risk-weight assertion above is not an artefact of a zero-EAD sub-row."""
        row = _guaranteed_row(sa_results, LOAN_MISMATCH_REF)
        assert row["ead_final"] > 0.0, (
            f"P1.229 B31: guaranteed-portion ead_final should be positive (full "
            f"coverage), got {row['ead_final']}"
        )
