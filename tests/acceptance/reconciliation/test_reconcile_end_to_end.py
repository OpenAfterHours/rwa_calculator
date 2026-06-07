"""End-to-end acceptance test for CreditRiskCalc.reconcile().

Exercises the full API stack — calculate() -> legacy load (scaling + value_map)
-> reconciliation -> export — against a real (single-loan) data set. The rich
per-component bucketing matrix is covered at the engine level in
tests/unit/engine/test_reconciliation.py; this test proves the wiring and export.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl
import pytest

from rwa_calc.api import CreditRiskCalc
from rwa_calc.api.reconciliation import ReconciliationSettings
from rwa_calc.contracts.config import ComponentMapping, LegacyColumnMapping
from tests.fixtures.api_validation.build_mandatory_only import write_mandatory_minimum


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
    """Legacy CSV: our loan (RWA in millions, class synonym) + a phantom row."""
    legacy = tmp_path / "legacy.csv"
    pl.DataFrame(
        {
            "loan_id": [our_ref, "PHANTOM-001"],
            "RWA_m": [our_rwa / 1_000_000.0, 0.123],
            "Asset_Class": ["CORP", "RETAIL"],
        }
    ).write_csv(legacy)
    return legacy


def _settings(legacy: Path) -> ReconciliationSettings:
    return ReconciliationSettings(
        legacy_file=legacy.resolve(),
        legacy_format="csv",
        mapping=LegacyColumnMapping(
            legacy_keys=("loan_id",),
            our_keys=("exposure_reference",),
            components={
                "rwa": ComponentMapping("RWA_m", scale=1_000_000.0),
                "exposure_class": ComponentMapping(
                    "Asset_Class", value_map={"CORP": "corporate", "RETAIL": "retail"}
                ),
            },
        ),
    )


class TestReconcileEndToEnd:
    def test_exact_match_and_phantom_legacy_row(
        self, our_calc: CreditRiskCalc, tmp_path: Path
    ) -> None:
        # Arrange: derive the legacy file from our actual results.
        our = our_calc.calculate()
        assert our.success
        results = our.collect_results()
        our_ref = results["exposure_reference"][0]
        our_rwa = float(results["rwa_final"][0])
        legacy = _write_legacy(tmp_path, our_ref, our_rwa)

        # Act
        response = our_calc.reconcile(_settings(legacy))

        # Assert: our loan reconciles exactly (millions scaled, CORP->corporate);
        # the phantom legacy row is missing_left.
        assert response.success
        buckets = {
            r["row_bucket"]: r["count"]
            for r in response.collect_summary_by_bucket().to_dicts()
        }
        assert buckets.get("exact_match") == 1
        assert buckets.get("missing_left") == 1

    def test_totals_tie_out_includes_phantom(
        self, our_calc: CreditRiskCalc, tmp_path: Path
    ) -> None:
        our = our_calc.calculate()
        results = our.collect_results()
        our_ref = results["exposure_reference"][0]
        our_rwa = float(results["rwa_final"][0])
        legacy = _write_legacy(tmp_path, our_ref, our_rwa)

        response = our_calc.reconcile(_settings(legacy))

        tie = response.collect_totals_tie_out()
        rwa_row = tie.filter(pl.col("component") == "rwa").row(0, named=True)
        assert rwa_row["our_total"] == pytest.approx(our_rwa)
        assert rwa_row["legacy_total"] == pytest.approx(our_rwa + 123_000.0)

    def test_reconcile_accepts_toml_config_path(
        self, our_calc: CreditRiskCalc, tmp_path: Path
    ) -> None:
        from rwa_calc.api.reconciliation import dump_reconciliation_config

        our = our_calc.calculate()
        results = our.collect_results()
        legacy = _write_legacy(tmp_path, results["exposure_reference"][0], float(results["rwa_final"][0]))
        cfg = tmp_path / "reconciliation.toml"
        cfg.write_text(dump_reconciliation_config(_settings(legacy)))

        response = our_calc.reconcile(cfg)

        assert response.success

    def test_excel_export_writes_expected_sheets(
        self, our_calc: CreditRiskCalc, tmp_path: Path
    ) -> None:
        pytest.importorskip("xlsxwriter")
        our = our_calc.calculate()
        results = our.collect_results()
        legacy = _write_legacy(tmp_path, results["exposure_reference"][0], float(results["rwa_final"][0]))
        response = our_calc.reconcile(_settings(legacy))

        out = tmp_path / "recon.xlsx"
        export = response.to_excel(out)

        assert out.exists()
        assert export.files == [out]

    def test_csv_export_writes_one_file_per_frame(
        self, our_calc: CreditRiskCalc, tmp_path: Path
    ) -> None:
        our = our_calc.calculate()
        results = our.collect_results()
        legacy = _write_legacy(tmp_path, results["exposure_reference"][0], float(results["rwa_final"][0]))
        response = our_calc.reconcile(_settings(legacy))

        export = response.to_csv(tmp_path / "csvout")

        names = {p.name for p in export.files}
        assert "reconciliation_summary_by_component.csv" in names
        assert "reconciliation_totals_tie_out.csv" in names
