"""Unit tests for the CreditRiskCalc.reconcile calculation-reuse seam.

reconcile(settings, calculation=...) lets a caller hand in an already-completed
CalculationResponse so the embedded full pipeline run is skipped. The caller
owns freshness verification (see api/run_index.py); the seam itself must only:
- skip self.calculate() when a calculation is supplied,
- keep the failed-calculation guard operating on the supplied response,
- leave the default (calculation=None) path unchanged.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import polars as pl
import pytest
from tests.fixtures.api_validation.build_mandatory_only import write_mandatory_minimum

from rwa_calc.analysis.recon_registry import ComponentMapping, LegacyColumnMapping
from rwa_calc.api.models import APIError, CalculationResponse, SummaryStatistics
from rwa_calc.api.reconciliation import ReconciliationSettings
from rwa_calc.api.service import CreditRiskCalc

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def our_calc(tmp_path: Path) -> CreditRiskCalc:
    """A CreditRiskCalc over the mandatory-minimum single-loan data set."""
    data_dir = write_mandatory_minimum(tmp_path)
    return CreditRiskCalc(
        data_path=data_dir,
        framework="CRR",
        reporting_date=date(2025, 1, 1),
        permission_mode="standardised",
    )


def _write_legacy(tmp_path: Path, our_ref: str, our_rwa: float) -> Path:
    """Legacy CSV holding our loan with an exactly-matching RWA."""
    legacy = tmp_path / "legacy.csv"
    pl.DataFrame({"loan_id": [our_ref], "RWA": [our_rwa]}).write_csv(legacy)
    return legacy


def _settings(legacy: Path) -> ReconciliationSettings:
    return ReconciliationSettings(
        legacy_file=legacy.resolve(),
        legacy_format="csv",
        mapping=LegacyColumnMapping(
            legacy_keys=("loan_id",),
            our_keys=("exposure_reference",),
            components={"rwa": ComponentMapping("RWA")},
        ),
    )


def _failed_response(tmp_path: Path) -> CalculationResponse:
    """A failed CalculationResponse carrying one identifiable error."""
    return CalculationResponse(
        success=False,
        framework="CRR",
        reporting_date=date(2025, 1, 1),
        summary=SummaryStatistics(
            total_ead=Decimal("0"),
            total_rwa=Decimal("0"),
            exposure_count=0,
            average_risk_weight=Decimal("0"),
        ),
        results_path=tmp_path / "no_results.parquet",
        errors=[
            APIError(
                code="LOAD001",
                message="prior calculation failed",
                severity="critical",
                category="load",
            )
        ],
    )


# =============================================================================
# Tests
# =============================================================================


class TestReconcileWithSuppliedCalculation:
    def test_supplied_calculation_skips_pipeline(
        self, our_calc: CreditRiskCalc, tmp_path: Path
    ) -> None:
        # Arrange: one genuine run, then make any further calculate() call blow up.
        prior = our_calc.calculate()
        assert prior.success
        results = prior.collect_results()
        legacy = _write_legacy(
            tmp_path, results["exposure_reference"][0], float(results["rwa_final"][0])
        )

        # Act: reconcile must not invoke the pipeline again.
        with patch.object(
            our_calc, "calculate", side_effect=AssertionError("pipeline re-run")
        ) as spy:
            response = our_calc.reconcile(_settings(legacy), calculation=prior)

        # Assert: the reuse path produced a normal, matching reconciliation.
        spy.assert_not_called()
        assert response.success
        buckets = {
            r["row_bucket"]: r["count"] for r in response.collect_summary_by_bucket().to_dicts()
        }
        assert buckets.get("exact_match") == 1

    def test_supplied_failed_calculation_short_circuits(self, tmp_path: Path) -> None:
        # Arrange: a failed response supplied by the caller must surface its own
        # errors — never fall through to the legacy join (which would silently
        # mark every legacy row missing_left and report success).
        calc = CreditRiskCalc(
            data_path=tmp_path,
            framework="CRR",
            reporting_date=date(2025, 1, 1),
        )
        legacy = _write_legacy(tmp_path, "LN-X", 1_000_000.0)
        failed = _failed_response(tmp_path)

        # Act
        with patch.object(calc, "calculate", side_effect=AssertionError("pipeline re-run")) as spy:
            response = calc.reconcile(_settings(legacy), calculation=failed)

        # Assert
        spy.assert_not_called()
        assert not response.success
        assert [e.code for e in response.errors] == ["LOAD001"]

    def test_default_path_still_calculates(self, tmp_path: Path) -> None:
        # Arrange: without a supplied calculation the seam must keep calling
        # calculate() exactly as before.
        calc = CreditRiskCalc(
            data_path=tmp_path,
            framework="CRR",
            reporting_date=date(2025, 1, 1),
        )
        legacy = _write_legacy(tmp_path, "LN-X", 1_000_000.0)
        failed = _failed_response(tmp_path)

        # Act
        with patch.object(calc, "calculate", return_value=failed) as spy:
            response = calc.reconcile(_settings(legacy))

        # Assert
        spy.assert_called_once()
        assert not response.success
        assert [e.code for e in response.errors] == ["LOAD001"]
