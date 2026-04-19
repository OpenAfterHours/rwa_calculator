"""
Unit tests for the real estate loan-splitter (CRR Art. 125/126, B3.1 Art. 124F/H).

Pipeline position under test:
    CRMProcessor -> RealEstateSplitter -> SA / IRB / Slotting Calculators

These tests construct the post-CRM bundle directly (bypassing the
classifier and CRM) so the splitter's row-partition logic can be
verified in isolation. End-to-end behaviour is exercised by the
integration tests in ``tests/integration/test_re_split_pipeline.py``.

References:
- CRR Art. 125: RRE 35% on portion up to 80% LTV.
- CRR Art. 126: CRE 50% on portion up to 50% LTV when rental coverage met.
- PRA PS1/26 Art. 124F: B3.1 RRE loan-splitting (cap 55% less prior charges).
- PRA PS1/26 Art. 124H(1)-(2): B3.1 CRE loan-splitting NP/SME.
- PRA PS1/26 Art. 124H(3): B3.1 CRE max(60%, min(cp_rw, Art. 124I)).
"""

from __future__ import annotations

from datetime import date
from typing import Any

import polars as pl
import pytest

from rwa_calc.contracts.bundles import CRMAdjustedBundle
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.engine.re_splitter import RealEstateSplitter

_REPORTING_DATE = date(2026, 12, 31)


def _build_bundle(rows: list[dict[str, Any]]) -> CRMAdjustedBundle:
    """Build a minimal CRMAdjustedBundle from a list of row dicts.

    All required + optional splitter columns are defaulted; per-row
    overrides simply update the dict.
    """
    base: dict[str, Any] = {
        "exposure_reference": "EXP1",
        "counterparty_reference": "CP1",
        "exposure_class": "CORPORATE",
        "ead_final": 100.0,
        "provision_allocated": 0.0,
        # Classifier-emitted candidate columns
        "re_split_target_class": None,
        "re_split_mode": None,
        "re_split_property_type": None,
        "re_split_property_value": 0.0,
        "re_split_cre_rental_coverage_met": False,
        # Existing real-estate columns referenced by the splitter
        "ltv": None,
        "property_type": None,
        "has_income_cover": False,
        "prior_charge_ltv": 0.0,
        "property_collateral_value": 0.0,
        "residential_collateral_value": 0.0,
        # Counterparty-type flags propagated from the classifier
        "cp_is_natural_person": False,
        "is_sme": False,
    }
    expanded = []
    for r in rows:
        full = dict(base)
        full.update(r)
        expanded.append(full)
    lf = pl.DataFrame(expanded).lazy()
    return CRMAdjustedBundle(
        exposures=lf,
        sa_exposures=lf,
        irb_exposures=pl.LazyFrame(),
    )


def _crr() -> CalculationConfig:
    return CalculationConfig.crr(reporting_date=_REPORTING_DATE)


def _b31() -> CalculationConfig:
    return CalculationConfig.basel_3_1(reporting_date=_REPORTING_DATE)


def _by_role(df: pl.DataFrame, role: str) -> dict[str, Any]:
    sub = df.filter(pl.col("re_split_role") == role)
    assert sub.height == 1, f"expected exactly one {role} row, got {sub.height}"
    return sub.to_dicts()[0]


# ---------------------------------------------------------------------------
# CRR scenarios
# ---------------------------------------------------------------------------


class TestCRRResidentialSplit:
    """CRR Art. 125 — RRE loan-split at 80% LTV."""

    def test_corporate_full_ltv_splits_80_20(self) -> None:
        """EAD 100, property 100, LTV 100% → secured 80, residual 20."""
        bundle = _build_bundle(
            [
                {
                    "exposure_reference": "RRE1",
                    "exposure_class": "CORPORATE",
                    "ead_final": 100.0,
                    "re_split_target_class": "RESIDENTIAL_MORTGAGE",
                    "re_split_mode": "split",
                    "re_split_property_type": "residential",
                    "re_split_property_value": 100.0,
                    "property_collateral_value": 100.0,
                }
            ]
        )

        result = RealEstateSplitter().split(bundle, _crr())
        df = result.exposures.collect()

        secured = _by_role(df, "secured")
        residual = _by_role(df, "residual")

        assert secured["ead_final"] == pytest.approx(80.0)
        assert secured["exposure_class"] == "RESIDENTIAL_MORTGAGE"
        assert secured["ltv"] == pytest.approx(0.80)
        assert residual["ead_final"] == pytest.approx(20.0)
        assert residual["exposure_class"] == "CORPORATE"
        assert secured["split_parent_id"] == "RRE1"
        assert residual["split_parent_id"] == "RRE1"

    def test_below_cap_secures_full_ead(self) -> None:
        """EAD 60, property 100 → secured cap 80; secured = 60, residual = 0."""
        bundle = _build_bundle(
            [
                {
                    "exposure_reference": "RRE2",
                    "ead_final": 60.0,
                    "re_split_target_class": "RESIDENTIAL_MORTGAGE",
                    "re_split_mode": "split",
                    "re_split_property_type": "residential",
                    "re_split_property_value": 100.0,
                    "property_collateral_value": 100.0,
                }
            ]
        )

        df = RealEstateSplitter().split(bundle, _crr()).exposures.collect()

        secured = _by_role(df, "secured")
        residual = _by_role(df, "residual")
        assert secured["ead_final"] == pytest.approx(60.0)
        assert residual["ead_final"] == pytest.approx(0.0)


class TestCRRCommercialSplit:
    """CRR Art. 126 — CRE 50% on LTV ≤ 50% with rental coverage."""

    def test_rental_met_split_50_50(self) -> None:
        """EAD 100, property 200 → secured cap 100; secured = 100, residual = 0."""
        bundle = _build_bundle(
            [
                {
                    "exposure_reference": "CRE1",
                    "exposure_class": "CORPORATE",
                    "ead_final": 100.0,
                    "re_split_target_class": "COMMERCIAL_MORTGAGE",
                    "re_split_mode": "split",
                    "re_split_property_type": "commercial",
                    "re_split_property_value": 200.0,
                    "re_split_cre_rental_coverage_met": True,
                    "property_collateral_value": 200.0,
                }
            ]
        )

        df = RealEstateSplitter().split(bundle, _crr()).exposures.collect()
        secured = _by_role(df, "secured")
        residual = _by_role(df, "residual")
        assert secured["ead_final"] == pytest.approx(100.0)
        assert secured["has_income_cover"] is True  # CRR Art. 126(2)(d)
        assert residual["ead_final"] == pytest.approx(0.0)

    def test_rental_not_met_no_split(self) -> None:
        """No split — exposure stays in original CORPORATE class."""
        bundle = _build_bundle(
            [
                {
                    "exposure_reference": "CRE2",
                    "exposure_class": "CORPORATE",
                    "ead_final": 100.0,
                    # Classifier emits re_split_mode=None when CRR rental cov fails
                    "re_split_target_class": "COMMERCIAL_MORTGAGE",
                    "re_split_mode": None,
                    "re_split_property_type": "commercial",
                    "re_split_property_value": 200.0,
                    "re_split_cre_rental_coverage_met": False,
                    "property_collateral_value": 200.0,
                }
            ]
        )

        result = RealEstateSplitter().split(bundle, _crr())
        df = result.exposures.collect()
        assert df.height == 1
        row = df.to_dicts()[0]
        assert row["exposure_class"] == "CORPORATE"
        assert row["ead_final"] == pytest.approx(100.0)
        # The splitter emits an RE004 informational warning for this case.
        assert any(e.code == "RE004" for e in result.crm_errors)


# ---------------------------------------------------------------------------
# Basel 3.1 scenarios
# ---------------------------------------------------------------------------


class TestB31ResidentialSplit:
    """B3.1 Art. 124F — RRE loan-split with cap = 55% × property value."""

    def test_natural_person_full_secured(self) -> None:
        """EAD 100, property 200 → cap 110; secured = 100, residual = 0."""
        bundle = _build_bundle(
            [
                {
                    "exposure_reference": "B31RRE1",
                    "exposure_class": "RETAIL_OTHER",
                    "ead_final": 100.0,
                    "re_split_target_class": "RESIDENTIAL_MORTGAGE",
                    "re_split_mode": "split",
                    "re_split_property_type": "residential",
                    "re_split_property_value": 200.0,
                    "property_collateral_value": 200.0,
                    "cp_is_natural_person": True,
                }
            ]
        )

        df = RealEstateSplitter().split(bundle, _b31()).exposures.collect()
        secured = _by_role(df, "secured")
        residual = _by_role(df, "residual")
        assert secured["ead_final"] == pytest.approx(100.0)
        assert residual["ead_final"] == pytest.approx(0.0)

    def test_corporate_high_ltv_splits_55_45(self) -> None:
        """EAD 100, property 100 → cap 55; secured = 55, residual = 45."""
        bundle = _build_bundle(
            [
                {
                    "exposure_reference": "B31RRE2",
                    "exposure_class": "CORPORATE",
                    "ead_final": 100.0,
                    "re_split_target_class": "RESIDENTIAL_MORTGAGE",
                    "re_split_mode": "split",
                    "re_split_property_type": "residential",
                    "re_split_property_value": 100.0,
                    "property_collateral_value": 100.0,
                }
            ]
        )

        df = RealEstateSplitter().split(bundle, _b31()).exposures.collect()
        secured = _by_role(df, "secured")
        residual = _by_role(df, "residual")
        assert secured["ead_final"] == pytest.approx(55.0)
        assert secured["exposure_class"] == "RESIDENTIAL_MORTGAGE"
        assert residual["ead_final"] == pytest.approx(45.0)
        assert residual["exposure_class"] == "CORPORATE"

    def test_art_124f2_prior_charge_reduces_threshold(self) -> None:
        """Prior charge LTV 0.10 → effective cap 0.45; secured = 45 on 100 EAD."""
        bundle = _build_bundle(
            [
                {
                    "exposure_reference": "B31RRE3",
                    "exposure_class": "CORPORATE",
                    "ead_final": 100.0,
                    "re_split_target_class": "RESIDENTIAL_MORTGAGE",
                    "re_split_mode": "split",
                    "re_split_property_type": "residential",
                    "re_split_property_value": 100.0,
                    "property_collateral_value": 100.0,
                    "prior_charge_ltv": 0.10,
                }
            ]
        )

        df = RealEstateSplitter().split(bundle, _b31()).exposures.collect()
        secured = _by_role(df, "secured")
        residual = _by_role(df, "residual")
        assert secured["ead_final"] == pytest.approx(45.0)
        assert residual["ead_final"] == pytest.approx(55.0)


class TestB31CommercialSplit:
    """B3.1 Art. 124H(1)-(2) — CRE NP/SME loan-split."""

    def test_natural_person_high_ltv_split(self) -> None:
        """EAD 200, property 300 → cap 165; secured 165, residual 35."""
        bundle = _build_bundle(
            [
                {
                    "exposure_reference": "B31CRE1",
                    "exposure_class": "RETAIL_OTHER",
                    "ead_final": 200.0,
                    "re_split_target_class": "COMMERCIAL_MORTGAGE",
                    "re_split_mode": "split",
                    "re_split_property_type": "commercial",
                    "re_split_property_value": 300.0,
                    "property_collateral_value": 300.0,
                    "cp_is_natural_person": True,
                }
            ]
        )

        df = RealEstateSplitter().split(bundle, _b31()).exposures.collect()
        secured = _by_role(df, "secured")
        residual = _by_role(df, "residual")
        assert secured["ead_final"] == pytest.approx(165.0)
        assert secured["exposure_class"] == "COMMERCIAL_MORTGAGE"
        assert residual["ead_final"] == pytest.approx(35.0)
        assert residual["exposure_class"] == "RETAIL_OTHER"

    def test_corporate_other_uses_whole_loan(self) -> None:
        """Art. 124H(3) — single COMMERCIAL_MORTGAGE row, no residual."""
        bundle = _build_bundle(
            [
                {
                    "exposure_reference": "B31CRE2",
                    "exposure_class": "CORPORATE",
                    "ead_final": 200.0,
                    "re_split_target_class": "COMMERCIAL_MORTGAGE",
                    "re_split_mode": "whole",
                    "re_split_property_type": "commercial",
                    "re_split_property_value": 300.0,
                    "property_collateral_value": 300.0,
                    "cp_is_natural_person": False,
                    "is_sme": False,
                }
            ]
        )

        df = RealEstateSplitter().split(bundle, _b31()).exposures.collect()
        assert df.height == 1
        row = df.to_dicts()[0]
        assert row["exposure_class"] == "COMMERCIAL_MORTGAGE"
        assert row["ead_final"] == pytest.approx(200.0)
        assert row["re_split_role"] == "whole"
        assert row["split_parent_id"] == "B31CRE2"


# ---------------------------------------------------------------------------
# Cross-cutting / regression cases
# ---------------------------------------------------------------------------


class TestSplitterPassThrough:
    """The splitter must be a no-op for unflagged rows."""

    @pytest.mark.parametrize("config_factory", [_crr, _b31])
    def test_unflagged_rows_pass_through(self, config_factory) -> None:
        bundle = _build_bundle(
            [
                {
                    "exposure_reference": "PASS1",
                    "exposure_class": "CORPORATE",
                    "ead_final": 100.0,
                    "re_split_mode": None,
                }
            ]
        )

        df = RealEstateSplitter().split(bundle, config_factory()).exposures.collect()
        assert df.height == 1
        row = df.to_dicts()[0]
        assert row["exposure_class"] == "CORPORATE"
        assert row["ead_final"] == pytest.approx(100.0)
        assert row["re_split_role"] is None
        assert row["split_parent_id"] is None

    def test_parent_ead_reconciles(self) -> None:
        """Sum of secured + residual == parent EAD for every split row."""
        bundle = _build_bundle(
            [
                {
                    "exposure_reference": "REC1",
                    "exposure_class": "CORPORATE",
                    "ead_final": 137.5,
                    "re_split_target_class": "RESIDENTIAL_MORTGAGE",
                    "re_split_mode": "split",
                    "re_split_property_type": "residential",
                    "re_split_property_value": 200.0,
                    "property_collateral_value": 200.0,
                },
                {
                    "exposure_reference": "REC2",
                    "exposure_class": "CORPORATE_SME",
                    "ead_final": 250.0,
                    "re_split_target_class": "COMMERCIAL_MORTGAGE",
                    "re_split_mode": "split",
                    "re_split_property_type": "commercial",
                    "re_split_property_value": 400.0,
                    "property_collateral_value": 400.0,
                    "is_sme": True,
                },
            ]
        )

        df = RealEstateSplitter().split(bundle, _b31()).exposures.collect()
        # Group by split_parent_id and sum EADs; compare to original.
        recon = (
            df.filter(pl.col("split_parent_id").is_not_null())
            .group_by("split_parent_id")
            .agg(pl.col("ead_final").sum().alias("total"))
            .sort("split_parent_id")
        )
        totals = {r["split_parent_id"]: r["total"] for r in recon.to_dicts()}
        assert totals["REC1"] == pytest.approx(137.5)
        assert totals["REC2"] == pytest.approx(250.0)

    def test_provisions_allocate_pro_rata(self) -> None:
        """Provisions allocate pro-rata to secured / residual EAD."""
        bundle = _build_bundle(
            [
                {
                    "exposure_reference": "PROV1",
                    "exposure_class": "CORPORATE",
                    "ead_final": 100.0,
                    "provision_allocated": 10.0,
                    "re_split_target_class": "RESIDENTIAL_MORTGAGE",
                    "re_split_mode": "split",
                    "re_split_property_type": "residential",
                    "re_split_property_value": 100.0,
                    "property_collateral_value": 100.0,
                },
            ]
        )

        df = RealEstateSplitter().split(bundle, _b31()).exposures.collect()
        secured = _by_role(df, "secured")
        residual = _by_role(df, "residual")
        # Secured = 55 / 100 * 10 = 5.5; residual = 45 / 100 * 10 = 4.5
        assert secured["provision_allocated"] == pytest.approx(5.5)
        assert residual["provision_allocated"] == pytest.approx(4.5)
        total = secured["provision_allocated"] + residual["provision_allocated"]
        assert total == pytest.approx(10.0)


class TestSplitterAuditTrail:
    """Per-parent audit row for every actually-split exposure."""

    def test_audit_emits_row_per_split(self) -> None:
        bundle = _build_bundle(
            [
                {
                    "exposure_reference": "AUD1",
                    "exposure_class": "CORPORATE",
                    "ead_final": 100.0,
                    "re_split_target_class": "RESIDENTIAL_MORTGAGE",
                    "re_split_mode": "split",
                    "re_split_property_type": "residential",
                    "re_split_property_value": 100.0,
                    "property_collateral_value": 100.0,
                },
                {
                    "exposure_reference": "AUD2",
                    "exposure_class": "CORPORATE",
                    "ead_final": 100.0,
                    "re_split_mode": None,  # untouched
                },
            ]
        )

        result = RealEstateSplitter().split(bundle, _b31())
        assert result.re_split_audit is not None
        audit = result.re_split_audit.collect()
        assert audit.height == 1
        row = audit.to_dicts()[0]
        assert row["split_parent_id"] == "AUD1"
        assert row["secured_ead"] == pytest.approx(55.0)
        assert row["residual_ead"] == pytest.approx(45.0)
        assert row["target_class"] == "RESIDENTIAL_MORTGAGE"
        assert row["regime"] == "basel_3_1"
