"""
R1 acceptance — negative on-balance amounts must never make a gross-exposure
template cell report a negative figure.

Scenario (tests/fixtures/r1_negative_gross/r1_negative_gross.py):
    CP_R1_IRB (F-IRB corporate): LN_R1_POS (+1,000,000) and LN_R1_DEP (-200,000),
        both under netting_agreement_reference NET_R1 (the on-balance netting
        convention, CRR Art. 195/219).
    CP_R1_BARE (SA corporate): LN_R1_BARE (-50,000), no netting reference.

The raw drawn/interest carriers seal negative for the deposit and the bare
loan. The floored reporting carriers (aggregator ``_add_reporting_projection``)
clip them at 0, so:
    - C 08.03 / CR6 IRB on-balance gross drawn == 1,000,000 (clip(1,000,000) +
      clip(-200,000)) — NOT the raw 800,000.
    - C 07.00 / CR4 SA on-balance gross drawn == 0 (clip(-50,000)) — NOT -50,000.

The EAD path already floored negatives, so ead_final is unchanged by the fix.

References:
    - CRR Art. 111 (SA gross exposure value); Art. 166 (IRB exposure value)
    - CRR Art. 195/219 (on-balance-sheet netting)
    - src/rwa_calc/engine/aggregator/aggregator.py::_add_reporting_projection
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl
import pytest
from tests.fixtures.acceptance_pipeline import run_parquet_pipeline
from tests.fixtures.r1_negative_gross.r1_negative_gross import (
    IRB_GROSS_DRAWN_FLOORED,
    IRB_GROSS_DRAWN_RAW,
    LOAN_DEP,
    SA_GROSS_DRAWN_FLOORED,
)

from rwa_calc.contracts.config import CalculationConfig, PermissionMode
from rwa_calc.reporting.corep.generator import COREPGenerator
from rwa_calc.reporting.pillar3.generator import Pillar3Generator

_FIXTURES_DIR = Path(__file__).parent.parent.parent / "fixtures" / "r1_negative_gross"
_GROSS_COLS = (
    "reporting_gross_drawn",
    "reporting_gross_interest",
    "reporting_gross_nominal",
    "reporting_gross_undrawn",
)


def _col_min(frame: pl.DataFrame, ref: str) -> float:
    """Non-null min of a template column as a float (cells fill_null to 0.0)."""
    value = frame.select(pl.col(ref).fill_null(0.0).min()).item()
    return float(value) if value is not None else 0.0


def _col_max(frame: pl.DataFrame, ref: str) -> float:
    """Non-null max of a template column as a float."""
    value = frame.select(pl.col(ref).fill_null(0.0).max()).item()
    return float(value) if value is not None else 0.0


def _run():
    config = CalculationConfig.basel_3_1(
        reporting_date=date(2030, 1, 1),
        permission_mode=PermissionMode.IRB,
        gcra_amount=0.0,
        sa_t2_credit=0.0,
        art_40_deductions=0.0,
    )
    return run_parquet_pipeline(_FIXTURES_DIR, config)


class TestR1NegativeGrossCarriers:
    """Negative on-balance amounts floored in the reporting gross carriers."""

    @pytest.fixture(scope="class")
    def result(self):
        return _run()

    @pytest.fixture(scope="class")
    def results_df(self, result) -> pl.DataFrame:
        return result.results.collect()

    @pytest.fixture(scope="class")
    def corep(self, result):
        return COREPGenerator().generate_from_lazyframe(result.results, framework="BASEL_3_1")

    @pytest.fixture(scope="class")
    def pillar3(self, result):
        return Pillar3Generator().generate_from_lazyframe(result.results, framework="BASEL_3_1")

    def test_sealed_edge_carries_gross_carriers(self, results_df: pl.DataFrame) -> None:
        """The four floored gross carriers are sealed on the aggregator exit."""
        assert all(c in results_df.columns for c in _GROSS_COLS)

    def test_gross_carriers_are_floored_clip_of_raw(self, results_df: pl.DataFrame) -> None:
        """reporting_gross_drawn == max(0, drawn_amount) on every row."""
        mismatch = results_df.filter(
            pl.col("reporting_gross_drawn") != pl.col("drawn_amount").clip(lower_bound=0.0)
        )
        assert mismatch.height == 0

    def test_deposit_leg_negative_raw_but_floored_carrier_zero(
        self, results_df: pl.DataFrame
    ) -> None:
        """The netted deposit keeps its negative raw drawn but floors the carrier."""
        dep = results_df.filter(pl.col("exposure_reference") == LOAN_DEP)
        assert dep.height == 1
        assert dep["drawn_amount"][0] < 0.0
        assert dep["reporting_gross_drawn"][0] == 0.0

    def test_ead_final_unaffected_and_non_negative(self, results_df: pl.DataFrame) -> None:
        """EAD is floored/unaffected — no ead_final goes negative."""
        assert _col_min(results_df, "ead_final") >= 0.0

    def test_c08_03_col_0010_floored_not_raw(self, corep) -> None:
        """C 08.03 IRB on-balance gross (col 0010) equals the floored hand-calc."""
        total = 0.0
        for frame in corep.c08_03.values():
            if "0010" in frame.columns:
                # Single PD band populated → the max is the class total.
                total += _col_max(frame, "0010")
                assert _col_min(frame, "0010") >= 0.0
        assert total == pytest.approx(IRB_GROSS_DRAWN_FLOORED)
        assert total != pytest.approx(IRB_GROSS_DRAWN_RAW)

    def test_c07_00_col_0010_non_negative(self, corep) -> None:
        """C 07.00 SA on-balance gross (col 0010) never goes negative."""
        for frame in corep.c07_00.values():
            if "0010" in frame.columns:
                assert _col_min(frame, "0010") == pytest.approx(SA_GROSS_DRAWN_FLOORED)
                assert _col_min(frame, "0010") >= 0.0

    def test_cr4_col_a_non_negative(self, pillar3) -> None:
        """CR4 SA on-balance gross (col a) never goes negative."""
        assert pillar3.cr4 is not None
        assert _col_min(pillar3.cr4, "a") >= 0.0

    def test_cr6_col_b_floored(self, pillar3) -> None:
        """CR6 IRB on-balance gross (col b) is floored — the band row equals 1,000,000."""
        frame = pillar3.cr6["corporate"]
        assert _col_min(frame, "b") >= 0.0
        assert _col_max(frame, "b") == pytest.approx(IRB_GROSS_DRAWN_FLOORED)
