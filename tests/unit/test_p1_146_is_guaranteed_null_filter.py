"""
Unit tests for P1.146: null ``is_guaranteed`` silently drops rows from aggregator CRM views.

Pipeline position:
    OutputAggregator._crm_reporting (generate_post_crm_detailed / generate_post_crm_summary)

Key responsibilities:
- Assert that an exposure with ``is_guaranteed=null`` appears as a single "original" row
  in ``post_crm_detailed`` (not silently discarded).
- Assert ``post_crm_detailed`` height is 4 (EXP_GUAR->2, EXP_PLAIN->1, EXP_NULL->1).
- Assert ``post_crm_summary`` CORPORATE bucket includes the null-is-guaranteed exposure.
- Assert ``pre_crm_summary`` totals are unaffected (control).

References:
    - src/rwa_calc/engine/aggregator/_crm_reporting.py lines 138, 166, 212
      (~pl.col("is_guaranteed") drops null rows — the defect under test)
    - tests/integration/test_pre_post_crm_reporting.py (existing aggregator-level pattern)
    - P1.146 scenario proposal
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest
from tests.fixtures.p1_146.p1_146 import (
    EXP_NULL_REF,
    POST_CRM_CORPORATE_EXPOSURE_COUNT,
    POST_CRM_CORPORATE_TOTAL_EAD,
    POST_CRM_DETAIL_EXPECTED_ROWS,
    PRE_CRM_TOTAL_EAD,
    build_sa_results,
)

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.engine.aggregator import OutputAggregator

EMPTY = pl.LazyFrame({"exposure_reference": pl.Series([], dtype=pl.String)})


@pytest.fixture
def crr_config() -> CalculationConfig:
    """CRR configuration for P1.146 tests."""
    return CalculationConfig.crr(reporting_date=date(2024, 12, 31))


@pytest.fixture
def aggregator() -> OutputAggregator:
    """OutputAggregator instance."""
    return OutputAggregator()


class TestP1146IsGuaranteedNullFilter:
    """Null ``is_guaranteed`` must not silently discard exposures from CRM views."""

    def test_post_crm_detailed_height_includes_null_is_guaranteed_row(
        self,
        aggregator: OutputAggregator,
        crr_config: CalculationConfig,
    ) -> None:
        """post_crm_detailed must contain 4 rows when one exposure has is_guaranteed=null.

        Pre-fix, ``_build_non_guaranteed_rows`` filters with ``~pl.col("is_guaranteed")``
        which evaluates to null (not True) for a Boolean null, so the exposure is silently
        dropped.  Post-fix it must appear as a single "original" row.

        Arrange: 3-row SA results — EXP_GUAR (True), EXP_PLAIN (False), EXP_NULL (null).
        Act:     aggregate() through OutputAggregator.
        Assert:  post_crm_detailed has 4 rows (not 3).
        """
        # Arrange
        sa_results = build_sa_results()

        # Act
        result = aggregator.aggregate(
            sa_results=sa_results,
            irb_results=EMPTY,
            slotting_results=EMPTY,
            equity_bundle=None,
            config=crr_config,
        )

        # Assert
        detailed_df = result.post_crm_detailed.collect()
        assert detailed_df.height == POST_CRM_DETAIL_EXPECTED_ROWS, (
            f"Expected {POST_CRM_DETAIL_EXPECTED_ROWS} rows in post_crm_detailed "
            f"(EXP_GUAR->2, EXP_PLAIN->1, EXP_NULL->1) but got {detailed_df.height}. "
            "Null is_guaranteed row was silently dropped by ~pl.col('is_guaranteed') filter."
        )

    def test_null_is_guaranteed_row_appears_as_original_crm_portion(
        self,
        aggregator: OutputAggregator,
        crr_config: CalculationConfig,
    ) -> None:
        """EXP_NULL must appear in post_crm_detailed as crm_portion_type='original'.

        Arrange: 3-row SA results with EXP_NULL having is_guaranteed=null.
        Act:     aggregate() through OutputAggregator.
        Assert:  exactly one row for EXP_NULL with crm_portion_type='original',
                 reporting_ead=750_000.0, reporting_rw=1.0.
        """
        # Arrange
        sa_results = build_sa_results()

        # Act
        result = aggregator.aggregate(
            sa_results=sa_results,
            irb_results=EMPTY,
            slotting_results=EMPTY,
            equity_bundle=None,
            config=crr_config,
        )

        # Assert
        detailed_df = result.post_crm_detailed.collect()
        null_rows = detailed_df.filter(pl.col("reporting_exposure_class") == "CORPORATE").filter(
            pl.col("crm_portion_type") == "original"
        )
        # Find the row with reporting_ead == 750_000 (EXP_NULL's EAD)
        exp_null_rows = null_rows.filter(pl.col("reporting_ead") == 750_000.0)
        assert len(exp_null_rows) == 1, (
            f"Expected 1 row for {EXP_NULL_REF} (reporting_ead=750_000, crm_portion_type='original') "
            f"in post_crm_detailed but found {len(exp_null_rows)}. "
            "Null is_guaranteed exposure was not rescued into the original-row path."
        )
        assert exp_null_rows["reporting_rw"][0] == pytest.approx(1.0), (
            f"Expected reporting_rw=1.0 for {EXP_NULL_REF} but got {exp_null_rows['reporting_rw'][0]}"
        )

    def test_post_crm_summary_corporate_includes_null_is_guaranteed_exposure(
        self,
        aggregator: OutputAggregator,
        crr_config: CalculationConfig,
    ) -> None:
        """post_crm_summary CORPORATE bucket must include EXP_NULL's EAD.

        Post-fix CORPORATE total_ead = EXP_PLAIN (1_000_000) + EXP_NULL (750_000)
        + EXP_GUAR unguaranteed portion (400_000) = 2_150_000.
        exposure_count = 3 (one row per CORPORATE-mapped portion).

        Arrange: 3-row SA results — EXP_GUAR (True), EXP_PLAIN (False), EXP_NULL (null).
        Act:     aggregate() through OutputAggregator.
        Assert:  post_crm_summary CORPORATE row total_ead == 2_150_000, count == 3.
        """
        # Arrange
        sa_results = build_sa_results()

        # Act
        result = aggregator.aggregate(
            sa_results=sa_results,
            irb_results=EMPTY,
            slotting_results=EMPTY,
            equity_bundle=None,
            config=crr_config,
        )

        # Assert
        summary_df = result.post_crm_summary.collect()
        corp_rows = summary_df.filter(pl.col("reporting_exposure_class") == "CORPORATE")
        assert len(corp_rows) == 1, (
            f"Expected 1 CORPORATE row in post_crm_summary but found {len(corp_rows)}"
        )
        assert corp_rows["total_ead"][0] == pytest.approx(POST_CRM_CORPORATE_TOTAL_EAD), (
            f"Expected CORPORATE total_ead={POST_CRM_CORPORATE_TOTAL_EAD} "
            f"but got {corp_rows['total_ead'][0]}. "
            "EXP_NULL (750_000) or EXP_GUAR unguaranteed (400_000) may be missing."
        )
        assert corp_rows["exposure_count"][0] == POST_CRM_CORPORATE_EXPOSURE_COUNT, (
            f"Expected CORPORATE exposure_count={POST_CRM_CORPORATE_EXPOSURE_COUNT} "
            f"but got {corp_rows['exposure_count'][0]}"
        )

    def test_pre_crm_summary_corporate_total_ead_unaffected(
        self,
        aggregator: OutputAggregator,
        crr_config: CalculationConfig,
    ) -> None:
        """pre_crm_summary total_ead must equal 2_750_000 regardless of the null fix.

        This is a control assertion: pre-CRM figures come from the original results
        frame and are not affected by the is_guaranteed null-filter bug.

        Arrange: 3-row SA results — EXP_GUAR (True), EXP_PLAIN (False), EXP_NULL (null).
        Act:     aggregate() through OutputAggregator.
        Assert:  pre_crm_summary CORPORATE total_ead == 2_750_000.
        """
        # Arrange
        sa_results = build_sa_results()

        # Act
        result = aggregator.aggregate(
            sa_results=sa_results,
            irb_results=EMPTY,
            slotting_results=EMPTY,
            equity_bundle=None,
            config=crr_config,
        )

        # Assert
        pre_crm_df = result.pre_crm_summary.collect()
        corp_rows = pre_crm_df.filter(pl.col("pre_crm_exposure_class") == "CORPORATE")
        assert len(corp_rows) == 1, (
            f"Expected 1 CORPORATE row in pre_crm_summary but found {len(corp_rows)}"
        )
        assert corp_rows["total_ead"][0] == pytest.approx(PRE_CRM_TOTAL_EAD), (
            f"Expected CORPORATE pre_crm total_ead={PRE_CRM_TOTAL_EAD} "
            f"but got {corp_rows['total_ead'][0]}"
        )
