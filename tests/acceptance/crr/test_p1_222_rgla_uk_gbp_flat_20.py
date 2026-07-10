"""
P1.222 — Flat-20% domestic-currency RGLA weight restricted to the UK/GBP
limb; unrated Italian municipality falls to Table 1A (Art. 115(1)(a)).

Pipeline position:
    Loader -> HierarchyResolver -> Classifier -> CRMProcessor
        -> SACalculator -> OutputAggregator

Key assertion:
    ``entity_type="rgla_institution"`` maps to SA exposure class RGLA
    (ordinary RGLA, not the UK-devolved ``rgla_sovereign`` 0% branch).
    ``_prepare_risk_weight_lookup`` (engine/sa/risk_weights.py) builds a
    composite ``is_domestic_currency = is_uk_domestic | is_eu_domestic``
    flag. That composite is legitimately reused for the Art. 114(4)/(7)
    CGCB 0% branch, but the SAME flag also gates the Art. 115(5) RGLA 20%
    branch (``_apply_b31_risk_weight_overrides`` / ``_apply_crr_risk_weight
    _overrides``), whose scope is UK RGLAs denominated AND funded in
    sterling only.

    Pre-fix (current engine bug): an unrated Italian municipality RGLA
    (IT, EUR — EU-domestic-currency) wrongly short-circuits to the RGLA
    domestic-currency 20% branch instead of falling through to the
    unrated Table 1A sovereign-derived lookup (CRR/PS1/26 Art. 115(1)(a)),
    understating risk_weight (0.20 vs 1.00) and rwa (1,000,000 vs the
    correct 5,000,000).

    Post-fix expected (identical under CRR and Basel 3.1 — Art. 115 is
    unchanged between regimes):
        exposure_class = "rgla" (ExposureClass.RGLA.value)
        risk_weight    = 1.00 (Table 1A, CQS 3 sovereign-derived, unrated)
        ead_final      = 5,000,000.0
        rwa_final      = 5,000,000.0 (EAD x RW x SF, SF=1.0)

References:
    - CRR Art. 115(1)(a) Table 1A / PRA PS1/26 Art. 115(1)(a) Table 1A --
      RGLA sovereign-derived risk weights (unrated RGLA).
    - CRR Art. 115(5) / PRA PS1/26 Art. 115(5) -- domestic-currency 20%,
      scoped to UK RGLAs denominated and funded in sterling.
    - CRR Art. 114(4)/(7) / PRA PS1/26 Art. 114(4)/(7) -- CGCB 0% domestic
      currency branch (legitimate use of the composite is_domestic_currency
      flag; this scenario does NOT touch that branch).
    - src/rwa_calc/engine/sa/risk_weights.py:952-954 (composite
      is_domestic_currency flag), :1143 (_apply_b31_risk_weight_overrides
      RGLA 20% branch), :1349 (_apply_crr_risk_weight_overrides RGLA 20%
      branch).
    - tests/fixtures/p1_222/p1_222.py: fixture builder and scenario constants.
    - docs/plans/compliance-audit-crr-111-241-rectification.md:354-358
      (Section 5 WS6, P1.222).
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl
import pytest
from tests.fixtures.p1_222.p1_222 import (
    EAD,
    EXPECTED_EXPOSURE_CLASS,
    EXPECTED_RISK_WEIGHT,
    EXPECTED_RWA,
    LOAN_REF,
)
from tests.fixtures.raw_bundle import make_raw_bundle

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import ExposureClass
from rwa_calc.engine.pipeline import PipelineOrchestrator

# ---------------------------------------------------------------------------
# Fixture path
# ---------------------------------------------------------------------------

_FIXTURES_DIR = Path(__file__).parent.parent.parent / "fixtures" / "p1_222"


# ---------------------------------------------------------------------------
# Bundle builder
# ---------------------------------------------------------------------------


def _build_bundle() -> RawDataBundle:
    """
    Construct a RawDataBundle from the P1.222 parquets.

    Two parquets are loaded:
      - counterparty.parquet: CP_RGLA_IT_001 (entity_type=rgla_institution,
        IT, sovereign_cqs=3, no ratings.parquet row -> unrated own-CQS)
      - loan.parquet:         LN_RGLA_IT_001 (EUR 5,000,000 senior term
        loan, ~5-year maturity)

    No ratings, model_permissions, facility_mappings or lending_mappings
    parquets exist for this scenario -- the loan links directly to the
    counterparty, no facility hierarchy or model permissions are exercised.
    """
    return make_raw_bundle(
        loans=pl.scan_parquet(_FIXTURES_DIR / "loan.parquet"),
        counterparties=pl.scan_parquet(_FIXTURES_DIR / "counterparty.parquet"),
    )


# ---------------------------------------------------------------------------
# Pipeline runner
# ---------------------------------------------------------------------------


def _run_pipeline(config: CalculationConfig) -> dict:
    """
    Run the P1.222 fixtures through the credit risk pipeline and return the
    single aggregated result row for LN_RGLA_IT_001 as a dict.
    """
    bundle = _build_bundle()
    results = PipelineOrchestrator().run_with_data(bundle, config)
    df = results.results.collect()
    rows = df.filter(pl.col("exposure_reference") == LOAN_REF)
    assert len(rows) == 1, (
        f"Expected exactly 1 aggregated row for {LOAN_REF!r}, got {len(rows)}. "
        f"All exposure_references: {df['exposure_reference'].to_list()}"
    )
    return rows.row(0, named=True)


# ---------------------------------------------------------------------------
# Config factories -- CRR and Basel 3.1 (Art. 115 identical under both)
# ---------------------------------------------------------------------------


def _crr_config() -> CalculationConfig:
    """CRR SA config, reporting_date before Basel 3.1 go-live."""
    return CalculationConfig.crr(reporting_date=date(2026, 6, 30))


def _b31_config() -> CalculationConfig:
    """Basel 3.1 SA config, reporting_date post go-live (2027-01-04)."""
    return CalculationConfig.basel_3_1(reporting_date=date(2027, 1, 4))


# ---------------------------------------------------------------------------
# P1.222 acceptance tests
# ---------------------------------------------------------------------------


class TestP1222RglaUnratedItalianMunicipalityTable1A:
    """
    P1.222: unrated Italian municipality RGLA (rgla_institution, IT, EUR,
    sovereign_cqs=3) must fall to the Table 1A unrated sovereign-derived
    lookup (Art. 115(1)(a)), NOT the UK/GBP-scoped domestic-currency 20%
    branch (Art. 115(5)) -- identical result under CRR and Basel 3.1.

    PRE-FIX (today): risk_weight=0.20, rwa_final=1,000,000.0 -> tests FAIL.
    POST-FIX: risk_weight=1.00, rwa_final=5,000,000.0 -> tests pass.
    """

    @pytest.fixture(scope="class")
    def crr_result_row(self) -> dict:
        """CRR aggregated result row for P1.222's LN_RGLA_IT_001."""
        return _run_pipeline(_crr_config())

    @pytest.fixture(scope="class")
    def b31_result_row(self) -> dict:
        """Basel 3.1 aggregated result row for P1.222's LN_RGLA_IT_001."""
        return _run_pipeline(_b31_config())

    # ------------------------------------------------------------------
    # PRIMARY ASSERTIONS -- FAIL pre-fix (both regimes, Art. 115 identical)
    # ------------------------------------------------------------------

    def test_crr_risk_weight_is_table_1a_cqs3(self, crr_result_row: dict) -> None:
        """
        P1.222 CRR PRIMARY: unrated Italian municipality RGLA risk_weight
        must be 1.00 (Table 1A, CQS 3 sovereign-derived), not the UK/GBP-
        scoped domestic-currency 20%.

        PRE-FIX (today): risk_weight = 0.20 -> test FAILS.
        POST-FIX:        risk_weight = 1.00 -> test passes.
        """
        actual_rw = crr_result_row["risk_weight"]
        assert actual_rw == pytest.approx(EXPECTED_RISK_WEIGHT, rel=1e-9), (
            f"P1.222 CRR: risk_weight should be {EXPECTED_RISK_WEIGHT:.2f} "
            f"(CRR Art. 115(1)(a) Table 1A, RGLA sovereign-derived, unrated, "
            f"CQS 3). Got {actual_rw:.6f}. "
            f"Pre-fix, the composite is_domestic_currency flag "
            f"(is_uk_domestic | is_eu_domestic) wrongly fires the Art. 115(5) "
            f"20% branch for this EU-domestic-currency (IT/EUR) RGLA -- that "
            f"branch is scoped to UK RGLAs denominated and funded in sterling "
            f"only. Fix _apply_crr_risk_weight_overrides "
            f"(engine/sa/risk_weights.py)."
        )

    def test_crr_rwa_final_is_5_000_000(self, crr_result_row: dict) -> None:
        """
        P1.222 CRR DISCRIMINATING: rwa_final = EAD x RW = 5,000,000 x 1.00
        = 5,000,000.

        PRE-FIX (today): rwa_final = 1,000,000.0 (EAD x buggy 0.20)
        -> test FAILS (understated by 4,000,000).
        """
        actual_rwa = crr_result_row["rwa_final"]
        assert actual_rwa == pytest.approx(EXPECTED_RWA, rel=1e-9), (
            f"P1.222 CRR: rwa_final should be {EXPECTED_RWA:,.2f} "
            f"(EAD {EAD:,.0f} x Table 1A CQS3 RW 1.00). Got {actual_rwa:,.2f}. "
            f"Pre-fix value ~1,000,000 (EAD x buggy 20%) understates capital "
            f"by 4,000,000."
        )

    def test_b31_risk_weight_is_table_1a_cqs3(self, b31_result_row: dict) -> None:
        """
        P1.222 Basel 3.1 PRIMARY: identical result to CRR -- Art. 115 is
        unchanged between regimes. risk_weight must be 1.00, not 0.20.

        PRE-FIX (today): risk_weight = 0.20 -> test FAILS.
        POST-FIX:        risk_weight = 1.00 -> test passes.
        """
        actual_rw = b31_result_row["risk_weight"]
        assert actual_rw == pytest.approx(EXPECTED_RISK_WEIGHT, rel=1e-9), (
            f"P1.222 B31: risk_weight should be {EXPECTED_RISK_WEIGHT:.2f} "
            f"(PS1/26 Art. 115(1)(a) Table 1A, RGLA sovereign-derived, "
            f"unrated, CQS 3). Got {actual_rw:.6f}. "
            f"Pre-fix, the composite is_domestic_currency flag wrongly fires "
            f"the Art. 115(5) 20% branch for this EU-domestic-currency "
            f"(IT/EUR) RGLA. Fix _apply_b31_risk_weight_overrides "
            f"(engine/sa/risk_weights.py)."
        )

    def test_b31_rwa_final_is_5_000_000(self, b31_result_row: dict) -> None:
        """
        P1.222 Basel 3.1 DISCRIMINATING: rwa_final = 5,000,000 (identical
        to CRR).

        PRE-FIX (today): rwa_final = 1,000,000.0 -> test FAILS.
        """
        actual_rwa = b31_result_row["rwa_final"]
        assert actual_rwa == pytest.approx(EXPECTED_RWA, rel=1e-9), (
            f"P1.222 B31: rwa_final should be {EXPECTED_RWA:,.2f} "
            f"(EAD {EAD:,.0f} x Table 1A CQS3 RW 1.00). Got {actual_rwa:,.2f}."
        )

    # ------------------------------------------------------------------
    # SUPPORTING ASSERTIONS -- exposure-class / EAD invariants (both regimes)
    # ------------------------------------------------------------------

    def test_crr_exposure_class_is_rgla(self, crr_result_row: dict) -> None:
        """P1.222 CRR: exposure_class == "rgla" (unaffected by the fix)."""
        assert ExposureClass.RGLA.value == EXPECTED_EXPOSURE_CLASS
        assert crr_result_row["exposure_class"] == EXPECTED_EXPOSURE_CLASS, (
            f"P1.222 CRR: exposure_class should be {EXPECTED_EXPOSURE_CLASS!r}. "
            f"Got {crr_result_row['exposure_class']!r}."
        )

    def test_b31_exposure_class_is_rgla(self, b31_result_row: dict) -> None:
        """P1.222 B31: exposure_class == "rgla" (unaffected by the fix)."""
        assert b31_result_row["exposure_class"] == EXPECTED_EXPOSURE_CLASS, (
            f"P1.222 B31: exposure_class should be {EXPECTED_EXPOSURE_CLASS!r}. "
            f"Got {b31_result_row['exposure_class']!r}."
        )

    def test_crr_ead_final_matches_drawn_amount(self, crr_result_row: dict) -> None:
        """P1.222 CRR: ead_final = drawn_amount (5,000,000.0); invariant across the fix."""
        assert crr_result_row["ead_final"] == pytest.approx(EAD, rel=1e-9), (
            f"P1.222 CRR: ead_final should be {EAD:,.2f}. "
            f"Got {crr_result_row['ead_final']:,.2f}."
        )

    def test_b31_ead_final_matches_drawn_amount(self, b31_result_row: dict) -> None:
        """P1.222 B31: ead_final = drawn_amount (5,000,000.0); invariant across the fix."""
        assert b31_result_row["ead_final"] == pytest.approx(EAD, rel=1e-9), (
            f"P1.222 B31: ead_final should be {EAD:,.2f}. "
            f"Got {b31_result_row['ead_final']:,.2f}."
        )
