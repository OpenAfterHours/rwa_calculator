"""
CCR-WWR-1 / P8.53: WWR gate wired into the PipelineOrchestrator.

Pipeline position:
    Loader -> HierarchyResolver -> CCRStage (apply_legal_enforceability_gate
    -> **apply_wwr_gate** -> ccr_rows_to_exposures) -> Classifier -> CRM
    -> SA Calculator -> OutputAggregator

Key responsibilities:
- Prove that apply_wwr_gate is called between apply_legal_enforceability_gate
  and ccr_rows_to_exposures in _run_ccr_stage (pipeline.py ~line 559-573).
- Post-gate: T_WWR_01 breaks out to synthetic NS "NS_WWR_01__wwr__T_WWR_01";
  T_NORMAL_01 stays in the residual "NS_WWR_01".
- Two CCR exposure rows appear in the aggregated result: one per NS.
- The synthetic row carries wwr_lgd_override=1.0 (CRR Art. 291(5)(c)).
- Exactly one CCR010 warning (ErrorCategory.CCR_WWR_SPECIFIC) in result.errors,
  zero CCR011 warnings.

Scenario (CCR-WWR-1 fixture):
    Counterparty CP_WWR_01: entity_type="institution", CQS 2, GB.
    CRR Art. 120(1) Table 3: institution CQS 2 -> 50% SA risk weight.

    Netting set NS_WWR_01 (CP_WWR_01, legally enforceable, unmargined,
    has_general_wwr_flag=False, wwr_lgd_override=null pre-gate).

    Two trades in NS_WWR_01:
        T_WWR_01:    equity derivative, GBP 10m, is_specific_wwr=True,
                     underlying_reference="CP_WWR_01_EQUITY".
                     CRR Art. 291(1)(b): issuer = counterparty -> specific WWR.
        T_NORMAL_01: IR derivative, GBP 50m, is_specific_wwr=False.

Expected post-gate structure (load-bearing assertions):
    Two CCR exposure rows:
        "ccr__NS_WWR_01"                  -- residual (T_NORMAL_01)
        "ccr__NS_WWR_01__wwr__T_WWR_01"   -- synthetic (T_WWR_01, __wwr__ separator)
    Synthetic row: wwr_lgd_override == 1.0
    Parent row:    wwr_lgd_override is null
    Diagnostics:   exactly 1 CCR010, 0 CCR011.

Out-of-scope assertions (see P8.53 §5 scope discipline):
    - No pinned EAD / RWA / risk-weight floats for the equity WWR trade.
      (equity asset-class add-on engine only partially shipped, P8.15/P8.34)
    - No IRB K-formula / LGD=100% capital effect.
      (CCR rows route through SA today; IRB consumer deferred to P8.31)

This test is RED on the unfixed pipeline because apply_wwr_gate is NOT wired:
without it both trades stay in NS_WWR_01 -> only one exposure row is produced
and the __wwr__ synthetic row never appears.

References:
    - CRR Art. 291(1)(b)  -- specific WWR definition (issuer = counterparty)
    - CRR Art. 291(5)(a)  -- separate netting-set carve-out for specific WWR
    - CRR Art. 291(5)(c)  -- LGD = 100% for IRB / wwr_lgd_override = 1.0
    - CRR Art. 291(5)(d)  -- SA risk weight = unsecured transaction
    - CRR Art. 120(1) Table 3 -- institution CQS 2 -> 50% SA RW
    - src/rwa_calc/engine/ccr/wwr.py:87 -- apply_wwr_gate
    - src/rwa_calc/engine/pipeline.py:559-573 -- _run_ccr_stage (missing gate call)
    - src/rwa_calc/engine/ccr/pipeline_adapter.py:370-398 -- synthetic-row select
      (wwr_lgd_override omitted until Change 2a)
    - tests/fixtures/ccr/ccr_wwr1_builder.py -- CCR-WWR-1 fixture
    - tests/unit/ccr/test_wwr.py -- unit-level gate tests (do not duplicate)
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import ErrorCategory, PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.fixtures.ccr.ccr_wwr1_builder import (
    CCR010_ERROR_CODE,
    CCR011_ERROR_CODE,
    CCR_WWR1_COUNTERPARTY_REF,
    EXPECTED_CCR010_COUNT,
    EXPECTED_CCR011_COUNT,
    NS_WWR_01_ID,
    SYNTHETIC_NS_ID,
    WWR_LGD_OVERRIDE_VALUE,
    build_raw_data_bundle_ccr_wwr1,
)

# ---------------------------------------------------------------------------
# Derived exposure-reference constants (load-bearing assertion strings).
# ---------------------------------------------------------------------------

#: Residual parent exposure reference (T_NORMAL_01 stays here).
_PARENT_EXPOSURE_REF: str = f"ccr__{NS_WWR_01_ID}"

#: Synthetic exposure reference — the __wwr__ separator is the anti-degenerate
#: proof that apply_wwr_gate ran: without the gate this row never exists.
_SYNTHETIC_EXPOSURE_REF: str = f"ccr__{SYNTHETIC_NS_ID}"


# ---------------------------------------------------------------------------
# Module-scoped pipeline fixture.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def ccr_wwr1_result_bundle():
    """
    Run the CCR-WWR-1 bundle through the full CRR SA pipeline.

    Returns the AggregatedResultBundle for structural assertions.

    Module-scoped: the pipeline runs once; all test methods in this module
    reuse the same result.

    Arrange:
        - Counterparty CP_WWR_01: institution, CQS 2, GB
        - External rating: S&P "A" = CQS 2
        - Netting set NS_WWR_01 (CP_WWR_01, legally enforceable, unmargined,
          has_general_wwr_flag=False)
        - Trade T_WWR_01: equity derivative, GBP 10m, is_specific_wwr=True
        - Trade T_NORMAL_01: IR derivative, GBP 50m, is_specific_wwr=False
        - Empty margin agreements and CCR collateral frames
    """
    # Arrange
    bundle = build_raw_data_bundle_ccr_wwr1()
    config = CalculationConfig.crr(
        reporting_date=date(2026, 1, 15),
        permission_mode=PermissionMode.STANDARDISED,
    )

    # Act - run the full pipeline
    return PipelineOrchestrator().run_with_data(bundle, config)


@pytest.fixture(scope="module")
def ccr_wwr1_all_rows(ccr_wwr1_result_bundle) -> list[dict]:
    """Return all CCR exposure rows from the aggregated result as a list of dicts."""
    df = ccr_wwr1_result_bundle.results.collect()
    return df.filter(pl.col("exposure_reference").str.starts_with("ccr__")).to_dicts()


@pytest.fixture(scope="module")
def ccr_wwr1_synthetic_row(ccr_wwr1_all_rows) -> dict:
    """
    Return the synthetic WWR exposure row for NS_WWR_01__wwr__T_WWR_01.

    This row only exists when apply_wwr_gate has been wired into the pipeline.
    On the unfixed engine this fixture will fail the assertion inside it,
    propagating a clear AssertionError to every test that depends on it.
    """
    # Filter to the synthetic row with __wwr__ separator
    matching = [r for r in ccr_wwr1_all_rows if r["exposure_reference"] == _SYNTHETIC_EXPOSURE_REF]
    assert len(matching) == 1, (
        f"CCR-WWR-1: expected exactly 1 synthetic CCR exposure row with "
        f"exposure_reference={_SYNTHETIC_EXPOSURE_REF!r} (the '__wwr__' separator "
        f"is the load-bearing anti-degenerate proof that apply_wwr_gate ran in the "
        f"orchestrator). Got {len(matching)} matching rows. "
        f"All CCR exposure references found: "
        f"{[r['exposure_reference'] for r in ccr_wwr1_all_rows]!r}. "
        "P8.53 fix: wire apply_wwr_gate between apply_legal_enforceability_gate "
        "and ccr_rows_to_exposures in pipeline.py::_run_ccr_stage (~line 559-573)."
    )
    return matching[0]


@pytest.fixture(scope="module")
def ccr_wwr1_parent_row(ccr_wwr1_all_rows) -> dict:
    """
    Return the residual parent exposure row for ccr__NS_WWR_01.

    T_NORMAL_01 (is_specific_wwr=False) stays in NS_WWR_01 after the gate.
    """
    matching = [r for r in ccr_wwr1_all_rows if r["exposure_reference"] == _PARENT_EXPOSURE_REF]
    assert len(matching) == 1, (
        f"CCR-WWR-1: expected exactly 1 parent CCR exposure row with "
        f"exposure_reference={_PARENT_EXPOSURE_REF!r}, got {len(matching)}. "
        f"All CCR exposure references: "
        f"{[r['exposure_reference'] for r in ccr_wwr1_all_rows]!r}."
    )
    return matching[0]


# ---------------------------------------------------------------------------
# CCR-WWR-1 acceptance test class.
# ---------------------------------------------------------------------------


class TestCCRWWR1OrchestratorGate:
    """
    CCR-WWR-1 / P8.53: four acceptance assertions proving apply_wwr_gate is
    wired into the PipelineOrchestrator.

    Pin 1 — partition row count: two CCR exposure rows total.
    Pin 2a — synthetic row identity: exposure_reference ends in __wwr__T_WWR_01.
    Pin 2b — override tag: synthetic row carries wwr_lgd_override == 1.0.
    Pin 2c — parent override null: parent row wwr_lgd_override is null.
    Pin 3  — diagnostics: exactly one CCR010, zero CCR011 in result.errors.

    All five tests are RED on the unfixed pipeline where the gate is not called.
    """

    def test_ccr_wwr1_partition_produces_two_ccr_rows(self, ccr_wwr1_all_rows: list[dict]) -> None:
        """
        Two CCR exposure rows must appear: one per post-gate netting set.

        Arrange:
            Pre-gate: 2 trades in 1 NS (NS_WWR_01).
            Post-gate (expected): T_WWR_01 -> synthetic NS; T_NORMAL_01 stays.
        Act:
            Full CRR SA + CCR pipeline via PipelineOrchestrator.
        Assert:
            Exactly 2 rows with exposure_reference starting with "ccr__".

        This assertion is RED on the unfixed pipeline where apply_wwr_gate is
        absent: both trades stay in NS_WWR_01 so only 1 CCR row is emitted.

        References: CRR Art. 291(5)(a) — each specific-WWR trade must be
        broken out into its own netting set.
        """
        # Arrange
        expected_count = 2

        # Assert
        actual_count = len(ccr_wwr1_all_rows)
        assert actual_count == expected_count, (
            f"CCR-WWR-1: expected {expected_count} CCR exposure rows (1 residual "
            f"NS_WWR_01 + 1 synthetic NS_WWR_01__wwr__T_WWR_01), got {actual_count}. "
            f"Exposure references found: "
            f"{[r['exposure_reference'] for r in ccr_wwr1_all_rows]!r}. "
            "P8.53 fix: wire apply_wwr_gate in pipeline.py::_run_ccr_stage so the "
            "specific-WWR trade T_WWR_01 is broken out into a separate netting set."
        )

    def test_ccr_wwr1_synthetic_row_has_wwr_separator(self, ccr_wwr1_synthetic_row: dict) -> None:
        """
        Synthetic exposure_reference must contain the __wwr__ separator.

        Arrange:
            T_WWR_01 (is_specific_wwr=True) in NS_WWR_01 pre-gate.
            Post-gate: synthetic NS id = NS_WWR_01__wwr__T_WWR_01.
        Act:
            Full pipeline.
        Assert:
            exposure_reference == "ccr__NS_WWR_01__wwr__T_WWR_01".

        The __wwr__ separator is the load-bearing anti-degenerate proof that
        apply_wwr_gate ran.

        References: CRR Art. 291(5)(a); wwr.py:_WWR_NS_ID_SEPARATOR = "__wwr__".
        """
        # Arrange
        expected_ref = _SYNTHETIC_EXPOSURE_REF

        # Assert
        actual_ref = ccr_wwr1_synthetic_row["exposure_reference"]
        assert actual_ref == expected_ref, (
            f"CCR-WWR-1: expected exposure_reference={expected_ref!r} "
            f"(synthetic NS with __wwr__ separator), got {actual_ref!r}. "
            "CRR Art. 291(5)(a): each specific-WWR trade must produce a "
            "separate single-trade netting set with id "
            "<original_ns_id>__wwr__<trade_id>."
        )

    def test_ccr_wwr1_synthetic_row_carries_wwr_lgd_override(
        self, ccr_wwr1_synthetic_row: dict
    ) -> None:
        """
        Synthetic exposure row must carry wwr_lgd_override == 1.0.

        Arrange:
            T_WWR_01 broken out to synthetic NS NS_WWR_01__wwr__T_WWR_01.
            apply_wwr_gate sets wwr_lgd_override = 1.0 on synthetic NS
            (CRR Art. 291(5)(c): LGD = 100% for specific WWR).
        Act:
            Full pipeline — pipeline_adapter selects wwr_lgd_override into
            the synthetic exposure row (Change 2a of P8.53).
        Assert:
            wwr_lgd_override == 1.0.

        This assertion is RED on the unfixed pipeline because:
        (a) apply_wwr_gate is not called (so no synthetic NS exists), AND
        (b) pipeline_adapter.py currently omits wwr_lgd_override from the
            synthetic-row select (second gap identified by scenario architect).

        References:
            CRR Art. 291(5)(c) — LGD = 100% for specific-WWR exposure.
            sa_ccr_factors.py:CCR_WWR_SPECIFIC_LGD_OVERRIDE = 1.0.
        """
        # Arrange
        expected_override = WWR_LGD_OVERRIDE_VALUE  # 1.0

        # Act: read from the exposure row (most-downstream observable point)
        actual_override = ccr_wwr1_synthetic_row.get("wwr_lgd_override")

        # Assert
        assert actual_override == expected_override, (
            f"CCR-WWR-1: expected wwr_lgd_override={expected_override} on synthetic "
            f"row {_SYNTHETIC_EXPOSURE_REF!r}, got {actual_override!r}. "
            "CRR Art. 291(5)(c): the synthetic netting set must carry "
            "wwr_lgd_override=1.0 (LGD=100%) so the IRB consumer can apply "
            "the full LGD floor. "
            "P8.53 Change 2a: pipeline_adapter.py must include wwr_lgd_override "
            "in the synthetic-row select expression."
        )

    def test_ccr_wwr1_parent_row_override_is_null(self, ccr_wwr1_parent_row: dict) -> None:
        """
        Residual parent exposure row must have wwr_lgd_override = null.

        Arrange:
            T_NORMAL_01 (is_specific_wwr=False) stays in NS_WWR_01 residual.
            NS_WWR_01 wwr_lgd_override is null in the pre-gate input frame.
        Act:
            Full pipeline.
        Assert:
            wwr_lgd_override is null / absent on the parent row.

        This ensures the gate does not contaminate the clean residual NS.

        References: CRR Art. 291(5)(a) — only specific-WWR trades are carved out.
        """
        # Arrange / Act
        actual_override = ccr_wwr1_parent_row.get("wwr_lgd_override")

        # Assert: null means either the key is absent or the value is None
        assert actual_override is None, (
            f"CCR-WWR-1: expected wwr_lgd_override=null on parent row "
            f"{_PARENT_EXPOSURE_REF!r} (T_NORMAL_01 has no specific WWR), "
            f"got {actual_override!r}. "
            "CRR Art. 291(5)(a): the residual netting set (containing non-WWR "
            "trades) must NOT inherit the wwr_lgd_override=1.0 tag."
        )

    def test_ccr_wwr1_exactly_one_ccr010_warning(self, ccr_wwr1_result_bundle) -> None:
        """
        Result bundle must contain exactly one CCR010 warning for NS_WWR_01.

        Arrange:
            NS_WWR_01 contains exactly 1 specific-WWR trade (T_WWR_01).
            One CCR010 is emitted per original NS with >= 1 specific-WWR trade.
        Act:
            Full pipeline; inspect AggregatedResultBundle.errors.
        Assert:
            len([e for e in result.errors if e.code == "CCR010"]) == 1.
            The CCR010 carries counterparty_reference="CP_WWR_01",
            category=ErrorCategory.CCR_WWR_SPECIFIC,
            and regulatory_reference referencing Art. 291.

        This assertion is RED on the unfixed pipeline because apply_wwr_gate
        is not called and no CCR010 is ever emitted.

        References: CRR Art. 291(4)-(5); wwr.py:CCR_WWR_SPECIFIC_ERROR_CODE.
        """
        # Arrange
        all_errors = ccr_wwr1_result_bundle.errors

        # Act: filter to CCR010 errors
        ccr010_errors = [e for e in all_errors if getattr(e, "code", None) == CCR010_ERROR_CODE]

        # Assert: count
        assert len(ccr010_errors) == EXPECTED_CCR010_COUNT, (
            f"CCR-WWR-1: expected {EXPECTED_CCR010_COUNT} CCR010 warning(s) "
            f"(one per original NS with specific-WWR trades), "
            f"got {len(ccr010_errors)}. "
            f"All error codes: {[getattr(e, 'code', None) for e in all_errors]!r}. "
            "P8.53 fix: wire apply_wwr_gate in the orchestrator; its error list "
            "must be propagated to AggregatedResultBundle.errors."
        )

        # Assert: counterparty reference on the sole CCR010
        ccr010 = ccr010_errors[0]
        actual_cp_ref = getattr(ccr010, "counterparty_reference", None)
        assert actual_cp_ref == CCR_WWR1_COUNTERPARTY_REF, (
            f"CCR-WWR-1: CCR010 counterparty_reference should be "
            f"{CCR_WWR1_COUNTERPARTY_REF!r}, got {actual_cp_ref!r}."
        )

        # Assert: category
        actual_category = getattr(ccr010, "category", None)
        assert actual_category == ErrorCategory.CCR_WWR_SPECIFIC, (
            f"CCR-WWR-1: CCR010 category should be "
            f"ErrorCategory.CCR_WWR_SPECIFIC, got {actual_category!r}."
        )

        # Assert: regulatory reference mentions Art. 291
        actual_reg_ref = getattr(ccr010, "regulatory_reference", "") or ""
        assert "291" in actual_reg_ref, (
            f"CCR-WWR-1: CCR010 regulatory_reference should reference Art. 291, "
            f"got {actual_reg_ref!r}."
        )

    def test_ccr_wwr1_zero_ccr011_warnings(self, ccr_wwr1_result_bundle) -> None:
        """
        No CCR011 warnings should appear (has_general_wwr_flag=False).

        Arrange:
            NS_WWR_01 has_general_wwr_flag=False -> no general-WWR condition.
            CCR011 is emitted only when has_general_wwr_flag=True.
        Act:
            Full pipeline; inspect AggregatedResultBundle.errors.
        Assert:
            No errors with code "CCR011" in result.errors.

        References: CRR Art. 291(1)(a), 291(6); wwr.py:CCR_WWR_GENERAL_ERROR_CODE.
        """
        # Arrange
        all_errors = ccr_wwr1_result_bundle.errors

        # Act
        ccr011_errors = [e for e in all_errors if getattr(e, "code", None) == CCR011_ERROR_CODE]

        # Assert
        assert len(ccr011_errors) == EXPECTED_CCR011_COUNT, (
            f"CCR-WWR-1: expected {EXPECTED_CCR011_COUNT} CCR011 warning(s) "
            f"(has_general_wwr_flag=False -> no general-WWR condition), "
            f"got {len(ccr011_errors)}. "
            "CRR Art. 291(1)(a): CCR011 is only emitted when has_general_wwr_flag=True."
        )
