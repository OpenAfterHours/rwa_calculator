"""Unit tests for Basel 3.1 Art. 147A approach restrictions.

Tests cover:
- IRBPermissions.full_irb_b31() factory method (permission-level restrictions)
- Classifier-level B31 restrictions:
  - Sovereign/quasi-sovereign → SA only
  - Institution → F-IRB only
  - IPRE/HVCRE → Slotting only
  - FSE corporate → F-IRB only (no A-IRB)
  - Large corporate (>GBP 440m) → F-IRB only (no A-IRB)
- CalculationConfig.basel_3_1() uses full_irb_b31() permissions

References:
- PRA PS1/26 Art. 147A
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.bundles import (
    ClassifiedExposuresBundle,
    CounterpartyLookup,
    ResolvedHierarchyBundle,
)
from rwa_calc.contracts.config import CalculationConfig, IRBPermissions
from rwa_calc.domain.enums import ApproachType, ExposureClass, PermissionMode
from rwa_calc.engine.classifier import ExposureClassifier


# =============================================================================
# Helpers
# =============================================================================


def _make_counterparty(
    ref: str = "CP001",
    entity_type: str = "corporate",
    annual_revenue: float = 100_000_000.0,
    total_assets: float = 500_000_000.0,
    apply_fi_scalar: bool = False,
    is_financial_sector_entity: bool | None = None,
    country_code: str = "GB",
) -> pl.LazyFrame:
    """Create a single-row counterparty LazyFrame."""
    data: dict = {
        "counterparty_reference": [ref],
        "counterparty_name": [f"Test {ref}"],
        "entity_type": [entity_type],
        "country_code": [country_code],
        "annual_revenue": [annual_revenue],
        "total_assets": [total_assets],
        "default_status": [False],
        "sector_code": ["MANU"],
        "apply_fi_scalar": [apply_fi_scalar],
        "is_managed_as_retail": [False],
    }
    if is_financial_sector_entity is not None:
        data["is_financial_sector_entity"] = [is_financial_sector_entity]
    return pl.DataFrame(data).lazy()


def _make_exposure(
    ref: str = "EXP001",
    cp_ref: str = "CP001",
    lgd: float | None = 0.45,
    internal_pd: float | None = 0.005,
) -> pl.LazyFrame:
    """Create a single-row exposure LazyFrame with IRB-ready fields."""
    return pl.DataFrame(
        {
            "exposure_reference": [ref],
            "exposure_type": ["loan"],
            "product_type": ["TERM_LOAN"],
            "book_code": ["CORP"],
            "counterparty_reference": [cp_ref],
            "value_date": [date(2023, 1, 1)],
            "maturity_date": [date(2028, 1, 1)],
            "currency": ["GBP"],
            "drawn_amount": [5_000_000.0],
            "undrawn_amount": [0.0],
            "nominal_amount": [0.0],
            "lgd": [lgd],
            "seniority": ["senior"],
            "exposure_has_parent": [False],
            "root_facility_reference": [None],
            "facility_hierarchy_depth": [1],
            "counterparty_has_parent": [False],
            "parent_counterparty_reference": [None],
            "ultimate_parent_reference": [None],
            "counterparty_hierarchy_depth": [1],
            "lending_group_reference": [None],
            "lending_group_total_exposure": [0.0],
            "internal_pd": [internal_pd],
        }
    ).lazy()


def _make_bundle(
    exposures: pl.LazyFrame,
    counterparties: pl.LazyFrame,
    specialised_lending: pl.LazyFrame | None = None,
) -> ResolvedHierarchyBundle:
    """Create a ResolvedHierarchyBundle for testing."""
    enriched_cp = counterparties.with_columns(
        [
            pl.lit(False).alias("counterparty_has_parent"),
            pl.lit(None).cast(pl.String).alias("parent_counterparty_reference"),
            pl.lit(None).cast(pl.String).alias("ultimate_parent_reference"),
            pl.lit(0).cast(pl.Int32).alias("counterparty_hierarchy_depth"),
            pl.lit(None).cast(pl.Int8).alias("cqs"),
        ]
    )

    exp_schema = exposures.collect_schema()
    if "residential_collateral_value" not in exp_schema.names():
        exposures = exposures.with_columns(
            pl.lit(0.0).alias("residential_collateral_value"),
        )
    if "exposure_for_retail_threshold" not in exp_schema.names():
        exposures = exposures.with_columns(
            (
                pl.col("drawn_amount")
                + pl.col("nominal_amount")
                - pl.col("residential_collateral_value")
            ).alias("exposure_for_retail_threshold"),
        )
    if "lending_group_adjusted_exposure" not in exp_schema.names():
        exposures = exposures.with_columns(
            pl.col("lending_group_total_exposure").alias("lending_group_adjusted_exposure"),
        )

    return ResolvedHierarchyBundle(
        exposures=exposures,
        counterparty_lookup=CounterpartyLookup(
            counterparties=enriched_cp,
            parent_mappings=pl.LazyFrame(
                schema={
                    "child_counterparty_reference": pl.String,
                    "parent_counterparty_reference": pl.String,
                }
            ),
            ultimate_parent_mappings=pl.LazyFrame(
                schema={
                    "counterparty_reference": pl.String,
                    "ultimate_parent_reference": pl.String,
                    "hierarchy_depth": pl.Int32,
                }
            ),
            rating_inheritance=pl.LazyFrame(
                schema={
                    "counterparty_reference": pl.String,
                    "internal_pd": pl.Float64,
                    "internal_model_id": pl.String,
                    "external_cqs": pl.Int8,
                    "cqs": pl.Int8,
                    "pd": pl.Float64,
                }
            ),
        ),
        collateral=pl.LazyFrame(),
        guarantees=pl.LazyFrame(),
        provisions=pl.LazyFrame(),
        specialised_lending=specialised_lending,
        model_permissions=None,
        lending_group_totals=pl.LazyFrame(
            schema={
                "lending_group_reference": pl.String,
                "total_drawn": pl.Float64,
                "total_nominal": pl.Float64,
                "total_exposure": pl.Float64,
                "adjusted_exposure": pl.Float64,
                "total_residential_coverage": pl.Float64,
                "exposure_count": pl.UInt32,
            }
        ),
    )


def _classify(
    entity_type: str = "corporate",
    annual_revenue: float = 100_000_000.0,
    is_financial_sector_entity: bool | None = None,
    lgd: float | None = 0.45,
    internal_pd: float | None = 0.005,
    specialised_lending: pl.LazyFrame | None = None,
    framework: str = "b31",
    country_code: str = "GB",
) -> pl.DataFrame:
    """Classify a single exposure and return collected results."""
    cp = _make_counterparty(
        entity_type=entity_type,
        annual_revenue=annual_revenue,
        is_financial_sector_entity=is_financial_sector_entity,
        country_code=country_code,
    )
    exp = _make_exposure(lgd=lgd, internal_pd=internal_pd)
    bundle = _make_bundle(exp, cp, specialised_lending=specialised_lending)

    if framework == "b31":
        config = CalculationConfig.basel_3_1(
            reporting_date=date(2027, 6, 30),
            permission_mode=PermissionMode.IRB,
        )
    else:
        config = CalculationConfig.crr(
            reporting_date=date(2024, 12, 31),
            permission_mode=PermissionMode.IRB,
        )

    classifier = ExposureClassifier()
    result = classifier.classify(bundle, config)
    return result.all_exposures.collect()


def _make_sl_table(sl_type: str, is_hvcre: bool = False) -> pl.LazyFrame:
    """Create a specialised lending table for the counterparty."""
    return pl.DataFrame(
        {
            "counterparty_reference": ["CP001"],
            "sl_type": [sl_type],
            "slotting_category": ["good"],
            "is_hvcre": [is_hvcre],
        }
    ).lazy()


# =============================================================================
# IRBPermissions.full_irb_b31() Tests
# =============================================================================


class TestFullIRBB31Permissions:
    """Tests for IRBPermissions.full_irb_b31() factory method."""

    def test_sovereign_sa_only(self) -> None:
        """Art. 147A(1)(a): Sovereigns must use SA only under B31."""
        perms = IRBPermissions.full_irb_b31()
        assert perms.get_permitted_approaches(ExposureClass.CENTRAL_GOVT_CENTRAL_BANK) == {
            ApproachType.SA
        }

    def test_pse_sa_only(self) -> None:
        """Art. 147A(1)(a)/Art. 147(3): PSE quasi-sovereigns must use SA only."""
        perms = IRBPermissions.full_irb_b31()
        assert perms.get_permitted_approaches(ExposureClass.PSE) == {ApproachType.SA}

    def test_mdb_sa_only(self) -> None:
        """Art. 147A(1)(a)/Art. 147(3): MDB quasi-sovereigns must use SA only."""
        perms = IRBPermissions.full_irb_b31()
        assert perms.get_permitted_approaches(ExposureClass.MDB) == {ApproachType.SA}

    def test_rgla_sa_only(self) -> None:
        """Art. 147A(1)(a)/Art. 147(3): RGLA quasi-sovereigns must use SA only."""
        perms = IRBPermissions.full_irb_b31()
        assert perms.get_permitted_approaches(ExposureClass.RGLA) == {ApproachType.SA}

    def test_institution_firb_only(self) -> None:
        """Art. 147A(1)(b): Institutions must use F-IRB only (no A-IRB)."""
        perms = IRBPermissions.full_irb_b31()
        permitted = perms.get_permitted_approaches(ExposureClass.INSTITUTION)
        assert ApproachType.SA in permitted
        assert ApproachType.FIRB in permitted
        assert ApproachType.AIRB not in permitted

    def test_corporate_allows_airb(self) -> None:
        """Art. 147A(1)(f): General corporates may use A-IRB with permission."""
        perms = IRBPermissions.full_irb_b31()
        permitted = perms.get_permitted_approaches(ExposureClass.CORPORATE)
        assert ApproachType.AIRB in permitted
        assert ApproachType.FIRB in permitted

    def test_corporate_sme_allows_airb(self) -> None:
        """Corporate SMEs may use A-IRB with permission."""
        perms = IRBPermissions.full_irb_b31()
        permitted = perms.get_permitted_approaches(ExposureClass.CORPORATE_SME)
        assert ApproachType.AIRB in permitted
        assert ApproachType.FIRB in permitted

    def test_retail_unchanged(self) -> None:
        """Art. 147A(3): Retail classes retain A-IRB option."""
        perms = IRBPermissions.full_irb_b31()
        for ec in [ExposureClass.RETAIL_MORTGAGE, ExposureClass.RETAIL_QRRE,
                    ExposureClass.RETAIL_OTHER]:
            permitted = perms.get_permitted_approaches(ec)
            assert ApproachType.SA in permitted
            assert ApproachType.AIRB in permitted
            assert ApproachType.FIRB not in permitted

    def test_specialised_lending_all_approaches(self) -> None:
        """SL retains all approaches (IPRE/HVCRE slotting enforced at classifier)."""
        perms = IRBPermissions.full_irb_b31()
        permitted = perms.get_permitted_approaches(ExposureClass.SPECIALISED_LENDING)
        assert ApproachType.SA in permitted
        assert ApproachType.SLOTTING in permitted
        assert ApproachType.FIRB in permitted
        assert ApproachType.AIRB in permitted

    def test_equity_sa_only(self) -> None:
        """Art. 147A: Equity must use SA only under B31."""
        perms = IRBPermissions.full_irb_b31()
        assert perms.get_permitted_approaches(ExposureClass.EQUITY) == {ApproachType.SA}

    def test_covered_bond_sa_only(self) -> None:
        """Covered bonds remain SA only under B31."""
        perms = IRBPermissions.full_irb_b31()
        assert perms.get_permitted_approaches(ExposureClass.COVERED_BOND) == {ApproachType.SA}


# =============================================================================
# CalculationConfig Integration Tests
# =============================================================================


class TestB31ConfigUsesB31Permissions:
    """Test that CalculationConfig.basel_3_1() uses full_irb_b31() permissions."""

    def test_b31_irb_config_uses_b31_permissions(self) -> None:
        """B31 IRB config should use full_irb_b31(), not full_irb()."""
        config = CalculationConfig.basel_3_1(
            reporting_date=date(2027, 6, 30),
            permission_mode=PermissionMode.IRB,
        )
        # Institution should be FIRB only (B31), not AIRB+FIRB (CRR)
        assert not config.irb_permissions.is_permitted(
            ExposureClass.INSTITUTION, ApproachType.AIRB
        )
        assert config.irb_permissions.is_permitted(
            ExposureClass.INSTITUTION, ApproachType.FIRB
        )

    def test_crr_irb_config_uses_full_irb(self) -> None:
        """CRR IRB config should use full_irb() with AIRB for institutions."""
        config = CalculationConfig.crr(
            reporting_date=date(2024, 12, 31),
            permission_mode=PermissionMode.IRB,
        )
        # Institution should have AIRB under CRR
        assert config.irb_permissions.is_permitted(
            ExposureClass.INSTITUTION, ApproachType.AIRB
        )

    def test_b31_sa_config_uses_sa_only(self) -> None:
        """B31 SA-only config should use sa_only() — no IRB."""
        config = CalculationConfig.basel_3_1(
            reporting_date=date(2027, 6, 30),
            permission_mode=PermissionMode.STANDARDISED,
        )
        # No IRB for any class
        assert not config.irb_permissions.is_permitted(
            ExposureClass.CORPORATE, ApproachType.FIRB
        )

    def test_b31_sovereign_forced_sa(self) -> None:
        """B31 IRB config blocks IRB for sovereigns."""
        config = CalculationConfig.basel_3_1(
            reporting_date=date(2027, 6, 30),
            permission_mode=PermissionMode.IRB,
        )
        assert not config.irb_permissions.is_permitted(
            ExposureClass.CENTRAL_GOVT_CENTRAL_BANK, ApproachType.FIRB
        )
        assert not config.irb_permissions.is_permitted(
            ExposureClass.CENTRAL_GOVT_CENTRAL_BANK, ApproachType.AIRB
        )


# =============================================================================
# Classifier-Level B31 Restriction Tests
# =============================================================================


class TestB31SovereignSAOnly:
    """Art. 147A(1)(a): Sovereign exposures must use SA only under B31."""

    def test_sovereign_gets_sa_under_b31(self) -> None:
        """Sovereign with internal PD still forced to SA under B31."""
        df = _classify(entity_type="sovereign")
        assert df["approach"][0] == ApproachType.SA.value

    def test_sovereign_gets_irb_under_crr(self) -> None:
        """Sovereign with internal PD gets AIRB under CRR."""
        df = _classify(entity_type="sovereign", framework="crr")
        assert df["approach"][0] == ApproachType.AIRB.value


class TestB31QuasiSovereignSAOnly:
    """Art. 147A(1)(a)/Art. 147(3): Quasi-sovereigns forced to SA."""

    def test_pse_gets_sa_under_b31(self) -> None:
        """PSE with internal PD still forced to SA under B31."""
        df = _classify(entity_type="pse_institution")
        assert df["approach"][0] == ApproachType.SA.value

    def test_mdb_gets_sa_under_b31(self) -> None:
        """MDB with internal PD still forced to SA under B31."""
        df = _classify(entity_type="mdb")
        assert df["approach"][0] == ApproachType.SA.value

    def test_rgla_gets_sa_under_b31(self) -> None:
        """RGLA with internal PD still forced to SA under B31."""
        df = _classify(entity_type="rgla_institution")
        assert df["approach"][0] == ApproachType.SA.value


class TestB31InstitutionFIRBOnly:
    """Art. 147A(1)(b): Institution exposures must use F-IRB only (no A-IRB)."""

    def test_institution_gets_firb_under_b31(self) -> None:
        """Institution with internal PD + LGD gets FIRB (not AIRB) under B31."""
        df = _classify(entity_type="institution")
        assert df["approach"][0] == ApproachType.FIRB.value

    def test_institution_gets_airb_under_crr(self) -> None:
        """Institution with internal PD + LGD gets AIRB under CRR."""
        df = _classify(entity_type="institution", framework="crr")
        assert df["approach"][0] == ApproachType.AIRB.value

    def test_bank_gets_firb_under_b31(self) -> None:
        """Bank entity_type (maps to institution) gets FIRB under B31."""
        df = _classify(entity_type="bank")
        assert df["approach"][0] == ApproachType.FIRB.value

    def test_institution_lgd_cleared_under_b31(self) -> None:
        """Institution FIRB should have LGD cleared (uses supervisory LGD)."""
        df = _classify(entity_type="institution")
        assert df["lgd"][0] is None


class TestB31IPREHVCRESlottingOnly:
    """Art. 147A(1)(c): IPRE/HVCRE must use slotting only under B31."""

    def test_ipre_forced_to_slotting_under_b31(self) -> None:
        """IPRE specialised lending forced to slotting under B31."""
        sl_table = _make_sl_table("ipre")
        df = _classify(
            entity_type="specialised_lending",
            specialised_lending=sl_table,
        )
        assert df["approach"][0] == ApproachType.SLOTTING.value

    def test_hvcre_forced_to_slotting_under_b31(self) -> None:
        """HVCRE specialised lending forced to slotting under B31."""
        sl_table = _make_sl_table("hvcre", is_hvcre=True)
        df = _classify(
            entity_type="specialised_lending",
            specialised_lending=sl_table,
        )
        assert df["approach"][0] == ApproachType.SLOTTING.value

    def test_project_finance_can_use_airb_under_b31(self) -> None:
        """PF specialised lending can still use AIRB under B31."""
        sl_table = _make_sl_table("project_finance")
        df = _classify(
            entity_type="specialised_lending",
            specialised_lending=sl_table,
        )
        # PF with internal PD + LGD should get AIRB (not slotting-forced)
        assert df["approach"][0] == ApproachType.AIRB.value

    def test_object_finance_can_use_airb_under_b31(self) -> None:
        """OF specialised lending can still use AIRB under B31."""
        sl_table = _make_sl_table("object_finance")
        df = _classify(
            entity_type="specialised_lending",
            specialised_lending=sl_table,
        )
        assert df["approach"][0] == ApproachType.AIRB.value

    def test_ipre_gets_airb_under_crr(self) -> None:
        """IPRE gets AIRB under CRR (no slotting-only restriction)."""
        sl_table = _make_sl_table("ipre")
        df = _classify(
            entity_type="specialised_lending",
            specialised_lending=sl_table,
            framework="crr",
        )
        assert df["approach"][0] == ApproachType.AIRB.value


class TestB31FSEFIRBOnly:
    """Art. 147A(1)(e): FSE corporates must use F-IRB only (no A-IRB)."""

    def test_fse_corporate_gets_firb_under_b31(self) -> None:
        """FSE corporate with internal PD + LGD gets FIRB (not AIRB) under B31."""
        df = _classify(
            entity_type="corporate",
            is_financial_sector_entity=True,
        )
        assert df["approach"][0] == ApproachType.FIRB.value

    def test_fse_corporate_gets_airb_under_crr(self) -> None:
        """FSE corporate gets AIRB under CRR (no FSE restriction)."""
        df = _classify(
            entity_type="corporate",
            is_financial_sector_entity=True,
            framework="crr",
        )
        assert df["approach"][0] == ApproachType.AIRB.value

    def test_non_fse_corporate_gets_airb_under_b31(self) -> None:
        """Non-FSE corporate with internal PD + LGD gets AIRB under B31."""
        df = _classify(
            entity_type="corporate",
            is_financial_sector_entity=False,
        )
        assert df["approach"][0] == ApproachType.AIRB.value

    def test_fse_corporate_lgd_cleared_under_b31(self) -> None:
        """FSE corporate FIRB should have LGD cleared (supervisory LGD)."""
        df = _classify(
            entity_type="corporate",
            is_financial_sector_entity=True,
        )
        assert df["lgd"][0] is None

    def test_null_fse_treated_as_non_fse(self) -> None:
        """Null is_financial_sector_entity defaults to non-FSE (AIRB permitted)."""
        df = _classify(
            entity_type="corporate",
            is_financial_sector_entity=None,
        )
        assert df["approach"][0] == ApproachType.AIRB.value


class TestB31LargeCorporateFIRBOnly:
    """Art. 147A(1)(d): Large corporates (>GBP 440m) must use F-IRB only."""

    def test_large_corporate_gets_firb_under_b31(self) -> None:
        """Corporate with revenue > GBP 440m gets FIRB under B31."""
        df = _classify(
            entity_type="corporate",
            annual_revenue=500_000_000.0,  # GBP 500m > 440m threshold
        )
        assert df["approach"][0] == ApproachType.FIRB.value

    def test_large_corporate_gets_airb_under_crr(self) -> None:
        """Large corporate gets AIRB under CRR (no revenue restriction)."""
        df = _classify(
            entity_type="corporate",
            annual_revenue=500_000_000.0,
            framework="crr",
        )
        assert df["approach"][0] == ApproachType.AIRB.value

    def test_below_threshold_gets_airb_under_b31(self) -> None:
        """Corporate at GBP 440m (at threshold) gets AIRB under B31."""
        df = _classify(
            entity_type="corporate",
            annual_revenue=440_000_000.0,  # Exactly at threshold — not above
        )
        assert df["approach"][0] == ApproachType.AIRB.value

    def test_just_above_threshold_gets_firb_under_b31(self) -> None:
        """Corporate at GBP 440m + 1 gets FIRB under B31."""
        df = _classify(
            entity_type="corporate",
            annual_revenue=440_000_001.0,
        )
        assert df["approach"][0] == ApproachType.FIRB.value

    def test_large_corporate_lgd_cleared(self) -> None:
        """Large corporate FIRB should have LGD cleared."""
        df = _classify(
            entity_type="corporate",
            annual_revenue=500_000_000.0,
        )
        assert df["lgd"][0] is None

    def test_sme_corporate_gets_airb(self) -> None:
        """SME corporate (below threshold) gets AIRB under B31."""
        df = _classify(
            entity_type="corporate",
            annual_revenue=30_000_000.0,
        )
        assert df["approach"][0] == ApproachType.AIRB.value


class TestB31NoIRBDataFallback:
    """Test that exposures without IRB data still fall to SA gracefully."""

    def test_no_internal_pd_gets_sa(self) -> None:
        """Corporate without internal PD gets SA even under B31 IRB config."""
        df = _classify(
            entity_type="corporate",
            internal_pd=None,
        )
        assert df["approach"][0] == ApproachType.SA.value

    def test_fse_no_internal_pd_gets_sa(self) -> None:
        """FSE without internal PD gets SA (not FIRB)."""
        df = _classify(
            entity_type="corporate",
            is_financial_sector_entity=True,
            internal_pd=None,
        )
        assert df["approach"][0] == ApproachType.SA.value


class TestB31WithoutFSEColumn:
    """Test B31 restrictions work when is_financial_sector_entity column is absent."""

    def test_corporate_gets_airb_without_fse_column(self) -> None:
        """Without FSE column, corporate defaults to non-FSE treatment (AIRB ok)."""
        # Don't pass is_financial_sector_entity at all
        df = _classify(entity_type="corporate")
        assert df["approach"][0] == ApproachType.AIRB.value

    def test_large_corporate_still_restricted_without_fse_column(self) -> None:
        """Large corporate revenue check works even without FSE column."""
        df = _classify(
            entity_type="corporate",
            annual_revenue=500_000_000.0,
        )
        assert df["approach"][0] == ApproachType.FIRB.value
