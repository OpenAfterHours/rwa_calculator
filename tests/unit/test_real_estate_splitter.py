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
        # Classifier-emitted candidate columns. Per-component eligibility
        # columns are intentionally absent — single-component tests trigger
        # the splitter's backward-compat derivation from re_split_mode +
        # re_split_property_type. Mixed-collateral tests set them explicitly.
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
                    "re_split_target_class": "residential_mortgage",
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
        assert secured["exposure_class"] == "residential_mortgage"
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
                    "re_split_target_class": "residential_mortgage",
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
                    "re_split_target_class": "commercial_mortgage",
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
                    "re_split_target_class": "commercial_mortgage",
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
                    "re_split_target_class": "residential_mortgage",
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
                    "re_split_target_class": "residential_mortgage",
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
        assert secured["exposure_class"] == "residential_mortgage"
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
                    "re_split_target_class": "residential_mortgage",
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
                    "re_split_target_class": "commercial_mortgage",
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
        assert secured["exposure_class"] == "commercial_mortgage"
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
                    "re_split_target_class": "commercial_mortgage",
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
        assert row["exposure_class"] == "commercial_mortgage"
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
                    "re_split_target_class": "residential_mortgage",
                    "re_split_mode": "split",
                    "re_split_property_type": "residential",
                    "re_split_property_value": 200.0,
                    "property_collateral_value": 200.0,
                },
                {
                    "exposure_reference": "REC2",
                    "exposure_class": "CORPORATE_SME",
                    "ead_final": 250.0,
                    "re_split_target_class": "commercial_mortgage",
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
                    "re_split_target_class": "residential_mortgage",
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
                    "re_split_target_class": "residential_mortgage",
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
        assert row["target_class"] == "residential_mortgage"
        assert row["regime"] == "basel_3_1"


class TestSplitterApproachGate:
    """Loan-splitting is SA-only — IRB / Slotting rows pass through unsplit.

    Rationale: CRR Art. 125/126 and PRA PS1/26 Art. 124F/H are all in the
    Standardised Approach part. Under IRB, residential-property collateral
    affects LGD (Art. 161(5) FIRB floor / AIRB own-estimate LGD), not
    exposure-class reclassification. Splitting an IRB row into a
    RESIDENTIAL_MORTGAGE secured child caused the IRB correlation formula
    to return the 0.15 retail-mortgage correlation instead of the
    corporate-SME supervisory correlation.
    """

    @pytest.mark.parametrize("approach", ["foundation_irb", "advanced_irb", "slotting"])
    def test_irb_row_with_split_flag_is_pass_through(self, approach: str) -> None:
        """FIRB/AIRB/Slotting rows keep their original exposure_class."""
        bundle = _build_bundle(
            [
                {
                    "exposure_reference": "IRB1",
                    "exposure_class": "CORPORATE_SME",
                    "approach": approach,
                    "ead_final": 100.0,
                    "re_split_target_class": "residential_mortgage",
                    "re_split_mode": "split",
                    "re_split_property_type": "residential",
                    "re_split_property_value": 200.0,
                    "property_collateral_value": 200.0,
                    "is_sme": True,
                }
            ]
        )

        df = RealEstateSplitter().split(bundle, _b31()).exposures.collect()

        assert df.height == 1, "IRB row must not be split into secured+residual"
        row = df.to_dicts()[0]
        assert row["exposure_class"] == "CORPORATE_SME"
        assert row["ead_final"] == pytest.approx(100.0)
        assert row["exposure_reference"] == "IRB1"
        assert row["re_split_role"] is None
        assert row["split_parent_id"] is None

    def test_irb_row_with_whole_flag_is_pass_through(self) -> None:
        """IRB row flagged as B3.1 Art. 124H(3) whole-loan is still IRB."""
        bundle = _build_bundle(
            [
                {
                    "exposure_reference": "IRB2",
                    "exposure_class": "CORPORATE",
                    "approach": "foundation_irb",
                    "ead_final": 200.0,
                    "re_split_target_class": "commercial_mortgage",
                    "re_split_mode": "whole",
                    "re_split_property_type": "commercial",
                    "re_split_property_value": 300.0,
                    "property_collateral_value": 300.0,
                }
            ]
        )

        df = RealEstateSplitter().split(bundle, _b31()).exposures.collect()

        assert df.height == 1
        row = df.to_dicts()[0]
        # Not reclassified to COMMERCIAL_MORTGAGE.
        assert row["exposure_class"] == "CORPORATE"
        assert row["ead_final"] == pytest.approx(200.0)

    def test_sa_row_with_approach_column_still_splits(self) -> None:
        """Regression guard: the gate must not break the SA path."""
        bundle = _build_bundle(
            [
                {
                    "exposure_reference": "SA1",
                    "exposure_class": "CORPORATE",
                    "approach": "standardised",
                    "ead_final": 100.0,
                    "re_split_target_class": "residential_mortgage",
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
        assert secured["exposure_class"] == "residential_mortgage"
        assert residual["ead_final"] == pytest.approx(45.0)

    def test_irb_row_does_not_emit_re002_warning(self) -> None:
        """IRB rows with zero effective cap must not trigger SA RE002."""
        bundle = _build_bundle(
            [
                {
                    "exposure_reference": "IRB3",
                    "exposure_class": "CORPORATE_SME",
                    "approach": "foundation_irb",
                    "ead_final": 100.0,
                    "re_split_target_class": "residential_mortgage",
                    "re_split_mode": "split",
                    "re_split_property_type": "residential",
                    "re_split_property_value": 0.0,  # zero cap
                    "property_collateral_value": 0.0,
                    "is_sme": True,
                }
            ]
        )

        result = RealEstateSplitter().split(bundle, _b31())
        assert not any(e.code == "RE002" for e in result.crm_errors)

    def test_mixed_sa_and_irb_batch(self) -> None:
        """SA rows split; IRB rows with the same flag do not."""
        bundle = _build_bundle(
            [
                {
                    "exposure_reference": "SA_MIX",
                    "exposure_class": "CORPORATE",
                    "approach": "standardised",
                    "ead_final": 100.0,
                    "re_split_target_class": "residential_mortgage",
                    "re_split_mode": "split",
                    "re_split_property_type": "residential",
                    "re_split_property_value": 100.0,
                    "property_collateral_value": 100.0,
                },
                {
                    "exposure_reference": "IRB_MIX",
                    "exposure_class": "CORPORATE_SME",
                    "approach": "foundation_irb",
                    "ead_final": 100.0,
                    "re_split_target_class": "residential_mortgage",
                    "re_split_mode": "split",
                    "re_split_property_type": "residential",
                    "re_split_property_value": 100.0,
                    "property_collateral_value": 100.0,
                    "is_sme": True,
                },
            ]
        )

        df = RealEstateSplitter().split(bundle, _b31()).exposures.collect()

        sa_rows = df.filter(pl.col("exposure_reference").str.starts_with("SA_MIX"))
        irb_rows = df.filter(pl.col("exposure_reference").str.starts_with("IRB_MIX"))

        assert sa_rows.height == 2  # split into _sec + _res
        assert irb_rows.height == 1  # pass-through
        assert irb_rows.to_dicts()[0]["exposure_class"] == "CORPORATE_SME"


# ---------------------------------------------------------------------------
# Mixed RRE + CRE collateral on a single exposure
# (PRA PS1/26 Art. 124(4) pro-rata; CRR Art. 124(1) "any part" — RRE-first)
# ---------------------------------------------------------------------------


def _mixed_bundle(
    *,
    ead: float,
    rre_value: float,
    cre_value: float,
    cre_rental_met: bool = True,
    is_npsme: bool = True,
    prior_charge_ltv: float = 0.0,
    exposure_class: str = "CORPORATE",
    provision: float = 0.0,
) -> CRMAdjustedBundle:
    """Build a mixed RRE+CRE exposure with both per-component flags set."""
    return _build_bundle(
        [
            {
                "exposure_reference": "MIX1",
                "exposure_class": exposure_class,
                "ead_final": ead,
                "provision_allocated": provision,
                "re_split_target_class": None,  # null for mixed; per-child set in splitter
                "re_split_mode": "split",
                "re_split_property_type": "mixed",
                "re_split_property_value": rre_value + cre_value,
                "re_split_residential_value": rre_value,
                "re_split_commercial_value": cre_value,
                "re_split_residential_eligible": rre_value > 0.0,
                "re_split_commercial_eligible": cre_value > 0.0 and cre_rental_met,
                "re_split_cre_rental_coverage_met": cre_rental_met,
                "property_collateral_value": rre_value + cre_value,
                "residential_collateral_value": rre_value,
                "prior_charge_ltv": prior_charge_ltv,
                "cp_is_natural_person": is_npsme,
                "is_sme": False,
            }
        ]
    )


class TestCRRMixedCollateral:
    """CRR Art. 124(1) "any part of an exposure" — RRE-first sequential split.

    User-instructed allocation policy: residential collateral (35% RW) is
    consumed first up to its 80% LTV cap; commercial (50% RW) takes the
    remainder up to its 50% LTV cap, but only when Art. 126(2)(d) rental
    coverage is satisfied.
    """

    def test_mixed_rre_absorbs_full_ead_no_cre_row(self) -> None:
        """EAD 100, RRE=200 (cap 160), CRE=200: RRE alone covers EAD.

        Only one component receives EAD → row uses the legacy ``secured``
        role (not ``secured_rre``) because the splitter only labels the
        pair when *both* components have allocated EAD.
        """
        bundle = _mixed_bundle(ead=100.0, rre_value=200.0, cre_value=200.0)

        df = RealEstateSplitter().split(bundle, _crr()).exposures.collect()

        secured = _by_role(df, "secured")
        cre_rows = df.filter(pl.col("re_split_role") == "secured_cre")
        residual = _by_role(df, "residual")

        assert cre_rows.height == 0
        assert secured["ead_final"] == pytest.approx(100.0)
        assert secured["exposure_class"] == "residential_mortgage"
        assert secured["property_type"] == "residential"
        assert residual["ead_final"] == pytest.approx(0.0)
        assert residual["exposure_class"] == "CORPORATE"

    def test_mixed_rre_first_then_cre_then_residual(self) -> None:
        """EAD 200, RRE=100 (cap 80), CRE=200 (cap 100), rental met.

        RRE-first: rre_secured = 80; remaining = 120; cre_secured = 100;
        residual = 20 at counterparty RW.
        """
        bundle = _mixed_bundle(ead=200.0, rre_value=100.0, cre_value=200.0)

        df = RealEstateSplitter().split(bundle, _crr()).exposures.collect()

        rre = _by_role(df, "secured_rre")
        cre = _by_role(df, "secured_cre")
        residual = _by_role(df, "residual")

        assert rre["ead_final"] == pytest.approx(80.0)
        assert rre["exposure_class"] == "residential_mortgage"
        assert rre["ltv"] == pytest.approx(0.80)
        assert cre["ead_final"] == pytest.approx(100.0)
        assert cre["exposure_class"] == "commercial_mortgage"
        assert cre["has_income_cover"] is True  # CRR Art. 126(2)(d)
        assert cre["ltv"] == pytest.approx(0.50)
        assert residual["ead_final"] == pytest.approx(20.0)
        assert residual["exposure_class"] == "CORPORATE"
        # Reconciles to parent EAD.
        assert (rre["ead_final"] + cre["ead_final"] + residual["ead_final"]) == pytest.approx(200.0)

    def test_mixed_cre_rental_failed_only_rre_secured(self) -> None:
        """When CRE rental coverage fails, only the RRE component is preferential."""
        bundle = _mixed_bundle(ead=200.0, rre_value=100.0, cre_value=200.0, cre_rental_met=False)

        df = RealEstateSplitter().split(bundle, _crr()).exposures.collect()

        # Only one component is eligible — emitted as a "secured" row (not "secured_rre"),
        # since the splitter only labels the pair when *both* components have EAD > 0.
        secured = _by_role(df, "secured")
        residual = _by_role(df, "residual")

        assert secured["ead_final"] == pytest.approx(80.0)
        assert secured["exposure_class"] == "residential_mortgage"
        assert residual["ead_final"] == pytest.approx(120.0)
        assert residual["exposure_class"] == "CORPORATE"

    def test_mixed_audit_records_per_component_breakdown(self) -> None:
        bundle = _mixed_bundle(ead=200.0, rre_value=100.0, cre_value=200.0)

        result = RealEstateSplitter().split(bundle, _crr())
        assert result.re_split_audit is not None
        audit = result.re_split_audit.collect().to_dicts()[0]

        assert audit["split_parent_id"] == "MIX1"
        assert audit["parent_ead"] == pytest.approx(200.0)
        assert audit["rre_secured_ead"] == pytest.approx(80.0)
        assert audit["cre_secured_ead"] == pytest.approx(100.0)
        assert audit["residual_ead"] == pytest.approx(20.0)
        assert audit["rre_property_value"] == pytest.approx(100.0)
        assert audit["cre_property_value"] == pytest.approx(200.0)
        assert audit["is_mixed"] is True
        assert audit["regime"] == "crr"


class TestB31MixedCollateral:
    """PRA PS1/26 Art. 124(4) — pro-rata split by collateral value.

    rre_share = rre_v / (rre_v + cre_v); cre_share = 1 - rre_share.
    Each component's secured EAD = min(EAD × share, 0.55 × component_v).
    """

    def test_mixed_natural_person_pro_rata(self) -> None:
        """EAD 100, RRE=60, CRE=40 → rre_share=0.6; cre_share=0.4.

        rre_secured = min(60, 33) = 33; cre_secured = min(40, 22) = 22;
        residual = 45.
        """
        bundle = _mixed_bundle(ead=100.0, rre_value=60.0, cre_value=40.0)

        df = RealEstateSplitter().split(bundle, _b31()).exposures.collect()

        rre = _by_role(df, "secured_rre")
        cre = _by_role(df, "secured_cre")
        residual = _by_role(df, "residual")

        assert rre["ead_final"] == pytest.approx(33.0)
        assert rre["exposure_class"] == "residential_mortgage"
        assert rre["property_type"] == "residential"
        assert rre["property_collateral_value"] == pytest.approx(60.0)
        assert cre["ead_final"] == pytest.approx(22.0)
        assert cre["exposure_class"] == "commercial_mortgage"
        assert cre["property_type"] == "commercial"
        assert cre["property_collateral_value"] == pytest.approx(40.0)
        assert residual["ead_final"] == pytest.approx(45.0)
        assert residual["exposure_class"] == "CORPORATE"

    def test_mixed_under_cap_emits_pro_rata_unbound(self) -> None:
        """EAD 50, RRE=200, CRE=200 → both within cap; pro-rata fills EAD."""
        bundle = _mixed_bundle(ead=50.0, rre_value=200.0, cre_value=200.0)

        df = RealEstateSplitter().split(bundle, _b31()).exposures.collect()
        rre = _by_role(df, "secured_rre")
        cre = _by_role(df, "secured_cre")
        residual = _by_role(df, "residual")

        # rre_share=0.5, cre_share=0.5; allocation 25 each, both below 110 cap.
        assert rre["ead_final"] == pytest.approx(25.0)
        assert cre["ead_final"] == pytest.approx(25.0)
        assert residual["ead_final"] == pytest.approx(0.0)

    def test_mixed_with_prior_charge_reduces_both_caps(self) -> None:
        """Prior charge LTV 0.10 → cap_pct = 0.45 for both components.

        EAD 100, RRE=80, CRE=20 (total 100): rre_share=0.8, cre_share=0.2.
        rre_secured = min(80, 0.45 × 80) = 36; cre_secured = min(20, 0.45 × 20) = 9;
        residual = 100 - 36 - 9 = 55.
        """
        bundle = _mixed_bundle(
            ead=100.0,
            rre_value=80.0,
            cre_value=20.0,
            prior_charge_ltv=0.10,
        )

        df = RealEstateSplitter().split(bundle, _b31()).exposures.collect()
        rre = _by_role(df, "secured_rre")
        cre = _by_role(df, "secured_cre")
        residual = _by_role(df, "residual")

        assert rre["ead_final"] == pytest.approx(36.0)
        assert cre["ead_final"] == pytest.approx(9.0)
        assert residual["ead_final"] == pytest.approx(55.0)

    def test_mixed_provisions_split_three_ways(self) -> None:
        """Provisions allocate pro-rata to each child's EAD share."""
        bundle = _mixed_bundle(ead=100.0, rre_value=60.0, cre_value=40.0, provision=10.0)

        df = RealEstateSplitter().split(bundle, _b31()).exposures.collect()
        rre = _by_role(df, "secured_rre")
        cre = _by_role(df, "secured_cre")
        residual = _by_role(df, "residual")

        # rre 33/100 * 10 = 3.3; cre 22/100 * 10 = 2.2; residual 45/100 * 10 = 4.5.
        assert rre["provision_allocated"] == pytest.approx(3.3)
        assert cre["provision_allocated"] == pytest.approx(2.2)
        assert residual["provision_allocated"] == pytest.approx(4.5)
        total = (
            rre["provision_allocated"]
            + cre["provision_allocated"]
            + residual["provision_allocated"]
        )
        assert total == pytest.approx(10.0)

    def test_mixed_emits_re003_warning(self) -> None:
        """Each mixed split contributes one row to the RE003 informational count."""
        bundle = _mixed_bundle(ead=100.0, rre_value=60.0, cre_value=40.0)

        result = RealEstateSplitter().split(bundle, _b31())
        re003 = [e for e in result.crm_errors if e.code == "RE003"]
        assert len(re003) == 1
        assert "1 exposure(s)" in re003[0].message
        assert "pro-rata" in re003[0].message  # B3.1 allocation rule named in message
        assert re003[0].regulatory_reference == "PRA PS1/26 Art. 124(4)"

    def test_mixed_audit_records_pro_rata_breakdown(self) -> None:
        bundle = _mixed_bundle(ead=100.0, rre_value=60.0, cre_value=40.0)

        result = RealEstateSplitter().split(bundle, _b31())
        assert result.re_split_audit is not None
        audit = result.re_split_audit.collect().to_dicts()[0]

        assert audit["rre_secured_ead"] == pytest.approx(33.0)
        assert audit["cre_secured_ead"] == pytest.approx(22.0)
        assert audit["residual_ead"] == pytest.approx(45.0)
        assert audit["is_mixed"] is True
        assert audit["regime"] == "basel_3_1"


class TestMixedReconciliation:
    """Per-parent reconciliation across mixed and pure splits in one batch."""

    def test_mixed_and_pure_in_same_batch_reconcile_to_parent_ead(self) -> None:
        rows = [
            # Mixed RRE+CRE
            {
                "exposure_reference": "M1",
                "exposure_class": "CORPORATE",
                "ead_final": 100.0,
                "re_split_mode": "split",
                "re_split_property_type": "mixed",
                "re_split_property_value": 100.0,
                "re_split_residential_value": 60.0,
                "re_split_commercial_value": 40.0,
                "re_split_residential_eligible": True,
                "re_split_commercial_eligible": True,
                "property_collateral_value": 100.0,
                "residential_collateral_value": 60.0,
                "cp_is_natural_person": True,
            },
            # Pure RRE
            {
                "exposure_reference": "P1",
                "exposure_class": "CORPORATE",
                "ead_final": 100.0,
                "re_split_target_class": "residential_mortgage",
                "re_split_mode": "split",
                "re_split_property_type": "residential",
                "re_split_property_value": 100.0,
                "re_split_residential_value": 100.0,
                "re_split_commercial_value": 0.0,
                "re_split_residential_eligible": True,
                "re_split_commercial_eligible": False,
                "property_collateral_value": 100.0,
                "residential_collateral_value": 100.0,
            },
        ]
        bundle = _build_bundle(rows)
        df = RealEstateSplitter().split(bundle, _b31()).exposures.collect()

        recon = (
            df.filter(pl.col("split_parent_id").is_not_null())
            .group_by("split_parent_id")
            .agg(pl.col("ead_final").sum().alias("total"))
            .sort("split_parent_id")
        )
        totals = {r["split_parent_id"]: r["total"] for r in recon.to_dicts()}
        assert totals["M1"] == pytest.approx(100.0)
        assert totals["P1"] == pytest.approx(100.0)

        # Mixed parent emits 3 rows (rre + cre + residual); pure parent emits 2.
        m1_rows = df.filter(pl.col("split_parent_id") == "M1")
        p1_rows = df.filter(pl.col("split_parent_id") == "P1")
        assert m1_rows.height == 3
        assert p1_rows.height == 2

    def test_pure_rre_uses_secured_role_not_secured_rre(self) -> None:
        """Backward compat: single-component splits keep the legacy 'secured' role."""
        rows = [
            {
                "exposure_reference": "PRRE",
                "exposure_class": "CORPORATE",
                "ead_final": 100.0,
                "re_split_target_class": "residential_mortgage",
                "re_split_mode": "split",
                "re_split_property_type": "residential",
                "re_split_property_value": 100.0,
                "re_split_residential_value": 100.0,
                "re_split_commercial_value": 0.0,
                "re_split_residential_eligible": True,
                "re_split_commercial_eligible": False,
                "property_collateral_value": 100.0,
                "residential_collateral_value": 100.0,
            }
        ]
        bundle = _build_bundle(rows)
        df = RealEstateSplitter().split(bundle, _b31()).exposures.collect()

        roles = set(df["re_split_role"].to_list())
        assert "secured" in roles
        assert "secured_rre" not in roles
        assert "secured_cre" not in roles
