"""
P1.118: CRR Art. 162(4) — effective maturity (M) derivation for short-term
self-liquidating trade finance under F-IRB.

Pipeline position:
    RawDataBundle -> Full Pipeline -> AggregatedResultBundle (irb_results)

Scenario:
    Two identical corporate counterparties (GB, PD=0.50%, annual_revenue=GBP 200m)
    each holding one documentary-credit LC (risk_type=MLR, nominal=GBP 10m,
    maturity=2026-09-30, residual≈0.7452y from reporting_date 2026-01-01).

    Row A — TF_LC_001 (CP_TRADE_001):
        is_short_term_trade_lc=True
        has_one_day_maturity_floor=False  (caller leaves False; engine must derive True)

        Expected engine behaviour:
            1. Engine derives has_one_day_maturity_floor=True from
               is_short_term_trade_lc=True (CRR Art. 162(4) carve-out).
            2. irb/namespace.py prepare_columns then sets maturity = 1/365 ≈ 0.00274y
               directly (not as a floor — it overwrites the computed residual).
            3. irb_maturity_m = 1/365 ≈ 0.00274y.

    Row B — TF_LC_002 (CP_TRADE_002):
        is_short_term_trade_lc=False
        has_one_day_maturity_floor=False

        Expected: standard CRR Art. 162(2) 1-year M floor applies.
        Residual 0.7452y < 1.0y → maturity clipped to [1.0, 5.0] → M = 1.0y.

Engine bug (pre-fix):
    irb/namespace.py `prepare_columns` (lines 299-307) reads `has_one_day_maturity_floor`
    directly from the input column.  It does NOT derive the flag from
    `is_short_term_trade_lc`.  With has_one_day_maturity_floor=False on both rows,
    both rows fall through to the standard maturity_date chain with a 1.0y clip floor,
    so Row A's irb_maturity_m is incorrectly 1.0y instead of 1/365 ≈ 0.00274y.

    Test failure before fix: irb_maturity_m for TF_LC_001 ≈ 1.0 != ≈ 0.00274.

References:
    - CRR Art. 162(4): 1-day effective maturity floor for short-term
      self-liquidating trade transactions (incl. documentary credits).
    - CRR Art. 162(2): standard 1-year M floor for all other IRB exposures.
    - src/rwa_calc/engine/irb/namespace.py lines 299-307: prepare_columns maturity chain
      (sets maturity = 1/365 when has_one_day_maturity_floor=True)
    - tests/fixtures/p1_118/p1_118.py: fixture constants and builders
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest
from tests.fixtures.p1_118.p1_118 import (
    CONTINGENT_REF_A,
    CONTINGENT_REF_B,
    EXPECTED_M_A,
    EXPECTED_M_B,
    REPORTING_DATE,
)
from tests.fixtures.raw_bundle import make_raw_bundle

from rwa_calc.contracts.bundles import AggregatedResultBundle
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import LOAN_SCHEMA
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

_FIXTURES_DIR = Path(__file__).parent.parent.parent / "fixtures" / "p1_118"

# ---------------------------------------------------------------------------
# Tolerances
# ---------------------------------------------------------------------------

# EXPECTED_M_A = 1/365 ≈ 0.00274y (1-day floor, engine sets M directly).
# EXPECTED_M_B = 1.0y (standard 1-year floor).
# A tolerance of ±0.002y (~0.73 days) unambiguously separates 0.00274y from
# 1.0y and is tight enough to catch any residual-maturity leakage.
_M_TOL = 0.002  # ±0.002y (≈ 0.73 days)


# ---------------------------------------------------------------------------
# Pipeline runner
# ---------------------------------------------------------------------------


def _run_pipeline_p1118() -> AggregatedResultBundle:
    """Run the CRR F-IRB pipeline with P1.118 scenario inputs.

    Loads counterparty, rating, model_permission, and contingent fixtures.
    Facilities and loans are empty — this is a pure contingent scenario.
    PermissionMode.IRB routes both counterparties to F-IRB via the
    UK_CORP_FIRB_01 model permission (exposure_class=corporate,
    approach=foundation_irb).
    """
    # Arrange — load parquets
    counterparties = pl.scan_parquet(_FIXTURES_DIR / "counterparty.parquet")
    ratings = pl.scan_parquet(_FIXTURES_DIR / "rating.parquet")
    model_permissions = pl.scan_parquet(_FIXTURES_DIR / "model_permission.parquet")
    contingents = pl.scan_parquet(_FIXTURES_DIR / "contingent.parquet")
    facility_mappings = pl.scan_parquet(_FIXTURES_DIR / "facility_mapping.parquet")
    lending_mappings = pl.scan_parquet(_FIXTURES_DIR / "lending_mapping.parquet")

    bundle = make_raw_bundle(
        facilities=pl.LazyFrame(
            schema={"facility_reference": pl.String, "counterparty_reference": pl.String}
        ),
        loans=pl.LazyFrame(schema=dtypes_of(LOAN_SCHEMA)),
        counterparties=counterparties,
        facility_mappings=facility_mappings,
        lending_mappings=lending_mappings,
        contingents=contingents,
        ratings=ratings,
        model_permissions=model_permissions,
    )

    config = CalculationConfig.crr(
        reporting_date=REPORTING_DATE,
        permission_mode=PermissionMode.IRB,
    )

    return PipelineOrchestrator().run_with_data(bundle, config)


def _get_irb_row(result: AggregatedResultBundle, contingent_ref: str) -> dict:
    """Return the IRB result dict for a given contingent_reference.

    Raises AssertionError if not found or not unique.
    """
    assert result.irb_results is not None, "irb_results must not be None for F-IRB scenario"
    df = result.irb_results.filter(
        pl.col("exposure_reference").str.contains(contingent_ref)
    ).collect()
    assert len(df) == 1, (
        f"Expected exactly 1 IRB row for {contingent_ref!r}, got {len(df)}. "
        f"Check that the counterparty was routed to F-IRB and not SA."
    )
    return df.to_dicts()[0]


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------


class TestP1118Art1624ShortTermTradeFinanceMDerivation:
    """
    P1.118 — CRR Art. 162(4): when ``is_short_term_trade_lc=True``, the engine
    must derive ``has_one_day_maturity_floor=True`` and set M = 1/365 ≈ 0.00274y.

    Engine mechanics (irb/namespace.py lines 299-307):
        When ``has_one_day_maturity_floor=True``, prepare_columns sets
        ``maturity = 1/365`` *directly* — not as a minimum floor but as an
        override that replaces the residual-maturity computation.
        The engine-implementer must add derivation logic so that
        ``is_short_term_trade_lc=True`` → ``has_one_day_maturity_floor=True``
        before this branch is evaluated.

    Row A (is_short_term_trade_lc=True):
        irb_maturity_m = 1/365 ≈ 0.00274y  (1-day-floor set by engine)
    Row B (is_short_term_trade_lc=False):
        irb_maturity_m = 1.0y  (standard 1-year floor, residual 0.7452y < 1.0y)

    Pre-fix: both rows receive M=1.0y because has_one_day_maturity_floor is read
    as-is from the input column (False on both rows) without derivation.
    """

    @pytest.fixture(scope="class")
    def result(self) -> AggregatedResultBundle:
        """Run the pipeline once; reuse across all tests in this class."""
        return _run_pipeline_p1118()

    @pytest.fixture(scope="class")
    def row_a(self, result: AggregatedResultBundle) -> dict:
        """IRB result row for TF_LC_001 (is_short_term_trade_lc=True)."""
        return _get_irb_row(result, CONTINGENT_REF_A)

    @pytest.fixture(scope="class")
    def row_b(self, result: AggregatedResultBundle) -> dict:
        """IRB result row for TF_LC_002 (is_short_term_trade_lc=False)."""
        return _get_irb_row(result, CONTINGENT_REF_B)

    # ------------------------------------------------------------------
    # Primary assertion — Row A: 1-day floor sets M = 1/365 ≈ 0.00274y
    # ------------------------------------------------------------------

    def test_p1_118_row_a_maturity_equals_one_day_floor(self, row_a: dict) -> None:
        """
        Row A (is_short_term_trade_lc=True) must have irb_maturity_m = 1/365 ≈ 0.00274y.

        Engine path (irb/namespace.py lines 299-307):
            when has_one_day_maturity_floor=True → maturity = 1/365 (literal assignment).
        The engine-implementer must derive has_one_day_maturity_floor=True from
        is_short_term_trade_lc=True (Art. 162(4) carve-out).

        Arrange: TF_LC_001, is_short_term_trade_lc=True, has_one_day_maturity_floor=False
                 (engine must derive True from is_short_term_trade_lc).
                 Reporting date 2026-01-01, maturity_date 2026-09-30 (272 days residual).
        Act:     full CRR F-IRB pipeline.
        Assert:  irb_maturity_m ≈ 1/365 ≈ 0.00274y (±0.002y).

        Pre-fix: irb_maturity_m = 1.0y (standard 1-year floor, flag not derived).
        """
        # Arrange / Act (pipeline run in fixture)
        assert "irb_maturity_m" in row_a, (
            f"Column 'irb_maturity_m' not found in IRB result for {CONTINGENT_REF_A}. "
            f"Available columns: {list(row_a.keys())}"
        )
        m_a = row_a["irb_maturity_m"]

        # Assert — EXPECTED_M_A = 1/365 ≈ 0.00274y
        assert m_a == pytest.approx(EXPECTED_M_A, abs=_M_TOL), (
            f"TF_LC_001 (is_short_term_trade_lc=True) irb_maturity_m={m_a:.5f}y "
            f"!= expected {EXPECTED_M_A:.5f}y (1-day floor: 1/365). "
            f"If irb_maturity_m ≈ 1.0y the engine is applying the standard 1-year "
            f"floor (Art. 162(2)) instead of the 1-day carve-out (Art. 162(4)). "
            f"The engine must derive has_one_day_maturity_floor=True from "
            f"is_short_term_trade_lc=True, which triggers maturity=1/365 in "
            f"namespace.py prepare_columns lines 299-307."
        )

    # ------------------------------------------------------------------
    # Primary assertion — Row B: standard 1-year floor must bind
    # ------------------------------------------------------------------

    def test_p1_118_row_b_maturity_equals_one_year_standard_floor(self, row_b: dict) -> None:
        """
        Row B (is_short_term_trade_lc=False) must use the standard 1-year M floor (Art. 162(2)).

        Residual maturity 0.7452y < 1.0y → maturity clipped to [1.0, 5.0] → M = 1.0y.

        Arrange: TF_LC_002, is_short_term_trade_lc=False, has_one_day_maturity_floor=False.
                 Reporting date 2026-01-01, maturity_date 2026-09-30 (272 days).
        Act:     full CRR F-IRB pipeline.
        Assert:  irb_maturity_m = 1.0y (±0.002y).
        """
        # Arrange / Act (pipeline run in fixture)
        assert "irb_maturity_m" in row_b, (
            f"Column 'irb_maturity_m' not found in IRB result for {CONTINGENT_REF_B}. "
            f"Available columns: {list(row_b.keys())}"
        )
        m_b = row_b["irb_maturity_m"]

        # Assert — EXPECTED_M_B = 1.0y
        assert m_b == pytest.approx(EXPECTED_M_B, abs=_M_TOL), (
            f"TF_LC_002 (is_short_term_trade_lc=False) irb_maturity_m={m_b:.4f}y "
            f"!= expected {EXPECTED_M_B:.4f}y (1-year floor). "
            f"Residual 0.7452y < 1.0y so the standard Art. 162(2) 1-year floor "
            f"must bind for this exposure."
        )

    # ------------------------------------------------------------------
    # Directional assertion — Row A maturity strictly less than Row B
    # ------------------------------------------------------------------

    def test_p1_118_row_a_maturity_strictly_less_than_row_b(self, row_a: dict, row_b: dict) -> None:
        """
        Row A (1-day floor, M≈0.00274y) must be strictly lower than Row B (M=1.0y).

        After the fix, M_A = 1/365 ≈ 0.00274y and M_B = 1.0y.
        The gap (~0.997y) is far wider than _M_TOL (0.002y).

        Arrange / Act: as above.
        Assert:  row_a.irb_maturity_m < row_b.irb_maturity_m - _M_TOL.

        Pre-fix: both rows have M=1.0y, so this assertion also fails
        (difference ≈ 0, which is not > _M_TOL).
        """
        m_a = row_a["irb_maturity_m"]
        m_b = row_b["irb_maturity_m"]

        assert m_a < m_b - _M_TOL, (
            f"TF_LC_001.irb_maturity_m ({m_a:.5f}y) is not strictly less than "
            f"TF_LC_002.irb_maturity_m ({m_b:.4f}y) by more than {_M_TOL}y. "
            f"Expected M_A ≈ 0.00274y (1-day floor) << M_B = 1.0y (1-year floor). "
            f"If both are 1.0y the 1-day floor is not being derived from "
            f"is_short_term_trade_lc."
        )

    # ------------------------------------------------------------------
    # EAD sanity — Row A CCF=20% (Art. 166(9) trade LC exception)
    # ------------------------------------------------------------------

    def test_p1_118_row_a_ead_reflects_20pct_ccf(self, row_a: dict) -> None:
        """
        TF_LC_001 (is_short_term_trade_lc=True) must use CCF=20%.

        Under CRR Art. 166(9) the short-term trade LC carve-out applies to MLR items
        with is_short_term_trade_lc=True → CCF = 20%.
        EAD = 10,000,000 × 0.20 = 2,000,000.

        Arrange: TF_LC_001, risk_type=MLR, is_short_term_trade_lc=True, nominal=10m.
        Act:     full CRR F-IRB pipeline.
        Assert:  ead_final ≈ 2,000,000 (±1.0).
        """
        ead_a = row_a.get("ead_final", 0.0) or 0.0
        expected_ead_a = 2_000_000.0

        assert ead_a == pytest.approx(expected_ead_a, abs=1.0), (
            f"TF_LC_001.ead_final={ead_a:,.0f} != expected {expected_ead_a:,.0f}. "
            f"is_short_term_trade_lc=True must trigger CCF=20% (Art. 166(9)); "
            f"EAD = 10,000,000 × 0.20 = 2,000,000."
        )

    def test_p1_118_row_b_ead_reflects_issued_mlr_ccf(self, row_b: dict) -> None:
        """
        TF_LC_002 (is_short_term_trade_lc=False, is_obs_commitment=False) CCF check.

        With is_obs_commitment=False and risk_type=MLR, the CCF under CRR
        Art. 166(10)(c) is 20% for an issued MLR OBS item (not a commitment).
        EAD = 10,000,000 × 0.20 = 2,000,000.

        Arrange: TF_LC_002, risk_type=MLR, is_obs_commitment=False,
                 is_short_term_trade_lc=False, nominal=10m.
        Act:     full CRR F-IRB pipeline.
        Assert:  ead_final ≈ 2,000,000 (±1.0).
        """
        ead_b = row_b.get("ead_final", 0.0) or 0.0
        # is_obs_commitment=False + risk_type=MLR -> issued MLR OBS item: 20% CCF
        expected_ead_b = 2_000_000.0

        assert ead_b == pytest.approx(expected_ead_b, abs=1.0), (
            f"TF_LC_002.ead_final={ead_b:,.0f} != expected {expected_ead_b:,.0f}. "
            f"is_obs_commitment=False + risk_type=MLR must use 20% CCF for an "
            f"issued MLR OBS item."
        )
