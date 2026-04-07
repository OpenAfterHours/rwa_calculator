"""
Tests for Art. 169A/169B LGD Modelling Collateral Method.

PRA PS1/26 Art. 169A: Scope — AIRB firms may use LGD Modelling Collateral
Method to recognise collateral directly in LGD estimates.  When data is
sufficient (Art. 169A(1)(a)), own LGD captures collateral effects.

Art. 169B: When an AIRB firm does not have sufficient data to model a collateral
type/jurisdiction robustly, it falls back to the Foundation Collateral Method
formula (Art. 230/231) with its OWN unsecured LGD as LGDU — not the supervisory
LGDU.  Only Foundation-eligible collateral is recognised.

Test structure:
- Config/enum tests
- Art. 169A full modelling (sufficient data, own LGD kept)
- Art. 169B fallback (insufficient data, FCM formula with own LGDU)
- Foundation election (supervisory LGDU, same as FIRB)
- No-collateral path
- CRR backward compatibility
- Mixed batch tests
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import (
    AIRBCollateralMethod,
    ApproachType,
    PermissionMode,
)
from rwa_calc.engine.crm.collateral import (
    _apply_collateral_unified,
    apply_firb_supervisory_lgd_no_collateral,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _b31_config(
    airb_method: AIRBCollateralMethod = AIRBCollateralMethod.LGD_MODELLING,
) -> CalculationConfig:
    return CalculationConfig.basel_3_1(
        reporting_date=date(2030, 6, 30),
        permission_mode=PermissionMode.IRB,
        airb_collateral_method=airb_method,
    )


def _crr_config() -> CalculationConfig:
    return CalculationConfig.crr(
        reporting_date=date(2025, 12, 31),
        permission_mode=PermissionMode.IRB,
    )


def _make_exposures(
    approach: str = ApproachType.AIRB.value,
    lgd: float = 0.12,
    lgd_unsecured: float | None = None,
    has_sufficient_collateral_data: bool | None = None,
    ead_gross: float = 1_000_000.0,
    seniority: str = "senior",
    include_lgd_unsecured_col: bool = True,
    include_suff_data_col: bool = True,
) -> pl.LazyFrame:
    data: dict = {
        "exposure_reference": ["EXP_001"],
        "approach": [approach],
        "lgd": [lgd],
        "lgd_pre_crm": [lgd],
        "lgd_post_crm": [lgd],
        "ead_gross": [ead_gross],
        "ead_pre_crm": [ead_gross],
        "seniority": [seniority],
        "counterparty_reference": ["CP_001"],
        "currency": ["GBP"],
        "maturity_date": [date(2035, 1, 1)],
    }
    if include_lgd_unsecured_col:
        data["lgd_unsecured"] = [lgd_unsecured]
    if include_suff_data_col:
        data["has_sufficient_collateral_data"] = [has_sufficient_collateral_data]
    return pl.LazyFrame(data)


def _make_collateral(
    beneficiary: str = "EXP_001",
    collateral_type: str = "real_estate",
    market_value: float = 500_000.0,
) -> pl.LazyFrame:
    return pl.LazyFrame(
        {
            "collateral_reference": ["COLL_001"],
            "beneficiary_reference": [beneficiary],
            "beneficiary_type": ["exposure"],
            "collateral_type": [collateral_type],
            "market_value": [market_value],
            "value_after_haircut": [market_value],
            "value_after_maturity_adj": [market_value],
            "is_eligible_financial_collateral": [True],
        }
    )


def _empty_ead_totals() -> pl.LazyFrame:
    return pl.LazyFrame(
        {
            "parent_facility_reference": pl.Series([], dtype=pl.String),
            "_fac_ead_total": pl.Series([], dtype=pl.Float64),
        }
    )


def _empty_cp_totals() -> pl.LazyFrame:
    return pl.LazyFrame(
        {
            "counterparty_reference": pl.Series([], dtype=pl.String),
            "_cp_ead_total": pl.Series([], dtype=pl.Float64),
        }
    )


# ===========================================================================
# 1. Config and enum tests
# ===========================================================================


class TestConfigAndEnum:
    def test_airb_collateral_method_enum_values(self):
        assert AIRBCollateralMethod.LGD_MODELLING == "lgd_modelling"
        assert AIRBCollateralMethod.FOUNDATION == "foundation"

    def test_b31_config_default_lgd_modelling(self):
        config = _b31_config()
        assert config.airb_collateral_method == AIRBCollateralMethod.LGD_MODELLING

    def test_b31_config_foundation_election(self):
        config = _b31_config(AIRBCollateralMethod.FOUNDATION)
        assert config.airb_collateral_method == AIRBCollateralMethod.FOUNDATION

    def test_crr_config_no_airb_method(self):
        config = _crr_config()
        assert config.airb_collateral_method is None

    def test_b31_factory_accepts_airb_method(self):
        config = CalculationConfig.basel_3_1(
            reporting_date=date(2030, 6, 30),
            airb_collateral_method=AIRBCollateralMethod.FOUNDATION,
        )
        assert config.airb_collateral_method == AIRBCollateralMethod.FOUNDATION


# ===========================================================================
# 2. Art. 169A — Full modelling (sufficient data, own LGD kept)
# ===========================================================================


class TestArt169AFullModelling:
    """When AIRB has sufficient data, own LGD captures collateral effects."""

    def test_airb_sufficient_data_keeps_own_lgd_no_collateral(self):
        """AIRB + LGD_MODELLING + sufficient data + no collateral → keep own lgd."""
        config = _b31_config()
        exposures = _make_exposures(
            approach=ApproachType.AIRB.value,
            lgd=0.12,
            lgd_unsecured=0.25,
            has_sufficient_collateral_data=True,
        )
        result = apply_firb_supervisory_lgd_no_collateral(
            exposures, is_basel_3_1=True, config=config
        )
        df = result.collect()
        assert df["lgd_post_crm"][0] == pytest.approx(0.12)

    def test_airb_null_suff_data_defaults_to_sufficient(self):
        """Null has_sufficient_collateral_data → treated as sufficient (True)."""
        config = _b31_config()
        exposures = _make_exposures(
            approach=ApproachType.AIRB.value,
            lgd=0.15,
            lgd_unsecured=0.30,
            has_sufficient_collateral_data=None,
        )
        result = apply_firb_supervisory_lgd_no_collateral(
            exposures, is_basel_3_1=True, config=config
        )
        df = result.collect()
        assert df["lgd_post_crm"][0] == pytest.approx(0.15)

    def test_airb_missing_suff_data_column_keeps_own_lgd(self):
        """When has_sufficient_collateral_data column absent → own LGD kept."""
        config = _b31_config()
        exposures = _make_exposures(
            approach=ApproachType.AIRB.value,
            lgd=0.10,
            include_suff_data_col=False,
        )
        result = apply_firb_supervisory_lgd_no_collateral(
            exposures, is_basel_3_1=True, config=config
        )
        df = result.collect()
        assert df["lgd_post_crm"][0] == pytest.approx(0.10)


# ===========================================================================
# 3. Art. 169B — Insufficient data fallback (FCM formula with own LGDU)
# ===========================================================================


class TestArt169BFallback:
    """When AIRB lacks sufficient data, FCM formula with own unsecured LGD."""

    def test_airb_insufficient_data_no_collateral_uses_own_lgdu(self):
        """AIRB + insufficient data + no collateral → lgd_post_crm = own lgd_unsecured."""
        config = _b31_config()
        exposures = _make_exposures(
            approach=ApproachType.AIRB.value,
            lgd=0.12,
            lgd_unsecured=0.30,
            has_sufficient_collateral_data=False,
        )
        result = apply_firb_supervisory_lgd_no_collateral(
            exposures, is_basel_3_1=True, config=config
        )
        df = result.collect()
        # Art. 169B(2)(c): LGDU = own unsecured LGD = 0.30
        assert df["lgd_post_crm"][0] == pytest.approx(0.30)

    def test_airb_insufficient_data_no_collateral_falls_back_to_lgd(self):
        """When lgd_unsecured is null, fall back to lgd_pre_crm."""
        config = _b31_config()
        exposures = _make_exposures(
            approach=ApproachType.AIRB.value,
            lgd=0.12,
            lgd_unsecured=None,
            has_sufficient_collateral_data=False,
        )
        result = apply_firb_supervisory_lgd_no_collateral(
            exposures, is_basel_3_1=True, config=config
        )
        df = result.collect()
        assert df["lgd_post_crm"][0] == pytest.approx(0.12)

    def test_airb_169b_subordinated_uses_75pct(self):
        """Art. 169B subordinated: LGDU = 75% regardless of own estimate."""
        config = _b31_config()
        exposures = _make_exposures(
            approach=ApproachType.AIRB.value,
            lgd=0.12,
            lgd_unsecured=0.30,
            has_sufficient_collateral_data=False,
            seniority="subordinated",
        )
        result = apply_firb_supervisory_lgd_no_collateral(
            exposures, is_basel_3_1=True, config=config
        )
        df = result.collect()
        assert df["lgd_post_crm"][0] == pytest.approx(0.75)

    def test_airb_169b_with_collateral_uses_formula(self):
        """AIRB + insufficient data + collateral → LGD* formula with own LGDU."""
        config = _b31_config()
        exposures = _make_exposures(
            approach=ApproachType.AIRB.value,
            lgd=0.12,
            lgd_unsecured=0.30,
            has_sufficient_collateral_data=False,
            ead_gross=1_000_000.0,
        )
        collateral = _make_collateral(
            collateral_type="real_estate",
            market_value=700_000.0,
        )
        result = _apply_collateral_unified(
            exposures,
            collateral,
            config,
            _empty_ead_totals(),
            _empty_cp_totals(),
            is_basel_3_1=True,
        )
        df = result.collect()
        # Art. 169B(2): LGD* = LGDS_re × ES/E + own_LGDU × EU/E
        # B31 LGDS for real_estate = 0.20, OC ratio = 1.40
        # effectively_secured = 700000/1.40 = 500000 (capped at EAD=1M)
        # lgd_secured = 0.20 (single type)
        # ES = 500000, EU = 500000
        # LGD* = (0.20 × 500000 + 0.30 × 500000) / 1000000 = 0.25
        assert df["lgd_post_crm"][0] == pytest.approx(0.25)

    def test_airb_169b_vs_firb_different_lgdu(self):
        """Art. 169B uses own LGDU (30%), FIRB uses supervisory (40%)."""
        config = _b31_config()
        # AIRB 169B
        airb_exp = _make_exposures(
            approach=ApproachType.AIRB.value,
            lgd=0.12,
            lgd_unsecured=0.30,
            has_sufficient_collateral_data=False,
        )
        # FIRB
        firb_exp = _make_exposures(
            approach=ApproachType.FIRB.value,
            lgd=0.12,
        )

        collateral = _make_collateral(collateral_type="real_estate", market_value=700_000.0)

        airb_result = _apply_collateral_unified(
            airb_exp,
            collateral,
            config,
            _empty_ead_totals(),
            _empty_cp_totals(),
            is_basel_3_1=True,
        ).collect()

        firb_result = _apply_collateral_unified(
            firb_exp,
            collateral,
            config,
            _empty_ead_totals(),
            _empty_cp_totals(),
            is_basel_3_1=True,
        ).collect()

        # AIRB 169B: (0.20 × 500k + 0.30 × 500k) / 1M = 0.25
        # FIRB: (0.20 × 500k + 0.40 × 500k) / 1M = 0.30
        assert airb_result["lgd_post_crm"][0] == pytest.approx(0.25)
        assert firb_result["lgd_post_crm"][0] == pytest.approx(0.30)
        assert airb_result["lgd_post_crm"][0] < firb_result["lgd_post_crm"][0]

    def test_airb_169b_missing_lgd_unsecured_col_falls_back(self):
        """When lgd_unsecured column is absent, uses lgd_pre_crm as LGDU."""
        config = _b31_config()
        exposures = _make_exposures(
            approach=ApproachType.AIRB.value,
            lgd=0.12,
            has_sufficient_collateral_data=False,
            include_lgd_unsecured_col=False,
        )
        result = apply_firb_supervisory_lgd_no_collateral(
            exposures, is_basel_3_1=True, config=config
        )
        df = result.collect()
        # Falls back to lgd_pre_crm = 0.12
        assert df["lgd_post_crm"][0] == pytest.approx(0.12)


# ===========================================================================
# 4. Foundation election (supervisory LGDU, same as FIRB)
# ===========================================================================


class TestFoundationElection:
    """AIRB firm elects Foundation Collateral Method — same as FIRB."""

    def test_foundation_no_collateral_uses_supervisory_lgdu(self):
        """Foundation election + no collateral → supervisory 40% (non-FSE)."""
        config = _b31_config(AIRBCollateralMethod.FOUNDATION)
        exposures = _make_exposures(
            approach=ApproachType.AIRB.value,
            lgd=0.12,
            lgd_unsecured=0.30,
            has_sufficient_collateral_data=True,
        )
        result = apply_firb_supervisory_lgd_no_collateral(
            exposures, is_basel_3_1=True, config=config
        )
        df = result.collect()
        # Foundation: supervisory LGDU = 40% (non-FSE B31)
        assert df["lgd_post_crm"][0] == pytest.approx(0.40)

    def test_foundation_with_collateral_uses_supervisory_lgdu(self):
        """Foundation election + collateral → LGD* with supervisory LGDU."""
        config = _b31_config(AIRBCollateralMethod.FOUNDATION)
        exposures = _make_exposures(
            approach=ApproachType.AIRB.value,
            lgd=0.12,
            lgd_unsecured=0.30,
            has_sufficient_collateral_data=True,
            ead_gross=1_000_000.0,
        )
        collateral = _make_collateral(
            collateral_type="real_estate",
            market_value=700_000.0,
        )
        result = _apply_collateral_unified(
            exposures,
            collateral,
            config,
            _empty_ead_totals(),
            _empty_cp_totals(),
            is_basel_3_1=True,
        )
        df = result.collect()
        # Foundation: LGD* = (0.20 × 500k + 0.40 × 500k) / 1M = 0.30
        assert df["lgd_post_crm"][0] == pytest.approx(0.30)

    def test_foundation_subordinated_uses_75pct(self):
        """Foundation election + subordinated → 75%."""
        config = _b31_config(AIRBCollateralMethod.FOUNDATION)
        exposures = _make_exposures(
            approach=ApproachType.AIRB.value,
            lgd=0.12,
            seniority="subordinated",
        )
        result = apply_firb_supervisory_lgd_no_collateral(
            exposures, is_basel_3_1=True, config=config
        )
        df = result.collect()
        assert df["lgd_post_crm"][0] == pytest.approx(0.75)

    def test_foundation_ignores_suff_data_flag(self):
        """Foundation election ignores has_sufficient_collateral_data."""
        config = _b31_config(AIRBCollateralMethod.FOUNDATION)
        exposures = _make_exposures(
            approach=ApproachType.AIRB.value,
            lgd=0.12,
            has_sufficient_collateral_data=False,  # Would trigger 169B normally
        )
        result = apply_firb_supervisory_lgd_no_collateral(
            exposures, is_basel_3_1=True, config=config
        )
        df = result.collect()
        # Foundation: supervisory 40%, not own LGD
        assert df["lgd_post_crm"][0] == pytest.approx(0.40)


# ===========================================================================
# 5. CRR backward compatibility
# ===========================================================================


class TestCRRBackwardCompat:
    """Under CRR, AIRB is free-form — no method constraint."""

    def test_crr_airb_keeps_own_lgd_no_collateral(self):
        """CRR + AIRB + no collateral → keep own modelled LGD."""
        config = _crr_config()
        exposures = _make_exposures(
            approach=ApproachType.AIRB.value,
            lgd=0.12,
            lgd_unsecured=0.30,
            has_sufficient_collateral_data=False,  # Irrelevant under CRR
        )
        result = apply_firb_supervisory_lgd_no_collateral(
            exposures, is_basel_3_1=False, config=config
        )
        df = result.collect()
        assert df["lgd_post_crm"][0] == pytest.approx(0.12)

    def test_crr_airb_keeps_own_lgd_with_collateral(self):
        """CRR + AIRB + collateral → keep own modelled LGD."""
        config = _crr_config()
        exposures = _make_exposures(
            approach=ApproachType.AIRB.value,
            lgd=0.12,
            lgd_unsecured=0.30,
            has_sufficient_collateral_data=False,
        )
        collateral = _make_collateral(collateral_type="real_estate", market_value=700_000.0)
        result = _apply_collateral_unified(
            exposures,
            collateral,
            config,
            _empty_ead_totals(),
            _empty_cp_totals(),
            is_basel_3_1=False,
        )
        df = result.collect()
        assert df["lgd_post_crm"][0] == pytest.approx(0.12)

    def test_crr_firb_unaffected(self):
        """CRR FIRB path unchanged by AIRB method additions."""
        config = _crr_config()
        exposures = _make_exposures(approach=ApproachType.FIRB.value, lgd=0.12)
        result = apply_firb_supervisory_lgd_no_collateral(
            exposures, is_basel_3_1=False, config=config
        )
        df = result.collect()
        assert df["lgd_post_crm"][0] == pytest.approx(0.45)  # CRR supervisory senior


# ===========================================================================
# 6. No-config backward compatibility
# ===========================================================================


class TestNoConfigBackwardCompat:
    """When config is not passed, default to original behavior."""

    def test_no_config_airb_keeps_own_lgd(self):
        """config=None → AIRB keeps own LGD (backward compat)."""
        exposures = _make_exposures(approach=ApproachType.AIRB.value, lgd=0.12)
        result = apply_firb_supervisory_lgd_no_collateral(exposures, is_basel_3_1=True, config=None)
        df = result.collect()
        assert df["lgd_post_crm"][0] == pytest.approx(0.12)

    def test_no_config_firb_uses_supervisory(self):
        """config=None → FIRB uses supervisory LGD."""
        exposures = _make_exposures(approach=ApproachType.FIRB.value, lgd=0.12)
        result = apply_firb_supervisory_lgd_no_collateral(exposures, is_basel_3_1=True, config=None)
        df = result.collect()
        assert df["lgd_post_crm"][0] == pytest.approx(0.40)  # B31 non-FSE


# ===========================================================================
# 7. Mixed batch tests
# ===========================================================================


class TestMixedBatch:
    """Multiple exposures with different approaches in one batch."""

    def test_mixed_approaches_no_collateral(self):
        """SA + FIRB + AIRB(sufficient) + AIRB(insufficient) in one batch."""
        config = _b31_config()
        data = {
            "exposure_reference": ["SA_001", "FIRB_001", "AIRB_SUFF", "AIRB_INSUFF"],
            "approach": [
                ApproachType.SA.value,
                ApproachType.FIRB.value,
                ApproachType.AIRB.value,
                ApproachType.AIRB.value,
            ],
            "lgd": [0.0, 0.12, 0.12, 0.12],
            "lgd_pre_crm": [0.0, 0.12, 0.12, 0.12],
            "lgd_post_crm": [0.0, 0.12, 0.12, 0.12],
            "lgd_unsecured": [None, None, 0.30, 0.30],
            "has_sufficient_collateral_data": [None, None, True, False],
            "ead_gross": [1e6, 1e6, 1e6, 1e6],
            "ead_pre_crm": [1e6, 1e6, 1e6, 1e6],
            "seniority": ["senior", "senior", "senior", "senior"],
            "counterparty_reference": ["CP1", "CP2", "CP3", "CP4"],
            "currency": ["GBP", "GBP", "GBP", "GBP"],
            "maturity_date": [date(2035, 1, 1)] * 4,
        }
        exposures = pl.LazyFrame(data)
        result = apply_firb_supervisory_lgd_no_collateral(
            exposures, is_basel_3_1=True, config=config
        )
        df = result.collect()

        # SA: keeps lgd_pre_crm = 0.0
        assert df.filter(pl.col("exposure_reference") == "SA_001")["lgd_post_crm"][
            0
        ] == pytest.approx(0.0)
        # FIRB: supervisory 40% (B31 non-FSE)
        assert df.filter(pl.col("exposure_reference") == "FIRB_001")["lgd_post_crm"][
            0
        ] == pytest.approx(0.40)
        # AIRB sufficient: keeps own LGD = 0.12
        assert df.filter(pl.col("exposure_reference") == "AIRB_SUFF")["lgd_post_crm"][
            0
        ] == pytest.approx(0.12)
        # AIRB insufficient: own lgd_unsecured = 0.30
        assert df.filter(pl.col("exposure_reference") == "AIRB_INSUFF")["lgd_post_crm"][
            0
        ] == pytest.approx(0.30)

    def test_mixed_approaches_with_collateral(self):
        """FIRB + AIRB(169B) + AIRB(sufficient) with shared collateral."""
        config = _b31_config()
        data = {
            "exposure_reference": ["FIRB_001", "AIRB_169B", "AIRB_FULL"],
            "approach": [
                ApproachType.FIRB.value,
                ApproachType.AIRB.value,
                ApproachType.AIRB.value,
            ],
            "lgd": [0.12, 0.12, 0.12],
            "lgd_pre_crm": [0.12, 0.12, 0.12],
            "lgd_post_crm": [0.12, 0.12, 0.12],
            "lgd_unsecured": [None, 0.25, 0.25],
            "has_sufficient_collateral_data": [None, False, True],
            "ead_gross": [1e6, 1e6, 1e6],
            "ead_pre_crm": [1e6, 1e6, 1e6],
            "seniority": ["senior", "senior", "senior"],
            "counterparty_reference": ["CP1", "CP2", "CP3"],
            "currency": ["GBP", "GBP", "GBP"],
            "maturity_date": [date(2035, 1, 1)] * 3,
        }
        exposures = pl.LazyFrame(data)

        # Collateral: one per exposure, same type and value
        collateral = pl.LazyFrame(
            {
                "collateral_reference": ["C1", "C2", "C3"],
                "beneficiary_reference": ["FIRB_001", "AIRB_169B", "AIRB_FULL"],
                "beneficiary_type": ["exposure", "exposure", "exposure"],
                "collateral_type": ["real_estate", "real_estate", "real_estate"],
                "market_value": [700_000.0, 700_000.0, 700_000.0],
                "value_after_haircut": [700_000.0, 700_000.0, 700_000.0],
                "value_after_maturity_adj": [700_000.0, 700_000.0, 700_000.0],
                "is_eligible_financial_collateral": [True, True, True],
            }
        )

        result = _apply_collateral_unified(
            exposures,
            collateral,
            config,
            _empty_ead_totals(),
            _empty_cp_totals(),
            is_basel_3_1=True,
        ).collect()

        # ES = 700k/1.4 = 500k, EU = 500k
        # FIRB: (0.20×500k + 0.40×500k) / 1M = 0.30
        firb = result.filter(pl.col("exposure_reference") == "FIRB_001")
        assert firb["lgd_post_crm"][0] == pytest.approx(0.30)

        # AIRB 169B: (0.20×500k + 0.25×500k) / 1M = 0.225
        airb_169b = result.filter(pl.col("exposure_reference") == "AIRB_169B")
        assert airb_169b["lgd_post_crm"][0] == pytest.approx(0.225)

        # AIRB full modelling: keeps own LGD = 0.12
        airb_full = result.filter(pl.col("exposure_reference") == "AIRB_FULL")
        assert airb_full["lgd_post_crm"][0] == pytest.approx(0.12)


# ===========================================================================
# 8. Capital impact tests
# ===========================================================================


class TestCapitalImpact:
    """Demonstrate capital impact of Art. 169B vs Foundation vs full modelling."""

    def test_169b_lower_capital_than_foundation_with_lower_lgdu(self):
        """When own LGDU < supervisory, Art. 169B produces lower capital."""
        config_169b = _b31_config(AIRBCollateralMethod.LGD_MODELLING)
        config_fcm = _b31_config(AIRBCollateralMethod.FOUNDATION)

        exposures_169b = _make_exposures(
            approach=ApproachType.AIRB.value,
            lgd=0.12,
            lgd_unsecured=0.25,  # Below supervisory 40%
            has_sufficient_collateral_data=False,
        )
        exposures_fcm = _make_exposures(
            approach=ApproachType.AIRB.value,
            lgd=0.12,
            lgd_unsecured=0.25,
        )
        collateral = _make_collateral(collateral_type="real_estate", market_value=700_000.0)

        result_169b = _apply_collateral_unified(
            exposures_169b,
            collateral,
            config_169b,
            _empty_ead_totals(),
            _empty_cp_totals(),
            is_basel_3_1=True,
        ).collect()

        result_fcm = _apply_collateral_unified(
            exposures_fcm,
            collateral,
            config_fcm,
            _empty_ead_totals(),
            _empty_cp_totals(),
            is_basel_3_1=True,
        ).collect()

        # 169B: (0.20×500k + 0.25×500k)/1M = 0.225
        # FCM:  (0.20×500k + 0.40×500k)/1M = 0.30
        assert result_169b["lgd_post_crm"][0] < result_fcm["lgd_post_crm"][0]

    def test_full_modelling_can_be_lower_than_169b(self):
        """Full modelling (own LGD=12%) produces lower LGD than 169B (25%)."""
        config = _b31_config()

        exp_full = _make_exposures(
            approach=ApproachType.AIRB.value,
            lgd=0.12,
            lgd_unsecured=0.30,
            has_sufficient_collateral_data=True,
        )
        exp_169b = _make_exposures(
            approach=ApproachType.AIRB.value,
            lgd=0.12,
            lgd_unsecured=0.30,
            has_sufficient_collateral_data=False,
        )

        result_full = apply_firb_supervisory_lgd_no_collateral(
            exp_full, is_basel_3_1=True, config=config
        ).collect()
        result_169b = apply_firb_supervisory_lgd_no_collateral(
            exp_169b, is_basel_3_1=True, config=config
        ).collect()

        # Full modelling: own LGD = 0.12
        # 169B: own LGDU = 0.30
        assert result_full["lgd_post_crm"][0] == pytest.approx(0.12)
        assert result_169b["lgd_post_crm"][0] == pytest.approx(0.30)
        assert result_full["lgd_post_crm"][0] < result_169b["lgd_post_crm"][0]


# ===========================================================================
# 9. Financial collateral with Art. 169B
# ===========================================================================


class TestArt169BFinancialCollateral:
    """Art. 169B with financial collateral (LGDS = 0%)."""

    def test_169b_cash_collateral_lgds_zero(self):
        """Cash collateral: LGDS=0% reduces LGD significantly."""
        config = _b31_config()
        exposures = _make_exposures(
            approach=ApproachType.AIRB.value,
            lgd=0.12,
            lgd_unsecured=0.30,
            has_sufficient_collateral_data=False,
            ead_gross=1_000_000.0,
        )
        collateral = _make_collateral(
            collateral_type="cash",
            market_value=500_000.0,
        )
        result = _apply_collateral_unified(
            exposures,
            collateral,
            config,
            _empty_ead_totals(),
            _empty_cp_totals(),
            is_basel_3_1=True,
        ).collect()

        # Financial: OC=1.0, ES=500k, EU=500k
        # LGD* = (0.0×500k + 0.30×500k) / 1M = 0.15
        assert result["lgd_post_crm"][0] == pytest.approx(0.15)
