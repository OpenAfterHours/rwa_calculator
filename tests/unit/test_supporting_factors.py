"""
Unit tests for supporting factors (CRR2 Art. 501).

Tests cover:
- BTL exclusion from SME factor (BTL still counts toward total_cp_drawn)
- Drawn-only tier weighting: tier calculation uses drawn_amount + interest,
  NOT ead_final (which includes CCF-adjusted undrawn commitments)
- Infrastructure factor interaction with BTL
- Backward compatibility when drawn_amount column is missing
- Missing counterparty_reference warning (P1.31)
"""

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.contracts.errors import ERROR_SME_MISSING_COUNTERPARTY_REF, CalculationError
from rwa_calc.domain.enums import ErrorCategory, ErrorSeverity
from rwa_calc.engine.sa.supporting_factors import SupportingFactorCalculator


@pytest.fixture()
def calculator() -> SupportingFactorCalculator:
    return SupportingFactorCalculator()


@pytest.fixture()
def crr_config() -> CalculationConfig:
    return CalculationConfig.crr(reporting_date=date(2025, 12, 31))


def _make_exposures(
    rows: list[dict],
    include_btl: bool = True,
    include_drawn: bool = True,
    include_counterparty: bool = True,
) -> pl.LazyFrame:
    """Build a LazyFrame of exposures for supporting factor tests.

    Each row dict supports keys:
        ref, cp, ead, rwa, drawn (defaults to ead), interest (defaults to 0),
        is_sme (True), is_infra (False), is_btl (False).
    """
    data: dict = {
        "exposure_reference": [r["ref"] for r in rows],
        "ead_final": [r["ead"] for r in rows],
        "rwa_pre_factor": [r["rwa"] for r in rows],
        "is_sme": [r.get("is_sme", True) for r in rows],
        "is_infrastructure": [r.get("is_infra", False) for r in rows],
    }
    if include_counterparty:
        data["counterparty_reference"] = [r["cp"] for r in rows]
    if include_drawn:
        data["drawn_amount"] = [r.get("drawn", r["ead"]) for r in rows]
        data["interest"] = [r.get("interest", 0.0) for r in rows]
    if include_btl:
        data["is_buy_to_let"] = [r.get("is_btl", False) for r in rows]
    return pl.LazyFrame(data)


class TestBTLExcludedFromSMEFactor:
    """BTL exposures get supporting_factor=1.0 but still count toward total_cp_drawn."""

    def test_btl_excluded_non_btl_gets_blended(
        self,
        calculator: SupportingFactorCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """
        CP with 1.5m non-BTL + 1.0m BTL (all drawn):
        - total_cp_drawn = 2.5m (includes BTL)
        - Non-BTL gets the tiered blended factor (all within tier 1 threshold)
        - BTL gets 1.0
        """
        exposures = _make_exposures(
            [
                {"ref": "E1", "cp": "CP1", "ead": 1_500_000, "rwa": 600_000, "is_btl": False},
                {"ref": "E2", "cp": "CP1", "ead": 1_000_000, "rwa": 400_000, "is_btl": True},
            ]
        )

        result = calculator.apply_factors(exposures, crr_config).collect()

        # Both exposures should see total_cp_drawn = 2.5m (BTL included)
        assert result.filter(pl.col("exposure_reference") == "E1")["total_cp_drawn"][0] == 2_500_000
        assert result.filter(pl.col("exposure_reference") == "E2")["total_cp_drawn"][0] == 2_500_000

        # Non-BTL (E1) gets the SME factor < 1.0
        sf_e1 = result.filter(pl.col("exposure_reference") == "E1")["supporting_factor"][0]
        assert sf_e1 < 1.0, "Non-BTL exposure should get SME factor"

        # BTL (E2) gets factor = 1.0
        sf_e2 = result.filter(pl.col("exposure_reference") == "E2")["supporting_factor"][0]
        assert sf_e2 == pytest.approx(1.0), "BTL exposure should get factor 1.0"

        # Non-BTL RWA should be reduced
        rwa_e1 = result.filter(pl.col("exposure_reference") == "E1")["rwa_post_factor"][0]
        assert rwa_e1 < 600_000

        # BTL RWA should be unchanged
        rwa_e2 = result.filter(pl.col("exposure_reference") == "E2")["rwa_post_factor"][0]
        assert rwa_e2 == pytest.approx(400_000)

    def test_btl_contributes_to_total_cp_drawn(
        self,
        calculator: SupportingFactorCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """total_cp_drawn = 3.0m (includes 2.0m BTL)."""
        exposures = _make_exposures(
            [
                {"ref": "E1", "cp": "CP1", "ead": 1_000_000, "rwa": 400_000, "is_btl": False},
                {"ref": "E2", "cp": "CP1", "ead": 2_000_000, "rwa": 800_000, "is_btl": True},
            ]
        )

        result = calculator.apply_factors(exposures, crr_config).collect()

        # total_cp_drawn should include BTL
        total_cp = result["total_cp_drawn"][0]
        assert total_cp == pytest.approx(3_000_000)

    def test_all_btl_no_factor(
        self,
        calculator: SupportingFactorCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """CP with only BTL exposures: all get 1.0."""
        exposures = _make_exposures(
            [
                {"ref": "E1", "cp": "CP1", "ead": 1_000_000, "rwa": 400_000, "is_btl": True},
                {"ref": "E2", "cp": "CP1", "ead": 500_000, "rwa": 200_000, "is_btl": True},
            ]
        )

        result = calculator.apply_factors(exposures, crr_config).collect()

        assert result["supporting_factor"].to_list() == pytest.approx([1.0, 1.0])
        assert result["rwa_post_factor"].to_list() == pytest.approx([400_000, 200_000])

    def test_missing_btl_column_defaults_false(
        self,
        calculator: SupportingFactorCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """No is_buy_to_let column -> same as all False (backward compat)."""
        exposures = _make_exposures(
            [
                {"ref": "E1", "cp": "CP1", "ead": 1_000_000, "rwa": 400_000},
            ],
            include_btl=False,
        )

        result = calculator.apply_factors(exposures, crr_config).collect()

        # Should get SME factor applied normally
        sf = result["supporting_factor"][0]
        assert sf < 1.0, "Without BTL column, should behave as all non-BTL"

    def test_btl_false_normal_factor(
        self,
        calculator: SupportingFactorCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """Explicit is_buy_to_let=False behaves same as column missing."""
        exposures = _make_exposures(
            [
                {"ref": "E1", "cp": "CP1", "ead": 1_000_000, "rwa": 400_000, "is_btl": False},
            ]
        )

        result = calculator.apply_factors(exposures, crr_config).collect()

        sf = result["supporting_factor"][0]
        assert sf < 1.0, "Non-BTL should get SME factor"

    def test_non_sme_with_btl_unaffected(
        self,
        calculator: SupportingFactorCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """Non-SME CP: BTL flag irrelevant, factor always 1.0."""
        exposures = _make_exposures(
            [
                {
                    "ref": "E1",
                    "cp": "CP1",
                    "ead": 1_000_000,
                    "rwa": 400_000,
                    "is_sme": False,
                    "is_btl": True,
                },
                {
                    "ref": "E2",
                    "cp": "CP1",
                    "ead": 500_000,
                    "rwa": 200_000,
                    "is_sme": False,
                    "is_btl": False,
                },
            ]
        )

        result = calculator.apply_factors(exposures, crr_config).collect()

        assert result["supporting_factor"].to_list() == pytest.approx([1.0, 1.0])

    def test_btl_with_infrastructure(
        self,
        calculator: SupportingFactorCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """BTL excludes SME factor but infrastructure factor still applies."""
        exposures = _make_exposures(
            [
                {
                    "ref": "E1",
                    "cp": "CP1",
                    "ead": 1_000_000,
                    "rwa": 400_000,
                    "is_btl": True,
                    "is_infra": True,
                },
            ]
        )

        result = calculator.apply_factors(exposures, crr_config).collect()

        # Infrastructure factor should apply (0.75) even though BTL
        sf = result["supporting_factor"][0]
        assert sf == pytest.approx(0.75), "Infrastructure factor should still apply to BTL"
        assert result["rwa_post_factor"][0] == pytest.approx(300_000)


class TestDrawnOnlyTierWeighting:
    """SME tier threshold uses drawn_amount + interest, not ead_final."""

    def test_drawn_only_determines_tier(
        self,
        calculator: SupportingFactorCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """
        Counterparty with 1m drawn + 2m undrawn:
        - ead_final = 3m (includes CCF-adjusted undrawn)
        - drawn_amount = 1m → tier based on 1m (all tier 1) → factor = 0.7619
        - NOT based on 3m (which would produce blended factor)
        """
        exposures = _make_exposures(
            [
                {
                    "ref": "E1",
                    "cp": "CP1",
                    "drawn": 1_000_000,
                    "interest": 0.0,
                    "ead": 3_000_000,  # includes undrawn via CCF
                    "rwa": 3_000_000,
                },
            ]
        )

        result = calculator.apply_factors(exposures, crr_config).collect()

        sf = result["supporting_factor"][0]
        assert sf == pytest.approx(0.7619, rel=0.001), (
            f"Factor should be pure tier 1 (0.7619) based on 1m drawn, got {sf}"
        )

    def test_mixed_drawn_undrawn_counterparty(
        self,
        calculator: SupportingFactorCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """
        Two exposures to same counterparty, total drawn = 4m.
        E1: 2m drawn, 3m ead (has undrawn)
        E2: 2m drawn, 2m ead (fully drawn)
        Total drawn = 4m → blended factor based on 4m, NOT 5m.
        """
        threshold_gbp = float(
            crr_config.supporting_factors.sme_exposure_threshold_eur * crr_config.eur_gbp_rate
        )

        exposures = _make_exposures(
            [
                {"ref": "E1", "cp": "CP1", "drawn": 2_000_000, "ead": 3_000_000, "rwa": 3_000_000},
                {"ref": "E2", "cp": "CP1", "drawn": 2_000_000, "ead": 2_000_000, "rwa": 2_000_000},
            ]
        )

        result = calculator.apply_factors(exposures, crr_config).collect()

        # total_cp_drawn = 4m (not 5m)
        assert result["total_cp_drawn"][0] == pytest.approx(4_000_000)

        # Blended factor for 4m drawn
        expected_factor = (
            min(4_000_000, threshold_gbp) * 0.7619 + max(4_000_000 - threshold_gbp, 0) * 0.85
        ) / 4_000_000
        sf = result["supporting_factor"][0]
        assert sf == pytest.approx(expected_factor, rel=0.001), (
            f"Factor based on 4m drawn should be {expected_factor:.4f}, got {sf}"
        )

    def test_zero_drawn_undrawn_only_gets_tier1(
        self,
        calculator: SupportingFactorCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """
        Counterparty with zero drawn (only undrawn commitments):
        - drawn_amount = 0 → falls within tier 1 → factor = 0.7619
        """
        exposures = _make_exposures(
            [
                {
                    "ref": "E1",
                    "cp": "CP1",
                    "drawn": 0.0,
                    "interest": 0.0,
                    "ead": 2_000_000,  # all from undrawn via CCF
                    "rwa": 2_000_000,
                },
            ]
        )

        result = calculator.apply_factors(exposures, crr_config).collect()

        sf = result["supporting_factor"][0]
        assert sf == pytest.approx(0.7619, rel=0.001), (
            f"Zero drawn should get pure tier 1 factor 0.7619, got {sf}"
        )

    def test_interest_included_in_drawn_total(
        self,
        calculator: SupportingFactorCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """
        drawn_amount + interest = on-balance-sheet total for tiering.
        2m drawn + 0.2m interest = 2.2m → near threshold.
        """
        threshold_gbp = float(
            crr_config.supporting_factors.sme_exposure_threshold_eur * crr_config.eur_gbp_rate
        )

        exposures = _make_exposures(
            [
                {
                    "ref": "E1",
                    "cp": "CP1",
                    "drawn": 2_000_000,
                    "interest": 200_000.0,
                    "ead": 2_500_000,
                    "rwa": 2_500_000,
                },
            ]
        )

        result = calculator.apply_factors(exposures, crr_config).collect()

        # total_cp_drawn = 2.2m (drawn + interest)
        total = result["total_cp_drawn"][0]
        assert total == pytest.approx(2_200_000)

        # Factor based on 2.2m drawn+interest
        drawn_total = 2_200_000
        expected_factor = (
            min(drawn_total, threshold_gbp) * 0.7619 + max(drawn_total - threshold_gbp, 0) * 0.85
        ) / drawn_total
        sf = result["supporting_factor"][0]
        assert sf == pytest.approx(expected_factor, rel=0.001)

    def test_fallback_to_ead_when_drawn_missing(
        self,
        calculator: SupportingFactorCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """Without drawn_amount column, falls back to ead_final (backward compat)."""
        exposures = _make_exposures(
            [
                {"ref": "E1", "cp": "CP1", "ead": 1_000_000, "rwa": 400_000},
            ],
            include_drawn=False,
        )

        result = calculator.apply_factors(exposures, crr_config).collect()

        # Should still get SME factor based on ead_final
        sf = result["supporting_factor"][0]
        assert sf < 1.0, "Fallback to ead_final should still apply SME factor"
        assert sf == pytest.approx(0.7619, rel=0.001)

    def test_large_drawn_small_ead_uses_drawn_for_tier(
        self,
        calculator: SupportingFactorCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """
        Edge case: drawn > ead (possible after collateral deductions).
        Tier should still be based on drawn amount.
        """
        threshold_gbp = float(
            crr_config.supporting_factors.sme_exposure_threshold_eur * crr_config.eur_gbp_rate
        )

        exposures = _make_exposures(
            [
                {
                    "ref": "E1",
                    "cp": "CP1",
                    "drawn": 5_000_000,
                    "interest": 0.0,
                    "ead": 1_000_000,  # reduced by collateral
                    "rwa": 1_000_000,
                },
            ]
        )

        result = calculator.apply_factors(exposures, crr_config).collect()

        # Factor based on 5m drawn (blended), not 1m ead
        expected_factor = (
            min(5_000_000, threshold_gbp) * 0.7619 + max(5_000_000 - threshold_gbp, 0) * 0.85
        ) / 5_000_000
        sf = result["supporting_factor"][0]
        assert sf == pytest.approx(expected_factor, rel=0.001), (
            f"Factor should be based on 5m drawn ({expected_factor:.4f}), got {sf}"
        )


class TestMissingCounterpartyReferenceWarning:
    """P1.31: Missing counterparty_reference emits SF001 warning.

    CRR Art. 501 requires the EUR 2.5m tier threshold to be evaluated at the
    counterparty level. When counterparty_reference is absent, the calculator
    falls back to per-exposure drawn amounts, which can produce an incorrect
    tier classification and a wrong supporting factor.
    """

    def test_warning_emitted_when_counterparty_absent(
        self,
        calculator: SupportingFactorCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """SF001 warning emitted when counterparty_reference column is absent."""
        exposures = _make_exposures(
            [{"ref": "E1", "cp": "CP1", "ead": 1_000_000, "rwa": 400_000}],
            include_counterparty=False,
        )

        errors: list[CalculationError] = []
        calculator.apply_factors(exposures, crr_config, errors=errors)

        assert len(errors) == 1
        assert errors[0].code == ERROR_SME_MISSING_COUNTERPARTY_REF
        assert errors[0].severity == ErrorSeverity.WARNING
        assert errors[0].category == ErrorCategory.DATA_QUALITY
        assert "counterparty_reference" in errors[0].message
        assert "CRR Art. 501" in (errors[0].regulatory_reference or "")

    def test_no_warning_when_counterparty_present(
        self,
        calculator: SupportingFactorCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """No SF001 warning when counterparty_reference column is present."""
        exposures = _make_exposures(
            [{"ref": "E1", "cp": "CP1", "ead": 1_000_000, "rwa": 400_000}],
            include_counterparty=True,
        )

        errors: list[CalculationError] = []
        calculator.apply_factors(exposures, crr_config, errors=errors)

        assert len(errors) == 0

    def test_no_warning_when_no_sme_exposures(
        self,
        calculator: SupportingFactorCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """No warning when is_sme column is absent (no SME exposures)."""
        data = {
            "exposure_reference": ["E1"],
            "ead_final": [1_000_000.0],
            "rwa_pre_factor": [400_000.0],
            "is_infrastructure": [False],
        }
        exposures = pl.LazyFrame(data)

        errors: list[CalculationError] = []
        calculator.apply_factors(exposures, crr_config, errors=errors)

        assert len(errors) == 0

    def test_no_warning_when_errors_not_provided(
        self,
        calculator: SupportingFactorCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """No error when errors parameter is not provided (backward compat)."""
        exposures = _make_exposures(
            [{"ref": "E1", "cp": "CP1", "ead": 1_000_000, "rwa": 400_000}],
            include_counterparty=False,
        )

        # Should not raise — errors=None by default
        result = calculator.apply_factors(exposures, crr_config).collect()
        assert result["supporting_factor"][0] < 1.0

    def test_no_warning_under_basel_31(
        self,
        calculator: SupportingFactorCalculator,
    ) -> None:
        """No warning under Basel 3.1 (supporting factors disabled)."""
        b31_config = CalculationConfig.basel_3_1(reporting_date=date(2030, 6, 30))
        exposures = _make_exposures(
            [{"ref": "E1", "cp": "CP1", "ead": 1_000_000, "rwa": 400_000}],
            include_counterparty=False,
        )

        errors: list[CalculationError] = []
        calculator.apply_factors(exposures, b31_config, errors=errors)

        assert len(errors) == 0

    def test_per_exposure_fallback_wrong_tier_for_aggregate_above_threshold(
        self,
        calculator: SupportingFactorCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """
        Demonstrates the tier misclassification when counterparty_reference is absent.

        Two exposures to the same counterparty: 1.5m + 1.5m = 3m aggregate.
        With counterparty aggregation: 3m > EUR 2.5m threshold → blended factor.
        Without aggregation: each 1.5m < threshold → pure tier 1 factor (0.7619).

        The per-exposure fallback produces an incorrectly low factor because
        it doesn't see the counterparty aggregate exceeding the threshold.
        """
        threshold_gbp = float(
            crr_config.supporting_factors.sme_exposure_threshold_eur * crr_config.eur_gbp_rate
        )

        # WITH counterparty reference — correct aggregation
        exposures_with_cp = _make_exposures(
            [
                {"ref": "E1", "cp": "CP1", "ead": 1_500_000, "rwa": 600_000},
                {"ref": "E2", "cp": "CP1", "ead": 1_500_000, "rwa": 600_000},
            ],
            include_counterparty=True,
        )
        result_correct = calculator.apply_factors(exposures_with_cp, crr_config).collect()
        sf_correct = result_correct["supporting_factor"][0]

        # WITHOUT counterparty reference — per-exposure fallback
        exposures_no_cp = _make_exposures(
            [
                {"ref": "E1", "cp": "CP1", "ead": 1_500_000, "rwa": 600_000},
                {"ref": "E2", "cp": "CP1", "ead": 1_500_000, "rwa": 600_000},
            ],
            include_counterparty=False,
        )
        errors: list[CalculationError] = []
        result_fallback = calculator.apply_factors(
            exposures_no_cp, crr_config, errors=errors
        ).collect()
        sf_fallback = result_fallback["supporting_factor"][0]

        # Correct factor: blended for 3m aggregate (above threshold)
        expected_correct = (
            min(3_000_000, threshold_gbp) * 0.7619 + max(3_000_000 - threshold_gbp, 0) * 0.85
        ) / 3_000_000
        assert sf_correct == pytest.approx(expected_correct, rel=0.001)

        # Fallback factor: pure tier 1 for 1.5m each (below threshold)
        assert sf_fallback == pytest.approx(0.7619, rel=0.001)

        # The fallback produces a LOWER factor (more capital relief) — incorrect
        assert sf_fallback < sf_correct, (
            f"Fallback factor {sf_fallback:.4f} should be lower than correct "
            f"{sf_correct:.4f}, demonstrating capital understatement"
        )

        # Warning was emitted
        assert len(errors) == 1
        assert errors[0].code == ERROR_SME_MISSING_COUNTERPARTY_REF

    def test_warning_field_name_is_counterparty_reference(
        self,
        calculator: SupportingFactorCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """SF001 warning has field_name set for diagnostic filtering."""
        exposures = _make_exposures(
            [{"ref": "E1", "cp": "CP1", "ead": 1_000_000, "rwa": 400_000}],
            include_counterparty=False,
        )

        errors: list[CalculationError] = []
        calculator.apply_factors(exposures, crr_config, errors=errors)

        assert errors[0].field_name == "counterparty_reference"
