"""Cross-template COREP behaviours (C 07 + C 08 asserted together: combined generation, Excel export, substitution flows, netting, collateral method split, credit derivatives, equity transitional, sign convention).

Split from tests/unit/test_corep.py (Phase 7 Sn) — bodies verbatim.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import polars as pl
import pytest

from rwa_calc.reporting.corep.generator import COREPGenerator, COREPTemplateBundle
from tests.unit.reporting.corep._builders import (
    _combined_results,
    _get_total_row,
    _irb_results,
    _irb_results_with_phase2_cols,
    _sa_results,
    _sa_results_with_phase2_cols,
)

XLSXWRITER_AVAILABLE = bool(sys.modules.get("xlsxwriter")) or (
    importlib.util.find_spec("xlsxwriter") is not None
)


def _sa_results_with_bs_split() -> pl.LazyFrame:
    """SA results with on-BS and off-BS exposures for Section 2 testing."""
    return pl.LazyFrame(
        {
            "exposure_reference": ["SA_ON_1", "SA_ON_2", "SA_OFF_1"],
            "approach_applied": ["standardised"] * 3,
            "exposure_class": ["corporate", "corporate", "corporate"],
            "drawn_amount": [1000.0, 2000.0, 0.0],
            "undrawn_amount": [0.0, 0.0, 500.0],
            "ead_final": [1000.0, 2000.0, 400.0],
            "rwa_final": [1000.0, 2000.0, 400.0],
            "risk_weight": [1.0, 1.0, 1.0],
            "scra_provision_amount": [10.0, 20.0, 5.0],
            "gcra_provision_amount": [5.0, 10.0, 2.5],
            "sa_cqs": [3, 3, 3],
            "counterparty_reference": ["CP_A", "CP_B", "CP_C"],
            "bs_type": ["ONB", "ONB", "OFB"],
        }
    )


def _sa_results_with_substitution() -> pl.LazyFrame:
    """SA results with CRM substitution columns for Task 2H testing.

    Scenario: Corporate exposure SA_CORP_2 has a guarantee from an institution.
    The guaranteed portion (500) flows out of corporate class into institution class.
    """
    return pl.LazyFrame(
        {
            "exposure_reference": [
                "SA_CORP_1",
                "SA_CORP_2",
                "SA_INST_1",
                "SA_RETAIL_1",
            ],
            "approach_applied": ["standardised"] * 4,
            "exposure_class": [
                "corporate",
                "corporate",
                "institution",
                "retail_other",
            ],
            "drawn_amount": [1000.0, 2000.0, 3000.0, 200.0],
            "undrawn_amount": [500.0, 0.0, 0.0, 50.0],
            "ead_final": [1200.0, 2000.0, 3000.0, 225.0],
            "rwa_final": [1140.0, 1900.0, 600.0, 168.75],
            "risk_weight": [1.0, 1.0, 0.20, 0.75],
            "scra_provision_amount": [10.0, 20.0, 0.0, 2.0],
            "gcra_provision_amount": [5.0, 10.0, 15.0, 1.0],
            "sa_cqs": [3, 0, 2, 0],
            "counterparty_reference": ["CP_A", "CP_B", "CP_D", "CP_E"],
            "guaranteed_portion": [0.0, 500.0, 0.0, 0.0],
            # Pre-CRM: both corporates are in "corporate" class
            "pre_crm_exposure_class": [
                "corporate",
                "corporate",
                "institution",
                "retail_other",
            ],
            # Post-CRM: SA_CORP_2's guaranteed portion migrates to "institution"
            "post_crm_exposure_class_guaranteed": [
                "corporate",
                "institution",
                "institution",
                "retail_other",
            ],
        }
    )


def _irb_results_with_substitution() -> pl.LazyFrame:
    """IRB results with CRM substitution columns for Task 2H testing.

    Scenario: Corporate IRB exposure IRB_CORP_2 guaranteed by institution.
    The guaranteed portion (800) flows out of corporate class into institution class.
    """
    return pl.LazyFrame(
        {
            "exposure_reference": ["IRB_CORP_1", "IRB_CORP_2", "IRB_INST_1"],
            "approach_applied": [
                "foundation_irb",
                "foundation_irb",
                "foundation_irb",
            ],
            "exposure_class": ["corporate", "corporate", "institution"],
            "drawn_amount": [5000.0, 3000.0, 2000.0],
            "undrawn_amount": [1000.0, 0.0, 0.0],
            "ead_final": [5500.0, 3000.0, 2000.0],
            "rwa_final": [3850.0, 1800.0, 600.0],
            "risk_weight": [0.70, 0.60, 0.30],
            "pd_floored": [0.005, 0.01, 0.002],
            "lgd_floored": [0.45, 0.45, 0.45],
            "irb_maturity_m": [2.5, 3.0, 1.5],
            "expected_loss": [12.375, 13.5, 1.8],
            "irb_capital_k": [0.056, 0.048, 0.024],
            "provision_held": [15.0, 10.0, 3.0],
            "scra_provision_amount": [10.0, 5.0, 2.0],
            "gcra_provision_amount": [5.0, 5.0, 1.0],
            "counterparty_reference": ["CP_X", "CP_Y", "CP_W"],
            "bs_type": ["ONB", "ONB", "ONB"],
            "guaranteed_portion": [0.0, 800.0, 0.0],
            "pre_crm_exposure_class": ["corporate", "corporate", "institution"],
            "post_crm_exposure_class_guaranteed": [
                "corporate",
                "institution",
                "institution",
            ],
        }
    )


def _sa_results_with_netting() -> pl.LazyFrame:
    """SA results with on_bs_netting_amount for Task 3D testing."""
    return pl.LazyFrame(
        {
            "exposure_reference": [
                "SA_CORP_1",
                "SA_CORP_2",
                "SA_INST_1",
                "SA_RETAIL_1",
            ],
            "approach_applied": ["standardised"] * 4,
            "exposure_class": ["corporate", "corporate", "institution", "retail_other"],
            "drawn_amount": [1000.0, 2000.0, 3000.0, 500.0],
            "undrawn_amount": [500.0, 0.0, 0.0, 100.0],
            "ead_final": [1200.0, 2000.0, 3000.0, 550.0],
            "rwa_final": [1200.0, 2000.0, 600.0, 412.5],
            "risk_weight": [1.00, 1.00, 0.20, 0.75],
            "scra_provision_amount": [10.0, 20.0, 0.0, 5.0],
            "gcra_provision_amount": [5.0, 10.0, 15.0, 2.0],
            "collateral_adjusted_value": [0.0, 0.0, 0.0, 0.0],
            "guaranteed_portion": [0.0, 0.0, 0.0, 0.0],
            "sa_cqs": [3, None, 2, None],
            "counterparty_reference": ["CP_A", "CP_B", "CP_D", "CP_E"],
            # Netting amounts: CORP_1 has 150 netting, INST_1 has 200
            "on_bs_netting_amount": [150.0, 0.0, 200.0, 0.0],
        }
    )


def _irb_results_with_netting() -> pl.LazyFrame:
    """IRB results with on_bs_netting_amount for Task 3D testing."""
    return pl.LazyFrame(
        {
            "exposure_reference": ["IRB_CORP_1", "IRB_CORP_2", "IRB_INST_1"],
            "approach_applied": ["foundation_irb", "foundation_irb", "foundation_irb"],
            "exposure_class": ["corporate", "corporate", "institution"],
            "drawn_amount": [5000.0, 3000.0, 2000.0],
            "undrawn_amount": [1000.0, 0.0, 0.0],
            "ead_final": [5500.0, 3000.0, 2000.0],
            "rwa_final": [3850.0, 1800.0, 600.0],
            "risk_weight": [0.70, 0.60, 0.30],
            "pd_floored": [0.005, 0.01, 0.002],
            "lgd_floored": [0.45, 0.45, 0.45],
            "irb_maturity_m": [2.5, 3.0, 1.5],
            "expected_loss": [12.375, 13.5, 1.8],
            "irb_capital_k": [0.056, 0.048, 0.024],
            "provision_held": [15.0, 10.0, 3.0],
            "el_shortfall": [0.0, 3.5, 0.0],
            "el_excess": [2.625, 0.0, 1.2],
            "scra_provision_amount": [10.0, 5.0, 2.0],
            "gcra_provision_amount": [5.0, 5.0, 1.0],
            "counterparty_reference": ["CP_X", "CP_Y", "CP_W"],
            # Netting amounts: CORP_1 has 300 netting
            "on_bs_netting_amount": [300.0, 0.0, 0.0],
        }
    )


def _sa_results_with_equity_transitional() -> pl.LazyFrame:
    """SA results with equity transitional columns for Task 3I testing."""
    return pl.LazyFrame(
        {
            "exposure_reference": [
                "SA_EQ_HR_1",
                "SA_EQ_OTHER_1",
                "SA_IRB_HR_1",
                "SA_IRB_OTHER_1",
                "SA_CORP_1",
            ],
            "approach_applied": ["standardised"] * 5,
            "exposure_class": ["equity"] * 4 + ["corporate"],
            "drawn_amount": [100.0, 200.0, 150.0, 300.0, 1000.0],
            "undrawn_amount": [0.0] * 5,
            "ead_final": [100.0, 200.0, 150.0, 300.0, 1000.0],
            "rwa_final": [400.0, 500.0, 600.0, 750.0, 1000.0],
            "risk_weight": [4.00, 2.50, 4.00, 2.50, 1.00],
            "scra_provision_amount": [0.0] * 5,
            "gcra_provision_amount": [0.0] * 5,
            "collateral_adjusted_value": [0.0] * 5,
            "guaranteed_portion": [0.0] * 5,
            "sa_cqs": [None] * 5,
            "counterparty_reference": ["CP_A", "CP_B", "CP_C", "CP_D", "CP_E"],
            "equity_transitional_approach": [
                "sa_transitional",
                "sa_transitional",
                "irb_transitional",
                "irb_transitional",
                None,
            ],
            "equity_higher_risk": [True, False, True, False, None],
        }
    )


def _sa_results_with_collateral_split() -> pl.LazyFrame:
    """SA results with per-type collateral columns for collateral method split tests."""
    return pl.LazyFrame(
        {
            "exposure_reference": ["SA_CORP_1", "SA_CORP_2", "SA_INST_1"],
            "approach_applied": ["standardised"] * 3,
            "exposure_class": ["corporate", "corporate", "institution"],
            "drawn_amount": [1000.0, 2000.0, 3000.0],
            "undrawn_amount": [0.0, 0.0, 0.0],
            "ead_final": [1000.0, 2000.0, 3000.0],
            "rwa_final": [1000.0, 2000.0, 600.0],
            "risk_weight": [1.0, 1.0, 0.2],
            "scra_provision_amount": [10.0, 20.0, 0.0],
            "gcra_provision_amount": [5.0, 10.0, 15.0],
            "sa_cqs": [3, 0, 2],
            "counterparty_reference": ["CP_A", "CP_B", "CP_D"],
            # Collateral columns
            "collateral_adjusted_value": [150.0, 0.0, 200.0],
            "collateral_market_value": [180.0, 0.0, 250.0],
            "collateral_financial_value": [100.0, 0.0, 200.0],
            "collateral_cash_value": [50.0, 0.0, 100.0],
            "collateral_re_value": [30.0, 0.0, 0.0],
            "collateral_receivables_value": [10.0, 0.0, 0.0],
            "collateral_other_physical_value": [10.0, 0.0, 0.0],
            "guaranteed_portion": [0.0, 500.0, 0.0],
        }
    )


def _irb_results_with_collateral_split() -> pl.LazyFrame:
    """IRB results with per-type collateral columns for collateral method split tests."""
    return pl.LazyFrame(
        {
            "exposure_reference": ["IRB_CORP_1", "IRB_CORP_2"],
            "approach_applied": ["foundation_irb", "foundation_irb"],
            "exposure_class": ["corporate", "corporate"],
            "drawn_amount": [5000.0, 3000.0],
            "undrawn_amount": [1000.0, 0.0],
            "ead_final": [5500.0, 3000.0],
            "rwa_final": [3850.0, 1800.0],
            "risk_weight": [0.70, 0.60],
            "pd_floored": [0.005, 0.01],
            "lgd_floored": [0.45, 0.45],
            "irb_maturity_m": [2.5, 3.0],
            "expected_loss": [12.375, 13.5],
            "irb_capital_k": [0.056, 0.048],
            "provision_held": [15.0, 10.0],
            "el_shortfall": [0.0, 3.5],
            "el_excess": [2.625, 0.0],
            "scra_provision_amount": [10.0, 5.0],
            "gcra_provision_amount": [5.0, 5.0],
            "counterparty_reference": ["CP_X", "CP_Y"],
            # Collateral columns
            "collateral_financial_value": [200.0, 0.0],
            "collateral_cash_value": [80.0, 0.0],
            "collateral_re_value": [150.0, 100.0],
            "collateral_receivables_value": [50.0, 0.0],
            "collateral_other_physical_value": [30.0, 20.0],
            "guaranteed_portion": [0.0, 500.0],
        }
    )


def _sa_results_with_credit_derivatives() -> pl.LazyFrame:
    """SA results with protection_type distinguishing guarantees from credit derivatives."""
    return pl.LazyFrame(
        {
            "exposure_reference": ["SA_CORP_1", "SA_CORP_2", "SA_CORP_3", "SA_INST_1"],
            "approach_applied": ["standardised"] * 4,
            "exposure_class": ["corporate", "corporate", "corporate", "institution"],
            "drawn_amount": [1000.0, 2000.0, 1500.0, 3000.0],
            "undrawn_amount": [0.0, 0.0, 0.0, 0.0],
            "ead_final": [1000.0, 2000.0, 1500.0, 3000.0],
            "rwa_final": [1000.0, 2000.0, 1500.0, 600.0],
            "risk_weight": [1.0, 1.0, 1.0, 0.2],
            "scra_provision_amount": [10.0, 20.0, 15.0, 0.0],
            "gcra_provision_amount": [5.0, 10.0, 5.0, 15.0],
            "sa_cqs": [3, 0, 2, 2],
            "counterparty_reference": ["CP_A", "CP_B", "CP_C", "CP_D"],
            # Protection split: CORP_1 has guarantee, CORP_2 has credit derivative
            "guaranteed_portion": [200.0, 300.0, 0.0, 0.0],
            "protection_type": ["guarantee", "credit_derivative", None, None],
            # Substitution tracking
            "pre_crm_exposure_class": ["corporate", "corporate", "corporate", "institution"],
            "post_crm_exposure_class_guaranteed": [
                "corporate",
                "corporate",
                "corporate",
                "institution",
            ],
        }
    )


def _irb_results_with_credit_derivatives() -> pl.LazyFrame:
    """IRB results with protection_type for credit derivative tracking tests."""
    return pl.LazyFrame(
        {
            "exposure_reference": ["IRB_CORP_1", "IRB_CORP_2"],
            "approach_applied": ["foundation_irb", "foundation_irb"],
            "exposure_class": ["corporate", "corporate"],
            "drawn_amount": [5000.0, 3000.0],
            "undrawn_amount": [1000.0, 0.0],
            "ead_final": [5500.0, 3000.0],
            "rwa_final": [3850.0, 1800.0],
            "risk_weight": [0.70, 0.60],
            "pd_floored": [0.005, 0.01],
            "lgd_floored": [0.45, 0.45],
            "irb_maturity_m": [2.5, 3.0],
            "expected_loss": [12.375, 13.5],
            "irb_capital_k": [0.056, 0.048],
            "provision_held": [15.0, 10.0],
            "el_shortfall": [0.0, 3.5],
            "el_excess": [2.625, 0.0],
            "counterparty_reference": ["CP_E", "CP_F"],
            # Protection split: CORP_1 has guarantee, CORP_2 has credit derivative
            "guaranteed_portion": [800.0, 400.0],
            "protection_type": ["guarantee", "credit_derivative"],
            # Substitution tracking
            "pre_crm_exposure_class": ["corporate", "corporate"],
            "post_crm_exposure_class_guaranteed": ["corporate", "corporate"],
        }
    )


def _sa_results_with_sign_convention_cols() -> pl.LazyFrame:
    """Single SA corporate on-balance-sheet exposure for sign-convention tests.

    Provides all columns referenced by C 07.00 "(-)" COREP cells so that
    the generator's _compute_c07_values / _c07_crm_and_collateral_cols paths
    are exercised end-to-end.  The guaranteed_portion migrates to a different
    exposure class (pre != post) so that substitution outflow = 200.

    Source: P2.26 scenario proposal §2.
    """
    return pl.LazyFrame(
        {
            "exposure_reference": ["SA_CORP_SC1"],
            "approach_applied": ["standardised"],
            "exposure_class": ["corporate"],
            # On-balance-sheet amount (no undrawn — pure on-BS loan)
            "drawn_amount": [1000.0],
            "undrawn_amount": [0.0],
            "ead_final": [850.0],  # net after CRM (informational only for this fixture)
            "rwa_final": [850.0],
            "risk_weight": [1.0],
            "sa_cqs": [3],
            "counterparty_reference": ["CP_SC1"],
            # 0030: scra_provision_amount + gcra_provision_amount = 100 + 0
            "scra_provision_amount": [100.0],
            "gcra_provision_amount": [0.0],
            # 0035 (B3.1): on_bs_netting_amount = 50
            "on_bs_netting_amount": [50.0],
            # 0050: guaranteed_portion where protection_type="guarantee"
            "guaranteed_portion": [200.0],
            "protection_type": ["guarantee"],
            # Make substitution outflow fire (pre != post → outflow = 200)
            "pre_crm_exposure_class": ["corporate"],
            "post_crm_exposure_class_guaranteed": ["institution"],
            # 0070: fcsm_collateral_value (Simple method)
            "fcsm_collateral_value": [75.0],
            # 0080: collateral_re_value + collateral_receivables_value + collateral_other_physical_value
            "collateral_re_value": [120.0],
            "collateral_receivables_value": [0.0],
            "collateral_other_physical_value": [0.0],
            # 0130 / 0140: Cvam and market value
            "collateral_adjusted_value": [60.0],
            "collateral_market_value": [70.0],
        }
    )


def _irb_results_with_sign_convention_cols() -> pl.LazyFrame:
    """Single IRB corporate exposure for sign-convention tests (C 08.01 col 0290).

    Source: P2.26 scenario proposal §2.
    """
    return pl.LazyFrame(
        {
            "exposure_reference": ["IRB_CORP_SC1"],
            "approach_applied": ["foundation_irb"],
            "exposure_class": ["corporate"],
            "drawn_amount": [1000.0],
            "undrawn_amount": [0.0],
            "ead_final": [1000.0],
            "rwa_final": [700.0],
            "risk_weight": [0.70],
            "pd_floored": [0.005],
            "lgd_floored": [0.45],
            "irb_maturity_m": [2.5],
            "expected_loss": [2.25],
            "irb_capital_k": [0.056],
            "provision_held": [45.0],
            "el_shortfall": [0.0],
            "el_excess": [2.75],
            # 0290: scra_provision_amount + gcra_provision_amount = 40 + 0
            "scra_provision_amount": [40.0],
            "gcra_provision_amount": [0.0],
            "counterparty_reference": ["CP_IRSC1"],
        }
    )


class TestCombinedGeneration:
    """Tests for generating all templates from combined SA + IRB data."""

    def test_all_templates_generated(self) -> None:
        """All three template dicts are non-empty for combined data."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_combined_results())

        assert len(bundle.c07_00) > 0
        assert len(bundle.c08_01) > 0
        assert len(bundle.c08_02) > 0

    def test_sa_and_irb_separated(self) -> None:
        """C 07.00 only has SA data; C 08.01 only has IRB data."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_combined_results())

        # Sum EAD across all SA classes
        sa_total_ead = sum(_get_total_row(df)["0200"][0] for df in bundle.c07_00.values())
        expected_sa_ead = _sa_results().select(pl.col("ead_final").sum()).collect()[0, 0]
        assert sa_total_ead == pytest.approx(expected_sa_ead)

        # Sum EAD across all IRB classes
        irb_total_ead = sum(_get_total_row(df)["0110"][0] for df in bundle.c08_01.values())
        expected_irb_ead = _irb_results().select(pl.col("ead_final").sum()).collect()[0, 0]
        assert irb_total_ead == pytest.approx(expected_irb_ead)

    def test_bundle_framework_stored(self) -> None:
        """Framework is stored in the template bundle."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_combined_results(), framework="BASEL_3_1")
        assert bundle.framework == "BASEL_3_1"

    def test_bundle_errors_empty_on_success(self) -> None:
        """No errors for well-formed input data (geo info messages are acceptable)."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_combined_results())
        # C 09.01/09.02 emit info messages when cp_country_code is absent
        non_geo_errors = [e for e in bundle.errors if "C09" not in e]
        assert len(non_geo_errors) == 0

    def test_framework_affects_column_set(self) -> None:
        """CRR and Basel 3.1 produce different column sets."""
        gen = COREPGenerator()
        crr = gen.generate_from_lazyframe(_sa_results(), framework="CRR")
        b31 = gen.generate_from_lazyframe(_sa_results(), framework="BASEL_3_1")

        crr_cols = set(next(iter(crr.c07_00.values())).columns)
        b31_cols = set(next(iter(b31.c07_00.values())).columns)

        # CRR has supporting factor columns, B3.1 doesn't
        assert "0215" in crr_cols
        assert "0215" not in b31_cols

        # B3.1 has on-BS netting, CRR doesn't
        assert "0035" in b31_cols
        assert "0035" not in crr_cols


@pytest.mark.skipif(not XLSXWRITER_AVAILABLE, reason="xlsxwriter not installed")
class TestExcelExport:
    """Tests for COREP Excel workbook generation."""

    def test_export_creates_file(self, tmp_path: Path) -> None:
        """COREP export creates an Excel file."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_combined_results())

        output = tmp_path / "corep.xlsx"
        result = gen.export_to_excel(bundle, output)

        assert output.exists()
        assert result.format == "corep_excel"
        assert result.row_count > 0
        assert output in result.files

    def test_export_has_per_class_sheets(self, tmp_path: Path) -> None:
        """COREP Excel workbook has per-class sheets."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_combined_results())

        output = tmp_path / "corep.xlsx"
        gen.export_to_excel(bundle, output)

        sheets = pl.read_excel(output, sheet_id=0)
        sheet_names: list[str] = list(sheets.keys()) if isinstance(sheets, dict) else []

        # Should have C 07.00 sheets for SA classes
        assert any("C 07.00" in s for s in sheet_names)
        # Should have C 08.01 sheets for IRB classes
        assert any("C 08.01" in s for s in sheet_names)

    def test_export_round_trip_c07(self, tmp_path: Path) -> None:
        """C 07.00 data survives Excel round-trip."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results())

        output = tmp_path / "corep.xlsx"
        gen.export_to_excel(bundle, output)

        # Read back the first sheet
        sheets = pl.read_excel(output, sheet_id=0)
        if isinstance(sheets, dict):
            first_sheet = next(iter(sheets.values()))
            assert len(first_sheet) > 0

    def test_export_writes_non_finite_cells_as_blank(self, tmp_path: Path) -> None:
        """A non-finite COREP cell is written blank, not crashing the workbook.

        On real data a COREP template ratio can be NaN or +/-Inf (e.g. over a zero
        denominator in an empty class segment); xlsxwriter rejects NaN/Inf in
        write_number(), so they must become blank rather than abort the export.
        """
        gen = COREPGenerator()
        bundle = COREPTemplateBundle(
            c07_00={"corporate": pl.DataFrame({"row": ["Avg RW"], "value": [float("inf")]})},
            c08_01={},
            c08_02={},
        )
        output = tmp_path / "corep_nonfinite.xlsx"

        # Act — must not raise "NAN/INF not supported in write_number()".
        result = gen.export_to_excel(bundle, output)

        # Assert — workbook written; the non-finite cell reads back blank (null).
        # The data header sits on row 1 (row 0 is the readable-name banner band).
        assert output.exists()
        assert result.format == "corep_excel"
        sheets = pl.read_excel(output, sheet_id=0, read_options={"header_row": 1})
        df = next(iter(sheets.values())) if isinstance(sheets, dict) else sheets
        assert all(v is None for v in df["value"].to_list())

    def test_export_writes_readable_name_banner_above_refs(self, tmp_path: Path) -> None:
        """The COREP Excel export bands readable column names above the ref codes."""
        gen = COREPGenerator()
        bundle = COREPTemplateBundle(
            c07_00={
                "corporate": pl.DataFrame(
                    {
                        "row_ref": ["0010"],
                        "row_name": ["TOTAL EXPOSURES"],
                        "0010": [100.0],
                        "0220": [50.0],
                    }
                )
            },
            c08_01={},
            c08_02={},
        )
        output = tmp_path / "corep_banner.xlsx"

        # Act
        gen.export_to_excel(bundle, output)

        # Assert — row 0 carries the readable column names, row 1 the ref codes.
        sheets = pl.read_excel(output, sheet_id=0, read_options={"header_row": None})
        df = next(iter(sheets.values())) if isinstance(sheets, dict) else sheets
        banner = df.row(0)
        refs = df.row(1)
        assert "Original exposure pre conversion factors" in banner  # name of col 0010
        assert "Row code" in banner and "Row name" in banner
        assert "0010" in refs and "row_ref" in refs


class TestExposureTypeRows:
    """Tests for Section 2 exposure type breakdown (on-BS vs off-BS)."""

    def test_c07_on_bs_row_populated(self) -> None:
        """Row 0070 (on-BS) aggregates on-balance-sheet exposures."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_bs_split())

        corp = bundle.c07_00["corporate"]
        on_bs = corp.filter(pl.col("row_ref") == "0070")
        # 2 on-BS: EAD 1000+2000=3000
        assert on_bs["0200"][0] == pytest.approx(3000.0)

    def test_c07_off_bs_row_populated(self) -> None:
        """Row 0080 (off-BS) aggregates off-balance-sheet exposures."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_bs_split())

        corp = bundle.c07_00["corporate"]
        off_bs = corp.filter(pl.col("row_ref") == "0080")
        # 1 off-BS: EAD 400
        assert off_bs["0200"][0] == pytest.approx(400.0)

    def test_c07_on_plus_off_equals_total(self) -> None:
        """On-BS EAD + off-BS EAD = total EAD."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_bs_split())

        corp = bundle.c07_00["corporate"]
        total_ead = _get_total_row(corp)["0200"][0]
        on_bs_ead = corp.filter(pl.col("row_ref") == "0070")["0200"][0]
        off_bs_ead = corp.filter(pl.col("row_ref") == "0080")["0200"][0]
        assert on_bs_ead + off_bs_ead == pytest.approx(total_ead)

    def test_c07_ccr_rows_null(self) -> None:
        """CCR rows (0090-0130) remain null — CCR not implemented."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_bs_split())

        corp = bundle.c07_00["corporate"]
        for ref in ("0090", "0100", "0110", "0120", "0130"):
            row = corp.filter(pl.col("row_ref") == ref)
            if len(row) > 0:
                assert row["0200"][0] is None

    def test_c0801_on_bs_row_populated(self) -> None:
        """C 08.01 row 0020 (on-BS) is populated when bs_type available."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_phase2_cols())

        corp = bundle.c08_01["corporate"]
        on_bs = corp.filter(pl.col("row_ref") == "0020")
        # All IRB corp are ONB: EAD 5500+3000+600=9100
        assert on_bs["0110"][0] == pytest.approx(9100.0)

    def test_c07_section2_null_without_bs_type(self) -> None:
        """Section 2 rows are null when bs_type column is missing."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results())  # no bs_type col

        corp = bundle.c07_00["corporate"]
        on_bs = corp.filter(pl.col("row_ref") == "0070")
        assert on_bs["0200"][0] is None


class TestOfWhichDetailRows:
    """Tests for C 07.00 'of which' detail rows 0015 (defaulted) and 0020 (SME)."""

    def test_c07_defaulted_row_populated(self) -> None:
        """Row 0015 (defaulted) is populated when default_status column exists."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_phase2_cols())

        corp = bundle.c07_00["corporate"]
        defaulted = corp.filter(pl.col("row_ref") == "0015")
        # SA_DEF_1: EAD=800, default_status=True
        assert defaulted["0200"][0] == pytest.approx(800.0)

    def test_c07_defaulted_row_rwea(self) -> None:
        """Row 0015 RWEA matches defaulted exposures only."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_phase2_cols())

        corp = bundle.c07_00["corporate"]
        defaulted = corp.filter(pl.col("row_ref") == "0015")
        # SA_DEF_1: rwa_final=1200
        assert defaulted["0220"][0] == pytest.approx(1200.0)

    def test_c07_sme_row_populated(self) -> None:
        """Row 0020 (SME) is populated when sme columns exist."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_phase2_cols())

        sme = bundle.c07_00["corporate_sme"]
        sme_row = sme.filter(pl.col("row_ref") == "0020")
        # corporate_sme has sme_supporting_factor_eligible=True, EAD=550
        assert sme_row["0200"][0] == pytest.approx(550.0)

    def test_c07_defaulted_row_null_without_flag(self) -> None:
        """Row 0015 is null when no defaulted identification columns exist."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results())  # no default_status

        corp = bundle.c07_00["corporate"]
        defaulted = corp.filter(pl.col("row_ref") == "0015")
        assert defaulted["0200"][0] is None

    def test_c0801_defaulted_ead_col_0125(self) -> None:
        """C 08.01 col 0125 (defaulted EAD) populated from default_status."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_phase2_cols(), framework="BASEL_3_1")

        corp = _get_total_row(bundle.c08_01["corporate"])
        # IRB_DEF_1: EAD=600, default_status=True
        assert corp["0125"][0] == pytest.approx(600.0)

    def test_c0801_defaulted_rwea_col_0265(self) -> None:
        """C 08.01 col 0265 (defaulted RWEA) populated from default_status."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_phase2_cols(), framework="BASEL_3_1")

        corp = _get_total_row(bundle.c08_01["corporate"])
        # IRB_DEF_1: rwa_final=900, default_status=True
        assert corp["0265"][0] == pytest.approx(900.0)

    def test_c0801_defaulted_zero_when_none_defaulted(self) -> None:
        """C 08.01 cols 0125/0265 are 0.0 when no exposures are defaulted."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_phase2_cols(), framework="BASEL_3_1")

        inst = _get_total_row(bundle.c08_01["institution"])
        assert inst["0125"][0] == pytest.approx(0.0)
        assert inst["0265"][0] == pytest.approx(0.0)


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_missing_columns_handled_gracefully(self) -> None:
        """Generator handles missing optional columns without crashing."""
        minimal = pl.LazyFrame(
            {
                "approach_applied": ["standardised", "standardised"],
                "exposure_class": ["corporate", "institution"],
                "ead_final": [1000.0, 2000.0],
                "rwa_final": [1000.0, 400.0],
            }
        )
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(minimal)

        # Should produce C 07.00 per-class output
        assert len(bundle.c07_00) == 2
        assert "corporate" in bundle.c07_00

    def test_canonical_column_names(self) -> None:
        """Generator works with the sealed canonical names (ead_final / rwa_final).

        P7-S1 (Option B): reporting reads only the sealed ``AGGREGATOR_EXIT``
        column names; the prior consumer-side alias tolerance (``ead`` / ``rwa``)
        was intentionally removed, so the fixture feeds the canonical names.
        """
        canonical = pl.LazyFrame(
            {
                "approach_applied": ["standardised"],
                "exposure_class": ["corporate"],
                "ead_final": [1000.0],
                "rwa_final": [1000.0],
                "risk_weight": [1.0],
            }
        )
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(canonical)
        assert len(bundle.c07_00) == 1

    def test_sa_only_data(self) -> None:
        """SA-only data produces C 07.00 but empty C 08.01/C 08.02."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results())

        assert len(bundle.c07_00) > 0
        assert bundle.c08_01 == {}
        assert bundle.c08_02 == {}

    def test_irb_only_data(self) -> None:
        """IRB-only data produces C 08.01/C 08.02 but empty C 07.00."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results())

        assert bundle.c07_00 == {}
        assert len(bundle.c08_01) > 0
        assert len(bundle.c08_02) > 0

    def test_single_exposure(self) -> None:
        """Single exposure produces valid per-class template."""
        single = pl.LazyFrame(
            {
                "approach_applied": ["standardised"],
                "exposure_class": ["corporate"],
                "drawn_amount": [1000.0],
                "undrawn_amount": [0.0],
                "ead_final": [1000.0],
                "rwa_final": [1000.0],
                "risk_weight": [1.0],
            }
        )
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(single)

        assert "corporate" in bundle.c07_00
        corp = bundle.c07_00["corporate"]
        total = _get_total_row(corp)
        assert total["0200"][0] == pytest.approx(1000.0)

    def test_corporate_sme_separate_from_corporate(self) -> None:
        """corporate_sme gets its own separate template from corporate."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results())

        assert "corporate" in bundle.c07_00
        assert "corporate_sme" in bundle.c07_00

        corp_ead = _get_total_row(bundle.c07_00["corporate"])["0200"][0]
        sme_ead = _get_total_row(bundle.c07_00["corporate_sme"])["0200"][0]

        # Corporate: 1200+2000=3200, SME: 550
        assert corp_ead == pytest.approx(3200.0)
        assert sme_ead == pytest.approx(550.0)


class TestSubstitutionFlows:
    """Task 2H: CRM substitution flow columns (C 07.00: 0090/0100/0110;
    C 08.01: 0040/0070/0080/0090).

    Why: COREP requires reporting how CRM guarantees cause exposure to
    'flow' between exposure classes. Outflows show guaranteed portions
    leaving the borrower's class; inflows show guaranteed portions
    arriving from other classes via the guarantor's class assignment.
    """

    def test_c07_outflow_populated(self) -> None:
        """Col 0090 shows guaranteed portion leaving the class — emitted negative per Annex II §1.3."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_substitution())

        corp = _get_total_row(bundle.c07_00["corporate"])
        # SA_CORP_2 has 500 guaranteed_portion migrating to institution; stored as negative deduction
        assert corp["0090"][0] == pytest.approx(-500.0)

    def test_c07_inflow_populated(self) -> None:
        """Col 0100 shows guaranteed portion arriving from other classes."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_substitution())

        inst = _get_total_row(bundle.c07_00["institution"])
        # SA_CORP_2's 500 guaranteed portion flows into institution class
        assert inst["0100"][0] == pytest.approx(500.0)

    def test_c07_no_flow_class_has_zero(self) -> None:
        """Class with no substitution has 0 outflow and 0 inflow."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_substitution())

        retail = _get_total_row(bundle.c07_00["retail_other"])
        assert retail["0090"][0] == pytest.approx(0.0)
        assert retail["0100"][0] == pytest.approx(0.0)

    def test_c07_net_exposure_after_substitution(self) -> None:
        """Col 0110 = net exposure after all CRM deductions (guaranteed outflow removes 500)."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_substitution())

        corp = _get_total_row(bundle.c07_00["corporate"])
        v_0110 = corp["0110"][0]

        # Engine: 0040=3455, 0050=-500 (deduction), 0090=-500 (outflow deduction) → 0110=2455
        assert v_0110 == pytest.approx(2455.0)

    def test_c07_outflow_zero_without_substitution_cols(self) -> None:
        """Without pre/post CRM columns, outflow defaults to 0."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results())

        corp = _get_total_row(bundle.c07_00["corporate"])
        assert corp["0090"][0] == pytest.approx(0.0)

    def test_c08_guarantee_col_populated(self) -> None:
        """C 08.01 col 0040 shows guaranteed_portion sum."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_substitution())

        corp = _get_total_row(bundle.c08_01["corporate"])
        # IRB_CORP_2 has 800 guaranteed_portion
        assert corp["0040"][0] == pytest.approx(800.0)

    def test_c08_outflow_populated(self) -> None:
        """C 08.01 col 0070 shows guaranteed portion leaving the class."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_substitution())

        corp = _get_total_row(bundle.c08_01["corporate"])
        assert corp["0070"][0] == pytest.approx(800.0)

    def test_c08_inflow_populated(self) -> None:
        """C 08.01 col 0080 shows guaranteed portion arriving from other classes."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_substitution())

        inst = _get_total_row(bundle.c08_01["institution"])
        assert inst["0080"][0] == pytest.approx(800.0)

    def test_c08_net_after_substitution(self) -> None:
        """C 08.01 col 0090 = 0020 - 0040 - 0070 + 0080."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_substitution())

        corp = _get_total_row(bundle.c08_01["corporate"])
        v_0020 = corp["0020"][0]
        v_0040 = corp["0040"][0]
        v_0070 = corp["0070"][0]
        v_0080 = corp["0080"][0]
        v_0090 = corp["0090"][0]

        expected = v_0020 - v_0040 - v_0070 + v_0080
        assert v_0090 == pytest.approx(expected)


class TestOnBSNetting:
    """Task 3D: On-balance-sheet netting (COREP col 0035).

    Why: Basel 3.1 introduces col 0035 to separately report on-BS netting
    within the EAD waterfall: Original (0010) - Provisions (0030) - Netting
    (0035) = Net exposure (0040). Without this, the netting benefit is
    invisible in COREP reporting.
    """

    def test_c07_col_0035_populated_b31(self) -> None:
        """Col 0035 shows summed on_bs_netting_amount for Basel 3.1 — negative per Annex II §1.3."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_netting(), framework="BASEL_3_1")
        corp = _get_total_row(bundle.c07_00["corporate"])
        # SA_CORP_1 has 150 netting, SA_CORP_2 has 0 → total 150; stored as negative deduction
        assert corp["0035"][0] == pytest.approx(-150.0)

    def test_c07_col_0035_absent_crr(self) -> None:
        """Col 0035 doesn't exist under CRR (no on-BS netting column)."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_netting(), framework="CRR")
        corp = _get_total_row(bundle.c07_00["corporate"])
        assert "0035" not in corp.columns

    def test_c07_col_0040_includes_netting_b31(self) -> None:
        """Col 0040 is net exposure after provisions and netting deductions."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_netting(), framework="BASEL_3_1")
        corp = _get_total_row(bundle.c07_00["corporate"])
        v_0040 = corp["0040"][0]
        # Engine: 0010=3500, 0030=-45, 0035=-150 → 0040=3305 (3500 - 45 - 150)
        assert v_0040 == pytest.approx(3305.0)

    def test_c07_zero_netting_class(self) -> None:
        """Class with no netting exposures reports 0 for col 0035."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_netting(), framework="BASEL_3_1")
        retail = _get_total_row(bundle.c07_00["retail_other"])
        assert retail["0035"][0] == pytest.approx(0.0)

    def test_c08_col_0035_populated_b31(self) -> None:
        """C 08.01 col 0035 shows summed on_bs_netting_amount for Basel 3.1."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_netting(), framework="BASEL_3_1")
        corp = _get_total_row(bundle.c08_01["corporate"])
        # IRB_CORP_1 has 300 netting, IRB_CORP_2 has 0 → total 300
        assert corp["0035"][0] == pytest.approx(300.0)

    def test_c08_col_0035_absent_crr(self) -> None:
        """C 08.01 col 0035 doesn't exist under CRR."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_netting(), framework="CRR")
        corp = _get_total_row(bundle.c08_01["corporate"])
        assert "0035" not in corp.columns

    def test_c07_netting_without_column(self) -> None:
        """Without on_bs_netting_amount in data, col 0035 is None."""
        gen = COREPGenerator()
        # _sa_results() does not have on_bs_netting_amount
        bundle = gen.generate_from_lazyframe(_sa_results(), framework="BASEL_3_1")
        corp = _get_total_row(bundle.c07_00["corporate"])
        assert corp["0035"][0] is None


class TestEquityTransitionalRows:
    """Task 3I: Equity transitional provisions (B3.1 OF 07.00 rows 0371-0374).

    Why: Basel 3.1 removes equity IRB treatment and transitions all equity to
    SA. Rows 0371-0374 report the transitional equity exposures split by
    approach (SA/IRB transitional) and risk level (higher risk vs other).
    """

    def test_sa_higher_risk_row(self) -> None:
        """Row 0371: SA transitional, higher risk."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _sa_results_with_equity_transitional(), framework="BASEL_3_1"
        )
        eq = bundle.c07_00["equity"]
        row = eq.filter(pl.col("row_ref") == "0371")
        assert len(row) == 1
        assert row["0200"][0] == pytest.approx(100.0)

    def test_sa_other_equity_row(self) -> None:
        """Row 0372: SA transitional, other equity."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _sa_results_with_equity_transitional(), framework="BASEL_3_1"
        )
        eq = bundle.c07_00["equity"]
        row = eq.filter(pl.col("row_ref") == "0372")
        assert len(row) == 1
        assert row["0200"][0] == pytest.approx(200.0)

    def test_irb_higher_risk_row(self) -> None:
        """Row 0373: IRB transitional, higher risk."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _sa_results_with_equity_transitional(), framework="BASEL_3_1"
        )
        eq = bundle.c07_00["equity"]
        row = eq.filter(pl.col("row_ref") == "0373")
        assert len(row) == 1
        assert row["0200"][0] == pytest.approx(150.0)

    def test_irb_other_equity_row(self) -> None:
        """Row 0374: IRB transitional, other equity."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _sa_results_with_equity_transitional(), framework="BASEL_3_1"
        )
        eq = bundle.c07_00["equity"]
        row = eq.filter(pl.col("row_ref") == "0374")
        assert len(row) == 1
        assert row["0200"][0] == pytest.approx(300.0)

    def test_equity_rows_absent_crr(self) -> None:
        """Equity transitional rows don't exist under CRR."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _sa_results_with_equity_transitional(), framework="CRR"
        )
        eq = bundle.c07_00.get("equity")
        if eq is not None:
            eq_rows = eq.filter(pl.col("row_ref").is_in(["0371", "0372", "0373", "0374"]))
            assert len(eq_rows) == 0

    def test_equity_rows_null_without_column(self) -> None:
        """Without equity_transitional_approach, equity rows are null."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results(), framework="BASEL_3_1")
        corp = bundle.c07_00.get("corporate")
        if corp is not None:
            row = corp.filter(pl.col("row_ref") == "0371")
            if len(row) > 0:
                assert row["0200"][0] is None


class TestCollateralMethodSplit:
    """Tests for Task 3A: collateral method split for COREP reporting."""

    def test_c07_comprehensive_method_columns(self) -> None:
        """C 07.00 cols 0070=0.0, 0080 populated, 0120=0.0 for SA with collateral."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _sa_results_with_collateral_split(), framework="BASEL_3_1"
        )
        corp = bundle.c07_00["corporate"]
        total = corp.filter(pl.col("row_ref") == "0010")

        # 0070: Simple method not used → 0.0
        assert total["0070"][0] == pytest.approx(0.0)
        # 0080: Other funded = RE + receivables + other_physical = 30+10+10 = 50; negative per Annex II §1.3
        assert total["0080"][0] == pytest.approx(-50.0)
        # 0120: He = 0 for loans
        assert total["0120"][0] == pytest.approx(0.0)

    def test_c07_vol_mat_adjustment(self) -> None:
        """C 07.00 col 0140 = vol/mat haircut — emitted negative per Annex II §1.3."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _sa_results_with_collateral_split(), framework="BASEL_3_1"
        )
        corp = bundle.c07_00["corporate"]
        total = corp.filter(pl.col("row_ref") == "0010")

        # Corporate: market_value=180, adjusted_value=150 → vol/mat adj = 30; stored as negative deduction
        assert total["0140"][0] == pytest.approx(-30.0)

    def test_c07_fully_adjusted_exposure(self) -> None:
        """C 07.00 col 0150 = fully adjusted exposure value after all CRM deductions."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _sa_results_with_collateral_split(), framework="BASEL_3_1"
        )
        corp = bundle.c07_00["corporate"]
        total = corp.filter(pl.col("row_ref") == "0010")

        # Engine: 0110=2405, 0130=-150 (negative deduction per Annex II §1.3), 0150=2255
        assert total["0150"][0] == pytest.approx(2255.0)

    def test_c08_collateral_type_breakdown(self) -> None:
        """C 08.01 cols 0180/0190/0200/0210 populated from per-type collateral values."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _irb_results_with_collateral_split(), framework="BASEL_3_1"
        )
        corp = bundle.c08_01["corporate"]
        total = corp.filter(pl.col("row_ref") == "0010")

        # 0180: Financial collateral = 200 + 0 = 200
        assert total["0180"][0] == pytest.approx(200.0)
        # 0190: Real estate = 150 + 100 = 250
        assert total["0190"][0] == pytest.approx(250.0)
        # 0200: Other physical = 30 + 20 = 50
        assert total["0200"][0] == pytest.approx(50.0)
        # 0210: Receivables = 50 + 0 = 50
        assert total["0210"][0] == pytest.approx(50.0)

    def test_c08_other_funded_protection(self) -> None:
        """C 08.01 cols 0170-0173 are 0.0 (catch-all types not tracked)."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _irb_results_with_collateral_split(), framework="BASEL_3_1"
        )
        corp = bundle.c08_01["corporate"]
        total = corp.filter(pl.col("row_ref") == "0010")

        assert total["0170"][0] == pytest.approx(0.0)
        assert total["0171"][0] == pytest.approx(0.0)
        assert total["0172"][0] == pytest.approx(0.0)
        assert total["0173"][0] == pytest.approx(0.0)

    def test_c08_guarantees_unfunded(self) -> None:
        """C 08.01 col 0150 = guaranteed_portion sum."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _irb_results_with_collateral_split(), framework="BASEL_3_1"
        )
        corp = bundle.c08_01["corporate"]
        total = corp.filter(pl.col("row_ref") == "0010")

        # guaranteed_portion = 0 + 500 = 500
        assert total["0150"][0] == pytest.approx(500.0)

    def test_c08_other_funded_for_irb(self) -> None:
        """C 08.01 col 0060 = non-financial collateral total."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _irb_results_with_collateral_split(), framework="BASEL_3_1"
        )
        corp = bundle.c08_01["corporate"]
        total = corp.filter(pl.col("row_ref") == "0010")

        # 0060 = RE + receivables + other_physical = (150+100) + (50+0) + (30+20) = 350
        assert total["0060"][0] == pytest.approx(350.0)

    def test_no_collateral_class(self) -> None:
        """Columns are 0.0 when no collateral in class (institution has no non-fin)."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _sa_results_with_collateral_split(), framework="BASEL_3_1"
        )
        inst = bundle.c07_00["institution"]
        total = inst.filter(pl.col("row_ref") == "0010")

        # Institution has no non-financial collateral
        assert total["0080"][0] == pytest.approx(0.0)
        # Financial collateral (col 0130) stored as negative deduction per Annex II §1.3
        assert total["0130"][0] == pytest.approx(-200.0)


class TestCreditDerivativeTracking:
    """Tests for Task 3B: credit derivative tracking for COREP reporting."""

    def test_c07_guarantee_and_cd_split(self) -> None:
        """C 07.00 col 0050=guarantee only (negative), col 0060=credit derivative only (negative)."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _sa_results_with_credit_derivatives(), framework="BASEL_3_1"
        )
        corp = bundle.c07_00["corporate"]
        total = corp.filter(pl.col("row_ref") == "0010")

        # Col 0050: guarantees only = 200.0 (SA_CORP_1); negative deduction per Annex II §1.3
        assert total["0050"][0] == pytest.approx(-200.0)
        # Col 0060: credit derivatives only = 300.0 (SA_CORP_2); negative deduction per Annex II §1.3
        assert total["0060"][0] == pytest.approx(-300.0)

    def test_c07_institution_no_protection(self) -> None:
        """C 07.00 cols 0050/0060 are 0 for institution with no protection."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _sa_results_with_credit_derivatives(), framework="BASEL_3_1"
        )
        inst = bundle.c07_00["institution"]
        total = inst.filter(pl.col("row_ref") == "0010")

        assert total["0050"][0] == pytest.approx(0.0)
        assert total["0060"][0] == pytest.approx(0.0)

    def test_c07_col_0110_includes_cd_deduction(self) -> None:
        """C 07.00 col 0110 deducts both guarantees and credit derivatives."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _sa_results_with_credit_derivatives(), framework="BASEL_3_1"
        )
        corp = bundle.c07_00["corporate"]
        total = corp.filter(pl.col("row_ref") == "0010")

        col_0110 = total["0110"][0]

        # Engine: 0040=4435, 0050=-200 (guarantee), 0060=-300 (credit derivative) → 0110=3935
        assert col_0110 == pytest.approx(3935.0)

    def test_c08_guarantee_and_cd_split(self) -> None:
        """C 08.01 col 0040=guarantee only, col 0050=credit derivative only."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _irb_results_with_credit_derivatives(), framework="BASEL_3_1"
        )
        corp = bundle.c08_01["corporate"]
        total = corp.filter(pl.col("row_ref") == "0010")

        # Col 0040: guarantees only = 800.0 (IRB_CORP_1)
        assert total["0040"][0] == pytest.approx(800.0)
        # Col 0050: credit derivatives only = 400.0 (IRB_CORP_2)
        assert total["0050"][0] == pytest.approx(400.0)

    def test_c08_unfunded_protection_split(self) -> None:
        """C 08.01 col 0150=guarantee, col 0160=credit derivative."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _irb_results_with_credit_derivatives(), framework="BASEL_3_1"
        )
        corp = bundle.c08_01["corporate"]
        total = corp.filter(pl.col("row_ref") == "0010")

        # Col 0150: unfunded guarantees = 800.0
        assert total["0150"][0] == pytest.approx(800.0)
        # Col 0160: unfunded credit derivatives = 400.0
        assert total["0160"][0] == pytest.approx(400.0)

    def test_c08_pre_credit_derivatives_rwea(self) -> None:
        """C 08.01 col 0310 = total RWEA (pre-credit-derivative baseline)."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _irb_results_with_credit_derivatives(), framework="BASEL_3_1"
        )
        corp = bundle.c08_01["corporate"]
        total = corp.filter(pl.col("row_ref") == "0010")

        # Col 0310: total RWEA = 3850 + 1800 = 5650
        assert total["0310"][0] == pytest.approx(5650.0)

    def test_backward_compat_no_protection_type(self) -> None:
        """Without protection_type column, all guaranteed_portion is col 0050 (guarantees)."""
        gen = COREPGenerator()
        # Use the existing collateral split fixture which has guaranteed_portion but no
        # protection_type column — backward compatibility path
        bundle = gen.generate_from_lazyframe(
            _sa_results_with_collateral_split(), framework="BASEL_3_1"
        )
        corp = bundle.c07_00["corporate"]
        total = corp.filter(pl.col("row_ref") == "0010")

        # Col 0050: all guaranteed_portion goes to guarantees = 500.0 (SA_CORP_2); negative per Annex II §1.3
        assert total["0050"][0] == pytest.approx(-500.0)
        # Col 0060: 0.0 since no protection_type column to identify credit derivatives
        assert total["0060"][0] == pytest.approx(0.0)

    def test_crr_framework_includes_cd_cols(self) -> None:
        """CRR framework also has cols 0050/0060 for C 07.00 — negative per Annex II §1.3."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_credit_derivatives(), framework="CRR")
        corp = bundle.c07_00["corporate"]
        total = corp.filter(pl.col("row_ref") == "0010")

        assert total["0050"][0] == pytest.approx(-200.0)
        assert total["0060"][0] == pytest.approx(-300.0)


class TestEquityTransitionalColumns:
    """Tests for equity_transitional_approach/equity_higher_risk columns.

    Why: The equity calculator's _apply_transitional_floor() now writes
    annotation columns needed by COREP OF 07.00 rows 0371-0374. Without
    these columns, the equity transitional rows were always null.
    """

    def test_equity_transitional_approach_column_added(self) -> None:
        """Equity calculator adds equity_transitional_approach column."""
        from datetime import date
        from decimal import Decimal

        from rwa_calc.contracts.config import (
            CalculationConfig,
            EquityTransitionalConfig,
        )
        from rwa_calc.engine.equity.calculator import EquityCalculator

        eq_config = EquityTransitionalConfig(
            enabled=True,
            schedule={date(2027, 1, 1): (Decimal("1.00"), Decimal("1.50"))},
        )
        config_b31 = CalculationConfig.basel_3_1(
            reporting_date=date(2027, 6, 1),
        )
        # Replace equity_transitional with our test config
        import dataclasses

        config_with_trans: CalculationConfig = dataclasses.replace(
            config_b31, equity_transitional=eq_config
        )

        exposures = pl.LazyFrame(
            {
                "exposure_reference": ["EQ_1", "EQ_2"],
                "equity_type": ["listed", "listed"],
                "ead_final": [1000.0, 500.0],
                "risk_weight": [2.50, 2.50],
                "is_speculative": [False, True],
                "is_diversified_portfolio": [False, False],
                "is_exchange_traded": [False, False],
                "is_government_supported": [False, False],
                "ciu_approach": [None, None],
                "ciu_mandate_rw": [None, None],
                "ciu_third_party_calc": [None, None],
                "fund_reference": [None, None],
                "ciu_look_through_rw": [None, None],
                "fund_nav": [None, None],
            }
        )
        calc = EquityCalculator()
        result = calc._apply_transitional_floor(exposures, config_with_trans)
        collected = result.collect()
        assert "equity_transitional_approach" in collected.columns
        assert "equity_higher_risk" in collected.columns
        # SA transitional (B31 has no IRB equity)
        assert collected["equity_transitional_approach"][0] == "sa_transitional"
        # Non-speculative
        assert collected["equity_higher_risk"][0] is False
        # Speculative
        assert collected["equity_higher_risk"][1] is True


class TestSignConvention:
    """P2.26: COREP Annex II "(-)" column sign convention.

    COREP Annex II §1.3 specifies that columns labelled "(-)" must be
    reported as *negative* figures so that the DPM net-exposure arithmetic
    reconciles when summed across columns.  The generator currently emits
    positive sums; these tests will fail until the negate-at-boundary fix
    is applied in the engine.

    Columns under test (SA C 07.00 / OF 07.00):
        0030, 0035 (B3.1 only), 0050, 0060, 0070, 0080, 0090, 0130, 0140

    Column under test (IRB C 08.01 / OF 08.01):
        0290

    Invariants (must NOT be negated — no "(-)" label):
        0040 stays positive (net of adjustments formula consumes magnitudes)
        0110 >= 0
        0150 >= 0
        IRB 0090 >= 0

    References:
        - COREP Annex II §1.3 (docs/assets/ps1-26-annex-ii-reporting-instructions.pdf)
        - templates.py L89-99, L198-217, L239-262, L554
        - IMPLEMENTATION_PLAN.md P2.26
    """

    # ------------------------------------------------------------------
    # Arrange helpers
    # ------------------------------------------------------------------

    def _sa_bundle_b31(self) -> COREPTemplateBundle:
        """Generate the OF 07.00 bundle (Basel 3.1 framework)."""
        gen = COREPGenerator()
        return gen.generate_from_lazyframe(
            _sa_results_with_sign_convention_cols(), framework="BASEL_3_1"
        )

    def _sa_bundle_crr(self) -> COREPTemplateBundle:
        """Generate the C 07.00 bundle (CRR framework)."""
        gen = COREPGenerator()
        return gen.generate_from_lazyframe(_sa_results_with_sign_convention_cols(), framework="CRR")

    def _irb_bundle_b31(self) -> COREPTemplateBundle:
        """Generate the OF 08.01 bundle (Basel 3.1 framework)."""
        gen = COREPGenerator()
        return gen.generate_from_lazyframe(
            _irb_results_with_sign_convention_cols(), framework="BASEL_3_1"
        )

    # ------------------------------------------------------------------
    # SA "(-)" signed-value assertions (will FAIL pre-fix)
    # ------------------------------------------------------------------

    def test_c07_col_0030_negative_b31(self) -> None:
        """C 07.00 col 0030 (-) value adjustments emits -100.0 (B3.1)."""
        # Arrange
        bundle = self._sa_bundle_b31()
        corp = bundle.c07_00["corporate"]
        total = corp.filter(pl.col("row_ref") == "0010")
        # Act / Assert
        assert total["0030"][0] == pytest.approx(-100.0)

    def test_c07_col_0030_negative_crr(self) -> None:
        """C 07.00 col 0030 (-) value adjustments emits -100.0 (CRR)."""
        # Arrange
        bundle = self._sa_bundle_crr()
        corp = bundle.c07_00["corporate"]
        total = corp.filter(pl.col("row_ref") == "0010")
        # Act / Assert
        assert total["0030"][0] == pytest.approx(-100.0)

    def test_c07_col_0035_negative_b31_only(self) -> None:
        """C 07.00 col 0035 (-) on-bs netting emits -50.0 (B3.1 variant only)."""
        # Arrange
        bundle = self._sa_bundle_b31()
        corp = bundle.c07_00["corporate"]
        total = corp.filter(pl.col("row_ref") == "0010")
        # Act / Assert
        assert total["0035"][0] == pytest.approx(-50.0)

    def test_c07_col_0050_negative_b31(self) -> None:
        """C 07.00 col 0050 (-) guarantees emits -200.0 (B3.1)."""
        # Arrange
        bundle = self._sa_bundle_b31()
        corp = bundle.c07_00["corporate"]
        total = corp.filter(pl.col("row_ref") == "0010")
        # Act / Assert
        assert total["0050"][0] == pytest.approx(-200.0)

    def test_c07_col_0060_zero_no_credit_derivative(self) -> None:
        """C 07.00 col 0060 (-) credit derivatives is 0.0 when none present (B3.1)."""
        # Arrange — protection_type="guarantee" so no credit derivatives
        bundle = self._sa_bundle_b31()
        corp = bundle.c07_00["corporate"]
        total = corp.filter(pl.col("row_ref") == "0010")
        # Act / Assert — negative-zero normalises to 0.0 (not -0.0)
        val = total["0060"][0]
        assert val == pytest.approx(0.0)
        # Confirm sign: -0.0 and 0.0 are both acceptable for "no protection"
        assert val is not None

    def test_c07_col_0070_negative_b31(self) -> None:
        """C 07.00 col 0070 (-) simple-method financial collateral emits -75.0 (B3.1)."""
        # Arrange
        bundle = self._sa_bundle_b31()
        corp = bundle.c07_00["corporate"]
        total = corp.filter(pl.col("row_ref") == "0010")
        # Act / Assert
        assert total["0070"][0] == pytest.approx(-75.0)

    def test_c07_col_0080_negative_b31(self) -> None:
        """C 07.00 col 0080 (-) other funded credit protection emits -120.0 (B3.1)."""
        # Arrange — collateral_re_value=120
        bundle = self._sa_bundle_b31()
        corp = bundle.c07_00["corporate"]
        total = corp.filter(pl.col("row_ref") == "0010")
        # Act / Assert
        assert total["0080"][0] == pytest.approx(-120.0)

    def test_c07_col_0090_negative_b31(self) -> None:
        """C 07.00 col 0090 (-) substitution outflows emits -200.0 (B3.1)."""
        # Arrange — guaranteed_portion=200 migrates to different class → outflow=200
        bundle = self._sa_bundle_b31()
        corp = bundle.c07_00["corporate"]
        total = corp.filter(pl.col("row_ref") == "0010")
        # Act / Assert
        assert total["0090"][0] == pytest.approx(-200.0)

    def test_c07_col_0130_negative_b31(self) -> None:
        """C 07.00 col 0130 (-) Cvam collateral adjusted value emits -60.0 (B3.1)."""
        # Arrange
        bundle = self._sa_bundle_b31()
        corp = bundle.c07_00["corporate"]
        total = corp.filter(pl.col("row_ref") == "0010")
        # Act / Assert
        assert total["0130"][0] == pytest.approx(-60.0)

    def test_c07_col_0140_negative_b31(self) -> None:
        """C 07.00 col 0140 (-) vol/maturity adjustments emits -10.0 (B3.1)."""
        # Arrange — market_value=70, adjusted_value=60 → difference=10 → signed=-10
        bundle = self._sa_bundle_b31()
        corp = bundle.c07_00["corporate"]
        total = corp.filter(pl.col("row_ref") == "0010")
        # Act / Assert
        assert total["0140"][0] == pytest.approx(-10.0)

    # ------------------------------------------------------------------
    # IRB "(-)" signed-value assertion (will FAIL pre-fix)
    # ------------------------------------------------------------------

    def test_c08_col_0290_negative_b31(self) -> None:
        """C 08.01 col 0290 (-) value adjustments and provisions emits -40.0 (B3.1)."""
        # Arrange
        bundle = self._irb_bundle_b31()
        corp = bundle.c08_01["corporate"]
        total = corp.filter(pl.col("row_ref") == "0010")
        # Act / Assert
        assert total["0290"][0] == pytest.approx(-40.0)

    # ------------------------------------------------------------------
    # Invariants: NON-"(-)" columns must stay POSITIVE (catch over-negate)
    # These should PASS before and after the fix.
    # ------------------------------------------------------------------

    def test_c07_col_0040_stays_positive_b31(self) -> None:
        """C 07.00 col 0040 (no (-) label) = 1000 - 100 - 50 = 850.0 — stays positive.

        Verifies that the negate-at-boundary fix does NOT apply to 0040.
        The internal formula consumes magnitudes before negation; 0040 must
        remain positive so that 0110 arithmetic is correct.
        """
        # Arrange
        bundle = self._sa_bundle_b31()
        corp = bundle.c07_00["corporate"]
        total = corp.filter(pl.col("row_ref") == "0010")
        # Act / Assert: 0010=1000, 0030=100 (magnitude), 0035=50 (magnitude)
        assert total["0040"][0] == pytest.approx(850.0)

    def test_c07_col_0110_non_negative_b31(self) -> None:
        """C 07.00 col 0110 (no (-) label) stays >= 0 — not negated."""
        # Arrange
        bundle = self._sa_bundle_b31()
        corp = bundle.c07_00["corporate"]
        total = corp.filter(pl.col("row_ref") == "0010")
        # Act / Assert
        val = total["0110"][0]
        assert val is not None
        assert val >= 0.0

    def test_c07_col_0150_non_negative_b31(self) -> None:
        """C 07.00 col 0150 E* (no (-) label) stays >= 0 — not negated."""
        # Arrange
        bundle = self._sa_bundle_b31()
        corp = bundle.c07_00["corporate"]
        total = corp.filter(pl.col("row_ref") == "0010")
        # Act / Assert
        val = total["0150"][0]
        assert val is not None
        assert val >= 0.0

    def test_c08_col_0090_non_negative_b31(self) -> None:
        """C 08.01 col 0090 (no (-) label) stays positive — not negated."""
        # Arrange
        bundle = self._irb_bundle_b31()
        corp = bundle.c08_01["corporate"]
        total = corp.filter(pl.col("row_ref") == "0010")
        # Act / Assert
        val = total["0090"][0]
        # 0090 may be None when lfse/defaulted data absent — check only when present
        if val is not None:
            assert val >= 0.0
