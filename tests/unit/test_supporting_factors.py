"""
Unit tests for supporting factors (CRR2 Art. 501).

Tests cover:
- Residential-property collateral netting from E* (Art. 501 carve-out:
  each row's contribution to E* is reduced by residential_collateral_value,
  capped at drawn; mirrors the retail-threshold logic in Art. 123(c))
- BTL rows still receive factor=1.0 (separate eligibility gate; in practice
  a BTL row's RRE coverage usually equals or exceeds its drawn, so its E*
  contribution naturally lands at 0)
- Drawn-only tier weighting: tier calculation uses drawn_amount + interest,
  NOT ead_final (which includes CCF-adjusted undrawn commitments)
- Infrastructure factor interaction with BTL
- Backward compatibility when drawn_amount column is missing
- Group-of-connected-clients aggregation via lending_group_reference
- Missing counterparty/lending-group reference warning (P1.31)
"""

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.contracts.errors import ERROR_SME_MISSING_COUNTERPARTY_REF, CalculationError
from rwa_calc.domain.enums import ErrorCategory, ErrorSeverity
from rwa_calc.engine.supporting_factors import SupportingFactorCalculator
from rwa_calc.engine.thresholds import regulatory_threshold
from rwa_calc.rulebook import RulepackV0


def _sme_exposure_threshold_gbp(config: CalculationConfig) -> float:
    """CRR Art. 501 SME tiered-factor exposure threshold (GBP) from the rulepack."""
    pack = RulepackV0.from_config(config).pack
    return float(regulatory_threshold(pack, "sme_exposure_threshold", config.eur_gbp_rate))


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
    include_lending_group: bool = True,
    include_res_coll: bool = True,
) -> pl.LazyFrame:
    """Build a LazyFrame of exposures for supporting factor tests.

    Each row dict supports keys:
        ref, cp, ead, rwa, drawn (defaults to ead), interest (defaults to 0),
        is_sme (True), is_infra (False), is_btl (False), lending_group (None),
        res_coll (defaults to 0.0 — residential_collateral_value covering this row).

    ``lending_group_reference`` is a crm_exit contract column and is now
    carried by default (null-valued unless a row sets ``lending_group``) —
    the engine reads it directly and falls back to counterparty on null
    VALUES rather than column absence.
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
    if include_lending_group:
        data["lending_group_reference"] = [r.get("lending_group") for r in rows]
    if include_res_coll:
        data["residential_collateral_value"] = [float(r.get("res_coll", 0.0)) for r in rows]
    return pl.LazyFrame(data)


class TestBTLExcludedFromSMEFactor:
    """BTL exposures get supporting_factor=1.0 regardless of E* netting.

    CRR Art. 501 carves out claims secured on residential property collateral
    from the aggregate amount owed (E*). The engine implements this carve-out
    by subtracting ``residential_collateral_value`` (capped at drawn) from
    each row's contribution to E* — mirroring the retail-threshold logic in
    Art. 123(c). In practice a BTL loan's RRE collateral typically equals or
    exceeds its drawn balance, so a BTL row contributes 0 to E* by virtue of
    the netting; these tests pin that scenario explicitly.

    The BTL flag continues to gate the SF eligibility independently (BTL
    rows always receive factor=1.0).
    """

    def test_btl_excluded_non_btl_below_threshold_gets_tier1(
        self,
        calculator: SupportingFactorCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """
        CP with 1.5m non-BTL + 1.0m BTL (BTL fully covered by RRE):
        - total_cp_drawn = 1.5m (BTL contribution netted to 0 by RRE coverage)
        - Non-BTL gets pure Tier 1 factor (1.5m < EUR 2.5m threshold)
        - BTL gets 1.0
        """
        exposures = _make_exposures(
            [
                {"ref": "E1", "cp": "CP1", "ead": 1_500_000, "rwa": 600_000, "is_btl": False},
                {
                    "ref": "E2",
                    "cp": "CP1",
                    "ead": 1_000_000,
                    "rwa": 400_000,
                    "is_btl": True,
                    "res_coll": 1_000_000,  # fully secured on residential property
                },
            ]
        )

        result = calculator.apply_factors(exposures, crr_config).collect()

        # Both exposures should see total_cp_drawn = 1.5m (BTL netted to 0 in E*)
        assert result.filter(pl.col("exposure_reference") == "E1")["total_cp_drawn"][0] == 1_500_000
        assert result.filter(pl.col("exposure_reference") == "E2")["total_cp_drawn"][0] == 1_500_000

        # Non-BTL (E1) gets pure Tier 1 (0.7619) since E* = 1.5m < threshold
        sf_e1 = result.filter(pl.col("exposure_reference") == "E1")["supporting_factor"][0]
        assert sf_e1 == pytest.approx(0.7619, rel=0.001)

        # BTL (E2) gets factor = 1.0
        sf_e2 = result.filter(pl.col("exposure_reference") == "E2")["supporting_factor"][0]
        assert sf_e2 == pytest.approx(1.0), "BTL exposure should get factor 1.0"

        # Non-BTL RWA should be reduced
        rwa_e1 = result.filter(pl.col("exposure_reference") == "E1")["rwa_post_factor"][0]
        assert rwa_e1 < 600_000

        # BTL RWA should be unchanged
        rwa_e2 = result.filter(pl.col("exposure_reference") == "E2")["rwa_post_factor"][0]
        assert rwa_e2 == pytest.approx(400_000)

    def test_btl_excluded_from_total_cp_drawn(
        self,
        calculator: SupportingFactorCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """total_cp_drawn = 1.0m (Art. 501 nets the 2.0m BTL out of E* via RRE coverage)."""
        exposures = _make_exposures(
            [
                {"ref": "E1", "cp": "CP1", "ead": 1_000_000, "rwa": 400_000, "is_btl": False},
                {
                    "ref": "E2",
                    "cp": "CP1",
                    "ead": 2_000_000,
                    "rwa": 800_000,
                    "is_btl": True,
                    "res_coll": 2_000_000,  # fully secured on residential property
                },
            ]
        )

        result = calculator.apply_factors(exposures, crr_config).collect()

        # total_cp_drawn nets BTL drawn down to 0 via RRE coverage per Art. 501
        total_cp = result["total_cp_drawn"][0]
        assert total_cp == pytest.approx(1_000_000)

    def test_all_btl_no_factor(
        self,
        calculator: SupportingFactorCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """CP with only BTL exposures (all fully RRE-secured): all get 1.0."""
        exposures = _make_exposures(
            [
                {
                    "ref": "E1",
                    "cp": "CP1",
                    "ead": 1_000_000,
                    "rwa": 400_000,
                    "is_btl": True,
                    "res_coll": 1_000_000,
                },
                {
                    "ref": "E2",
                    "cp": "CP1",
                    "ead": 500_000,
                    "rwa": 200_000,
                    "is_btl": True,
                    "res_coll": 500_000,
                },
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
        threshold_gbp = _sme_exposure_threshold_gbp(crr_config)

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
        threshold_gbp = _sme_exposure_threshold_gbp(crr_config)

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
        threshold_gbp = _sme_exposure_threshold_gbp(crr_config)

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
        """No warning when no exposures are SME-flagged.

        ``is_sme`` is a crm_exit contract column the engine reads directly,
        so the frame carries it (all False) with the group-key columns.
        """
        data = {
            "exposure_reference": ["E1"],
            "counterparty_reference": ["CP1"],
            "lending_group_reference": [None],
            "ead_final": [1_000_000.0],
            "rwa_pre_factor": [400_000.0],
            "is_sme": [False],
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
        threshold_gbp = _sme_exposure_threshold_gbp(crr_config)

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


class TestLendingGroupAggregation:
    """E* aggregates across the SME's group of connected clients (CRR Art. 501).

    The implementation aggregates drawn over `lending_group_reference` first
    and falls back to `counterparty_reference` when no lending group is
    mapped — mirroring the retail aggregation pattern in engine/hierarchy.py.
    """

    def test_aggregates_drawn_across_lending_group(
        self,
        calculator: SupportingFactorCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """
        Two SMEs (CP1, CP2) in the same lending group, GBP 1.5m drawn each.
        Without group aggregation each falls below the EUR 2.5m threshold
        and would get pure Tier 1. With Art. 501 group aggregation, E* = 3m
        and both rows get the blended factor.
        """
        threshold_gbp = _sme_exposure_threshold_gbp(crr_config)

        exposures = _make_exposures(
            [
                {
                    "ref": "E1",
                    "cp": "CP1",
                    "ead": 1_500_000,
                    "rwa": 600_000,
                    "lending_group": "LG1",
                },
                {
                    "ref": "E2",
                    "cp": "CP2",
                    "ead": 1_500_000,
                    "rwa": 600_000,
                    "lending_group": "LG1",
                },
            ],
            include_lending_group=True,
        )

        result = calculator.apply_factors(exposures, crr_config).collect()

        # E* = 3m for both rows
        assert result["total_cp_drawn"].to_list() == pytest.approx([3_000_000, 3_000_000])

        expected_factor = (
            min(3_000_000, threshold_gbp) * 0.7619 + max(3_000_000 - threshold_gbp, 0) * 0.85
        ) / 3_000_000
        assert result["supporting_factor"].to_list() == pytest.approx(
            [expected_factor, expected_factor], rel=0.001
        )
        # Sanity: blended factor strictly worse than pure Tier 1
        assert expected_factor > 0.7619

    def test_falls_back_to_counterparty_when_lending_group_null(
        self,
        calculator: SupportingFactorCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """
        Lending group column present but null — fallback to counterparty
        aggregation preserves prior behaviour.
        """
        threshold_gbp = _sme_exposure_threshold_gbp(crr_config)

        exposures = _make_exposures(
            [
                {"ref": "E1", "cp": "CP1", "ead": 1_500_000, "rwa": 600_000, "lending_group": None},
                {"ref": "E2", "cp": "CP1", "ead": 1_500_000, "rwa": 600_000, "lending_group": None},
            ],
            include_lending_group=True,
        )

        result = calculator.apply_factors(exposures, crr_config).collect()

        # E* = 3m via counterparty fallback
        assert result["total_cp_drawn"].to_list() == pytest.approx([3_000_000, 3_000_000])

        expected_factor = (
            min(3_000_000, threshold_gbp) * 0.7619 + max(3_000_000 - threshold_gbp, 0) * 0.85
        ) / 3_000_000
        assert result["supporting_factor"].to_list() == pytest.approx(
            [expected_factor, expected_factor], rel=0.001
        )

    def test_three_member_group_below_threshold_individually(
        self,
        calculator: SupportingFactorCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """
        Three SMEs in same lending group, each well below threshold (1m drawn).
        Aggregate E* = 3m → blended factor on all three. Regression test for
        the gap where counterparty-only aggregation would give 0.7619 each.
        """
        threshold_gbp = _sme_exposure_threshold_gbp(crr_config)

        exposures = _make_exposures(
            [
                {
                    "ref": "E1",
                    "cp": "CP1",
                    "ead": 1_000_000,
                    "rwa": 400_000,
                    "lending_group": "LG1",
                },
                {
                    "ref": "E2",
                    "cp": "CP2",
                    "ead": 1_000_000,
                    "rwa": 400_000,
                    "lending_group": "LG1",
                },
                {
                    "ref": "E3",
                    "cp": "CP3",
                    "ead": 1_000_000,
                    "rwa": 400_000,
                    "lending_group": "LG1",
                },
            ],
            include_lending_group=True,
        )

        result = calculator.apply_factors(exposures, crr_config).collect()

        assert result["total_cp_drawn"].to_list() == pytest.approx(
            [3_000_000, 3_000_000, 3_000_000]
        )

        expected_factor = (
            min(3_000_000, threshold_gbp) * 0.7619 + max(3_000_000 - threshold_gbp, 0) * 0.85
        ) / 3_000_000
        assert result["supporting_factor"].to_list() == pytest.approx(
            [expected_factor] * 3, rel=0.001
        )
        assert expected_factor > 0.7619

    def test_lending_group_with_mixed_sme_non_sme_aggregates_whole_group(
        self,
        calculator: SupportingFactorCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """
        CRR Art. 501 says E* is the total amount owed by 'the SME OR the group
        of connected clients of the SME'. When a lending group spans an SME
        and a non-SME, the non-SME's drawn STILL counts toward E* (whole-group
        reading). The SF is then applied only to the SME-flagged row; the
        non-SME row gets factor=1.0.
        """
        threshold_gbp = _sme_exposure_threshold_gbp(crr_config)

        exposures = _make_exposures(
            [
                {
                    "ref": "E1",
                    "cp": "CP1",
                    "ead": 1_500_000,
                    "rwa": 600_000,
                    "is_sme": True,
                    "lending_group": "LG1",
                },
                {
                    "ref": "E2",
                    "cp": "CP2",
                    "ead": 5_000_000,
                    "rwa": 2_000_000,
                    "is_sme": False,
                    "lending_group": "LG1",
                },
            ],
            include_lending_group=True,
        )

        result = calculator.apply_factors(exposures, crr_config).collect()

        # E1 (SME) sees E* = 6.5m (whole group)
        e1 = result.filter(pl.col("exposure_reference") == "E1")
        assert e1["total_cp_drawn"][0] == pytest.approx(6_500_000)
        expected_factor = (
            min(6_500_000, threshold_gbp) * 0.7619 + max(6_500_000 - threshold_gbp, 0) * 0.85
        ) / 6_500_000
        assert e1["supporting_factor"][0] == pytest.approx(expected_factor, rel=0.001)

        # E2 (non-SME) gets factor = 1.0 regardless
        e2 = result.filter(pl.col("exposure_reference") == "E2")
        assert e2["supporting_factor"][0] == pytest.approx(1.0)

    def test_btl_in_lending_group_does_not_count_toward_e_star(
        self,
        calculator: SupportingFactorCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """
        Lending group with one non-BTL SME (1.5m drawn) and one BTL SME (3m
        drawn, fully RRE-secured). Art. 501 carves residential-property
        coverage out of E* (per-row netting), so the BTL row contributes 0
        to the group sum: E* = 1.5m and the non-BTL row gets pure Tier 1.
        The BTL row gets factor=1.0 regardless.
        """
        exposures = _make_exposures(
            [
                {
                    "ref": "E1",
                    "cp": "CP1",
                    "ead": 1_500_000,
                    "rwa": 600_000,
                    "is_btl": False,
                    "lending_group": "LG1",
                },
                {
                    "ref": "E2",
                    "cp": "CP2",
                    "ead": 3_000_000,
                    "rwa": 1_200_000,
                    "is_btl": True,
                    "res_coll": 3_000_000,  # fully secured on residential property
                    "lending_group": "LG1",
                },
            ],
            include_lending_group=True,
        )

        result = calculator.apply_factors(exposures, crr_config).collect()

        # E* = 1.5m (BTL row's drawn fully netted by its RRE collateral)
        assert result["total_cp_drawn"].to_list() == pytest.approx([1_500_000, 1_500_000])

        e1 = result.filter(pl.col("exposure_reference") == "E1")
        assert e1["supporting_factor"][0] == pytest.approx(0.7619, rel=0.001)

        e2 = result.filter(pl.col("exposure_reference") == "E2")
        assert e2["supporting_factor"][0] == pytest.approx(1.0)

    def test_null_lending_group_values_use_counterparty_only(
        self,
        calculator: SupportingFactorCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """
        Frame with null lending_group_reference values throughout: the
        counterparty fallback path runs cleanly and no SF001 warning is
        emitted (because counterparty_reference IS present).
        """
        threshold_gbp = _sme_exposure_threshold_gbp(crr_config)

        exposures = _make_exposures(
            [
                {"ref": "E1", "cp": "CP1", "ead": 2_000_000, "rwa": 800_000},
                {"ref": "E2", "cp": "CP1", "ead": 2_000_000, "rwa": 800_000},
            ],
        )

        errors: list[CalculationError] = []
        result = calculator.apply_factors(exposures, crr_config, errors=errors).collect()

        assert len(errors) == 0
        assert result["total_cp_drawn"].to_list() == pytest.approx([4_000_000, 4_000_000])

        expected_factor = (
            min(4_000_000, threshold_gbp) * 0.7619 + max(4_000_000 - threshold_gbp, 0) * 0.85
        ) / 4_000_000
        assert result["supporting_factor"].to_list() == pytest.approx(
            [expected_factor, expected_factor], rel=0.001
        )


class TestResidentialCollateralNettedFromEStar:
    """E* is reduced by ``residential_collateral_value`` per CRR Art. 501.

    The carve-out in Art. 501 ("excluding claims or contingent claims secured
    on residential property collateral") is implemented per-row, mirroring
    the retail-threshold logic in ``engine/hierarchy.py`` (Art. 123(c)):

        contribution_to_E* = max(0, drawn - residential_collateral_value)

    This applies independently of the BTL flag — a non-BTL SME secured on
    residential property still has the secured portion netted from E*.
    """

    def test_partial_rre_coverage_reduces_e_star_contribution(
        self,
        calculator: SupportingFactorCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """
        Non-BTL SME with £1.0m drawn and £0.6m residential collateral:
        contribution to E* = £0.4m (drawn minus collateral, capped at drawn).
        """
        exposures = _make_exposures(
            [
                {
                    "ref": "E1",
                    "cp": "CP1",
                    "ead": 1_000_000,
                    "rwa": 400_000,
                    "is_btl": False,
                    "res_coll": 600_000,
                },
            ]
        )

        result = calculator.apply_factors(exposures, crr_config).collect()

        assert result["total_cp_drawn"][0] == pytest.approx(400_000)
        # E* = 400k well below threshold → pure Tier 1 factor
        assert result["supporting_factor"][0] == pytest.approx(0.7619, rel=0.001)

    def test_full_rre_coverage_zeros_contribution(
        self,
        calculator: SupportingFactorCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """SME with res_coll >= drawn contributes 0 to E*."""
        exposures = _make_exposures(
            [
                {
                    "ref": "E1",
                    "cp": "CP1",
                    "ead": 800_000,
                    "rwa": 320_000,
                    "is_btl": False,
                    "res_coll": 800_000,
                },
                {"ref": "E2", "cp": "CP1", "ead": 500_000, "rwa": 200_000, "res_coll": 0.0},
            ]
        )

        result = calculator.apply_factors(exposures, crr_config).collect()

        # E* = 0.5m (the secured row nets to 0)
        assert result["total_cp_drawn"].to_list() == pytest.approx([500_000, 500_000])

    def test_rre_coverage_capped_at_drawn(
        self,
        calculator: SupportingFactorCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """res_coll > drawn must not produce a negative contribution to E*."""
        exposures = _make_exposures(
            [
                {
                    "ref": "E1",
                    "cp": "CP1",
                    "ead": 500_000,
                    "rwa": 200_000,
                    "res_coll": 2_000_000,  # collateral exceeds drawn
                },
                {"ref": "E2", "cp": "CP1", "ead": 1_000_000, "rwa": 400_000, "res_coll": 0.0},
            ]
        )

        result = calculator.apply_factors(exposures, crr_config).collect()

        # E1 contributes 0 (not negative); E* = 1.0m from E2 alone
        assert result["total_cp_drawn"].to_list() == pytest.approx([1_000_000, 1_000_000])

    def test_partial_rre_coverage_in_lending_group(
        self,
        calculator: SupportingFactorCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """
        Lending group with one fully-unsecured £2.0m SME and one £1.0m SME
        with £600k RRE coverage. E* = 2.0m + 0.4m = 2.4m → just under
        the EUR 2.5m threshold (~£2.18m at 0.8732 FX). The group sum
        crosses the threshold despite either row being below it alone.
        """
        threshold_gbp = _sme_exposure_threshold_gbp(crr_config)

        exposures = _make_exposures(
            [
                {
                    "ref": "E1",
                    "cp": "CP1",
                    "ead": 2_000_000,
                    "rwa": 800_000,
                    "lending_group": "LG1",
                    "res_coll": 0.0,
                },
                {
                    "ref": "E2",
                    "cp": "CP2",
                    "ead": 1_000_000,
                    "rwa": 400_000,
                    "lending_group": "LG1",
                    "res_coll": 600_000,
                },
            ],
            include_lending_group=True,
        )

        result = calculator.apply_factors(exposures, crr_config).collect()

        # E* = 2.0m + (1.0m - 0.6m) = 2.4m
        assert result["total_cp_drawn"].to_list() == pytest.approx([2_400_000, 2_400_000])

        expected_factor = (
            min(2_400_000, threshold_gbp) * 0.7619 + max(2_400_000 - threshold_gbp, 0) * 0.85
        ) / 2_400_000
        assert result["supporting_factor"].to_list() == pytest.approx(
            [expected_factor, expected_factor], rel=0.001
        )

    def test_missing_residential_collateral_column_no_netting(
        self,
        calculator: SupportingFactorCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """
        Backward compat: frame without ``residential_collateral_value``
        falls back to no netting (the column is optional in the engine).
        """
        exposures = _make_exposures(
            [
                {"ref": "E1", "cp": "CP1", "ead": 1_000_000, "rwa": 400_000},
            ],
            include_res_coll=False,
        )

        result = calculator.apply_factors(exposures, crr_config).collect()

        # No netting → full drawn contributes to E*
        assert result["total_cp_drawn"][0] == pytest.approx(1_000_000)
