"""Unit tests for the applied reporting class (``exposure_class_applied``).

The routing ``exposure_class`` records origination + guarantee substitution but
not two SA-only applied-treatment movements, so the reconciliation and COREP
class dimensions previously mis-bucketed those rows (RWA is correct; only the
class label was wrong):

- SME managed as retail took the 75% retail RW but stayed ``corporate_sme``.
- Defaulted SA exposures kept their origination class instead of routing to the
  "Exposures in default" class (CRR Art. 112(1)(j)).

The aggregator now derives ``exposure_class_applied`` so both are reported under
the class that matches the applied risk weight. IRB / slotting / equity rows keep
``exposure_class`` untouched.

References:
- CRR Art. 112(1)(j) / Art. 127: exposures in default
- CRR Art. 123 / PS1/26 Art. 123A: SME retail treatment
"""

from __future__ import annotations

import polars as pl
import pytest

from rwa_calc.analysis.recon_registry import RECONCILABLE_COMPONENTS_BY_NAME
from rwa_calc.domain.enums import ExposureClass
from rwa_calc.engine.aggregator.aggregator import (
    _add_exposure_class_applied,
    _add_post_crm_reporting_class,
)
from rwa_calc.reporting.corep.generator import COREPGenerator

# =============================================================================
# Aggregator helper — _add_exposure_class_applied
# =============================================================================


def _applied(rows: list[dict[str, object]]) -> list[str | None]:
    """Run ``_add_exposure_class_applied`` over ``rows`` and return the column."""
    lf = pl.LazyFrame(
        rows,
        schema={
            "approach_applied": pl.String,
            "exposure_class": pl.String,
            "is_defaulted": pl.Boolean,
            "cp_is_managed_as_retail": pl.Boolean,
            "qualifies_as_retail": pl.Boolean,
        },
    )
    return _add_exposure_class_applied(lf).collect()["exposure_class_applied"].to_list()


def _row(
    approach: str = "standardised",
    ec: str = "corporate",
    *,
    defaulted: bool = False,
    managed_as_retail: bool = False,
    qualifies: bool = False,
) -> dict[str, object]:
    return {
        "approach_applied": approach,
        "exposure_class": ec,
        "is_defaulted": defaulted,
        "cp_is_managed_as_retail": managed_as_retail,
        "qualifies_as_retail": qualifies,
    }


class TestAddExposureClassApplied:
    """The applied-class derivation mirrors the SA risk-weight predicate."""

    def test_sme_managed_as_retail_becomes_retail_other(self) -> None:
        """A qualifying SME managed as retail (75% RW) reports as retail_other."""
        result = _applied([_row(ec="corporate_sme", managed_as_retail=True, qualifies=True)])
        assert result[0] == ExposureClass.RETAIL_OTHER.value

    def test_sme_not_managed_as_retail_keeps_corporate_sme(self) -> None:
        """An SME that is not managed as retail keeps its corporate_sme class."""
        result = _applied([_row(ec="corporate_sme", managed_as_retail=False, qualifies=True)])
        assert result[0] == ExposureClass.CORPORATE_SME.value

    def test_sme_managed_but_not_qualifying_keeps_corporate_sme(self) -> None:
        """Managed-as-retail without qualifying (over threshold) stays corporate_sme."""
        result = _applied([_row(ec="corporate_sme", managed_as_retail=True, qualifies=False)])
        assert result[0] == ExposureClass.CORPORATE_SME.value

    def test_defaulted_sa_becomes_defaulted(self) -> None:
        """A defaulted SA exposure reports under the exposures-in-default class."""
        result = _applied([_row(ec="corporate", defaulted=True)])
        assert result[0] == ExposureClass.DEFAULTED.value

    def test_defaulted_wins_over_sme_retail(self) -> None:
        """Default (priority 5) outranks the SME-managed-as-retail movement."""
        result = _applied(
            [_row(ec="corporate_sme", defaulted=True, managed_as_retail=True, qualifies=True)]
        )
        assert result[0] == ExposureClass.DEFAULTED.value

    def test_high_risk_wins_over_defaulted(self) -> None:
        """High-risk (Art. 128, priority 4) outranks default for a defaulted row."""
        result = _applied([_row(ec=ExposureClass.HIGH_RISK.value, defaulted=True)])
        assert result[0] == ExposureClass.HIGH_RISK.value

    def test_performing_corporate_unchanged(self) -> None:
        """A plain performing corporate keeps its origination class."""
        result = _applied([_row(ec="corporate")])
        assert result[0] == ExposureClass.CORPORATE.value

    def test_irb_defaulted_keeps_exposure_class(self) -> None:
        """IRB reports default via a PD override, not a class — class is untouched."""
        result = _applied([_row(approach="advanced_irb", ec="retail_mortgage", defaulted=True)])
        assert result[0] == "retail_mortgage"

    def test_irb_sme_managed_as_retail_keeps_exposure_class(self) -> None:
        """IRB already reclassifies corporate→retail on exposure_class itself."""
        result = _applied(
            [
                _row(
                    approach="foundation_irb",
                    ec="corporate_sme",
                    managed_as_retail=True,
                    qualifies=True,
                )
            ]
        )
        assert result[0] == ExposureClass.CORPORATE_SME.value

    def test_slotting_keeps_specialised_lending(self) -> None:
        """Slotting rows keep SPECIALISED_LENDING even when defaulted."""
        result = _applied(
            [_row(approach="slotting", ec=ExposureClass.SPECIALISED_LENDING.value, defaulted=True)]
        )
        assert result[0] == ExposureClass.SPECIALISED_LENDING.value

    def test_equity_keeps_equity(self) -> None:
        """Equity rows keep the equity class."""
        result = _applied([_row(approach="equity", ec="equity")])
        assert result[0] == ExposureClass.EQUITY.value


# =============================================================================
# Guaranteed legs (pre-substitution semantics)
# =============================================================================


def _applied_with_guarantee(rows: list[dict[str, object]]) -> list[str | None]:
    """Run the helper over rows that carry an ``is_guaranteed`` flag."""
    lf = pl.LazyFrame(
        rows,
        schema={
            "approach_applied": pl.String,
            "exposure_class": pl.String,
            "is_defaulted": pl.Boolean,
            "cp_is_managed_as_retail": pl.Boolean,
            "qualifies_as_retail": pl.Boolean,
            "is_guaranteed": pl.Boolean,
        },
    )
    return _add_exposure_class_applied(lf).collect()["exposure_class_applied"].to_list()


class TestGuaranteedLegAppliedClass:
    """A guaranteed exposure's ``__G_`` / ``__REM`` legs both keep the obligor's
    pre-substitution applied class — the overlay is NOT gated on ``is_guaranteed``.

    Both legs carry the obligor's origination ``exposure_class`` (the guarantor's
    class lives in ``post_crm_exposure_class_guaranteed``), so in COREP C 07.00 the
    whole exposure originates in the obligor's sheet and the guaranteed portion
    leaves via a substitution outflow. Gating on ``~is_guaranteed`` would drop the
    guaranteed portion out of the defaulted / retail class and understate it.
    """

    def test_defaulted_guaranteed_leg_stays_defaulted(self) -> None:
        """The guaranteed leg (is_guaranteed=True) of a defaulted obligor is defaulted."""
        result = _applied_with_guarantee(
            [
                {**_row(ec="corporate_sme", defaulted=True), "is_guaranteed": True},  # __G_ leg
                {**_row(ec="corporate_sme", defaulted=True), "is_guaranteed": False},  # __REM leg
            ]
        )
        assert result == [ExposureClass.DEFAULTED.value, ExposureClass.DEFAULTED.value]

    def test_sme_retail_guaranteed_leg_stays_retail(self) -> None:
        """The guaranteed leg of an SME-managed-as-retail obligor stays retail_other."""
        result = _applied_with_guarantee(
            [
                {
                    **_row(ec="corporate_sme", managed_as_retail=True, qualifies=True),
                    "is_guaranteed": True,
                },
            ]
        )
        assert result[0] == ExposureClass.RETAIL_OTHER.value


# =============================================================================
# Reconciliation registry wiring
# =============================================================================


class TestReconClassComponent:
    """The exposure_class recon component prefers the post-guarantee class."""

    def test_prefers_post_crm_then_applied_then_origination(self) -> None:
        component = RECONCILABLE_COMPONENTS_BY_NAME["exposure_class"]
        assert component.our_columns == (
            "exposure_class_post_crm",
            "exposure_class_applied",
            "exposure_class",
        )

    def test_origination_class_surfaced_as_rationale(self) -> None:
        component = RECONCILABLE_COMPONENTS_BY_NAME["exposure_class"]
        assert "exposure_class" in component.explain_columns


# =============================================================================
# Post-guarantee reporting class (exposure_class_post_crm)
# =============================================================================


def _post_crm(rows: list[dict[str, object]]) -> list[str | None]:
    """Run both aggregator helpers and return the post-guarantee class column."""
    lf = pl.LazyFrame(
        rows,
        schema={
            "approach_applied": pl.String,
            "exposure_class": pl.String,
            "is_defaulted": pl.Boolean,
            "cp_is_managed_as_retail": pl.Boolean,
            "qualifies_as_retail": pl.Boolean,
            "is_guaranteed": pl.Boolean,
            "post_crm_exposure_class_guaranteed": pl.String,
        },
    )
    out = _add_post_crm_reporting_class(_add_exposure_class_applied(lf))
    return out.collect()["exposure_class_post_crm"].to_list()


def _guar_row(
    ec: str = "corporate",
    *,
    defaulted: bool = False,
    guaranteed: bool = False,
    guarantor_class: str | None = None,
) -> dict[str, object]:
    return {
        "approach_applied": "standardised",
        "exposure_class": ec,
        "is_defaulted": defaulted,
        "cp_is_managed_as_retail": False,
        "qualifies_as_retail": False,
        "is_guaranteed": guaranteed,
        "post_crm_exposure_class_guaranteed": guarantor_class,
    }


class TestPostCrmReportingClass:
    """The post-guarantee class puts the guaranteed slice under the guarantor."""

    def test_guaranteed_leg_takes_guarantor_class(self) -> None:
        """The __G_ leg of a defaulted obligor reports under the guarantor's class."""
        result = _post_crm(
            [
                _guar_row(
                    ec="corporate_sme",
                    defaulted=True,
                    guaranteed=True,
                    guarantor_class="institution",
                )
            ]
        )
        assert result[0] == "institution"

    def test_retained_leg_keeps_obligor_applied_class(self) -> None:
        """The __REM leg of a defaulted obligor stays defaulted (obligor applied)."""
        result = _post_crm([_guar_row(ec="corporate_sme", defaulted=True, guaranteed=False)])
        assert result[0] == ExposureClass.DEFAULTED.value

    def test_unguaranteed_exposure_uses_applied_class(self) -> None:
        """A plain unguaranteed exposure keeps its applied class."""
        result = _post_crm([_guar_row(ec="corporate", guaranteed=False)])
        assert result[0] == ExposureClass.CORPORATE.value

    def test_guaranteed_leg_missing_guarantor_class_falls_back(self) -> None:
        """A guaranteed leg with no resolved guarantor class falls back to applied."""
        result = _post_crm(
            [_guar_row(ec="corporate_sme", defaulted=True, guaranteed=True, guarantor_class="")]
        )
        assert result[0] == ExposureClass.DEFAULTED.value


# =============================================================================
# COREP C 07.00 bucketing
# =============================================================================


def _sa_results_with_applied() -> pl.LazyFrame:
    """SA rows whose applied class diverges from their origination class."""
    return pl.LazyFrame(
        {
            "exposure_reference": ["SA_CORP_1", "SA_SME_RETAIL", "SA_DEF_1"],
            "approach_applied": ["standardised", "standardised", "standardised"],
            "exposure_class": ["corporate", "corporate_sme", "corporate"],
            "exposure_class_applied": ["corporate", "retail_other", "defaulted"],
            "is_defaulted": [False, False, True],
            "ead_final": [1000.0, 500.0, 800.0],
            "rwa_final": [1000.0, 375.0, 1200.0],
            "risk_weight": [1.00, 0.75, 1.50],
            "counterparty_reference": ["CP_A", "CP_B", "CP_C"],
        }
    )


def _total_ev(sheet: pl.DataFrame) -> float:
    """Total exposure value (row 0010, col 0200) of a C 07.00 sheet."""
    return float(sheet.filter(pl.col("row_ref") == "0010")["0200"][0])


class TestC07BucketsOnAppliedClass:
    """C 07.00 buckets SA rows by exposure_class_applied when present."""

    def test_defaulted_sheet_receives_sa_row(self) -> None:
        """Defaulted SA exposure lands in the 'Exposures in default' sheet."""
        bundle = COREPGenerator().generate_from_lazyframe(_sa_results_with_applied())
        assert "defaulted" in bundle.c07_00
        assert _total_ev(bundle.c07_00["defaulted"]) == pytest.approx(800.0)

    def test_sme_managed_as_retail_lands_in_retail_sheet(self) -> None:
        """SME managed as retail is reported under the Retail sheet."""
        bundle = COREPGenerator().generate_from_lazyframe(_sa_results_with_applied())
        assert "retail_other" in bundle.c07_00
        assert _total_ev(bundle.c07_00["retail_other"]) == pytest.approx(500.0)

    def test_corporate_sheet_excludes_moved_rows(self) -> None:
        """The corporate sheet no longer double-counts the defaulted/retail rows."""
        bundle = COREPGenerator().generate_from_lazyframe(_sa_results_with_applied())
        assert _total_ev(bundle.c07_00["corporate"]) == pytest.approx(1000.0)
