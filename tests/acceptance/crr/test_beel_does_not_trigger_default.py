"""
Acceptance test: a non-zero ``beel`` on a performing exposure must NOT
silently route the row to defaulted treatment.

Background:
    Firms whose A-IRB model pipelines emit a BEEL-style value alongside
    ``lgd`` on every advanced-IRB customer (not just defaulted ones) would
    otherwise see those rows reclassified as defaulted, because Art. 158(5)
    and Art. 181(1)(h)(ii) define BEEL only for defaulted exposures and an
    earlier engine revision (commit f099eff3, shipped in v0.2.10) treated
    ``beel > 0`` as a default trigger.

    The classifier no longer does that. ``is_defaulted`` is derived from
    two explicit signals only:
        is_defaulted = cp_default_status OR row-level is_defaulted
    A contradictory ``(is_defaulted=False ∧ beel>0)`` combination is
    surfaced as a single non-blocking ``DQ008`` warning carrying the
    total offender count, so the input issue is visible without changing
    the calc.

Regulatory References:
    - CRR Art. 178: counterparty / exposure default definition
    - CRR Art. 153(1)(ii) / 154(1)(i): IRB defaulted RW formulas
    - PS1/26 Art. 158(5) / Art. 181(1)(h)(ii): BEEL is A-IRB defaulted-only
"""

from __future__ import annotations

import dataclasses
from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.bundles import (
    ClassifiedExposuresBundle,
    CounterpartyLookup,
    ResolvedHierarchyBundle,
)
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import ApproachType, PermissionMode
from rwa_calc.engine.classifier import ExposureClassifier

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _counterparty_lf(*, counterparty_reference: str, default_status: bool) -> pl.LazyFrame:
    return pl.DataFrame(
        {
            "counterparty_reference": [counterparty_reference],
            "counterparty_name": ["BEEL Test Corp"],
            "entity_type": ["corporate"],
            "country_code": ["GB"],
            "annual_revenue": [200_000_000.0],
            "total_assets": [400_000_000.0],
            "default_status": [default_status],
            "sector_code": ["MANU"],
            "apply_fi_scalar": [False],
            "is_managed_as_retail": [False],
        }
    ).lazy()


def _exposure_lf(
    *,
    exposure_reference: str,
    counterparty_reference: str,
    is_defaulted: bool,
    beel: float,
    lgd: float = 0.45,
) -> pl.LazyFrame:
    """Single AIRB-eligible corporate exposure with explicit default + BEEL columns."""
    return pl.DataFrame(
        {
            "exposure_reference": [exposure_reference],
            "exposure_type": ["loan"],
            "product_type": ["TERM_LOAN"],
            "book_code": ["CORP"],
            "counterparty_reference": [counterparty_reference],
            "value_date": [date(2025, 1, 1)],
            "maturity_date": [date(2028, 1, 1)],
            "currency": ["GBP"],
            "drawn_amount": [1_000_000.0],
            "undrawn_amount": [0.0],
            "nominal_amount": [0.0],
            "lgd": [lgd],
            "beel": [beel],
            "is_defaulted": [is_defaulted],
            "internal_pd": [0.02],
            "model_id": ["CORP-AIRB-V1"],
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
            "residential_collateral_value": [0.0],
            "exposure_for_retail_threshold": [1_000_000.0],
            "lending_group_adjusted_exposure": [0.0],
        }
    ).lazy()


def _model_permissions_lf() -> pl.LazyFrame:
    return pl.DataFrame(
        {
            "model_id": ["CORP-AIRB-V1"],
            "exposure_class": ["corporate"],
            "approach": ["advanced_irb"],
            "country_codes": [None],
            "excluded_book_codes": [None],
        },
        schema={
            "model_id": pl.String,
            "exposure_class": pl.String,
            "approach": pl.String,
            "country_codes": pl.String,
            "excluded_book_codes": pl.String,
        },
    ).lazy()


def _build_bundle(
    *,
    exposures: pl.LazyFrame,
    counterparties: pl.LazyFrame,
    model_permissions: pl.LazyFrame | None,
) -> ResolvedHierarchyBundle:
    enriched_cp = counterparties.with_columns(
        [
            pl.lit(False).alias("counterparty_has_parent"),
            pl.lit(None).cast(pl.String).alias("parent_counterparty_reference"),
            pl.lit(None).cast(pl.String).alias("ultimate_parent_reference"),
            pl.lit(0).cast(pl.Int32).alias("counterparty_hierarchy_depth"),
            pl.lit(None).cast(pl.Int8).alias("cqs"),
        ]
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
        model_permissions=model_permissions,
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


@pytest.fixture
def crr_irb_config() -> CalculationConfig:
    return CalculationConfig.crr(
        reporting_date=date(2026, 1, 1),
        permission_mode=PermissionMode.IRB,
    )


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------


class TestBEELDoesNotTriggerDefault:
    """Per-scenario assertions on the classifier's defaulted-derivation behaviour."""

    def test_airb_performing_with_beel_routes_performing_and_warns(
        self,
        crr_irb_config: CalculationConfig,
    ) -> None:
        """A-IRB performing row with beel>0 → not defaulted, one aggregate DQ008.

        Mirrors the user's reported scenario: their A-IRB model team
        populates ``beel`` alongside ``lgd`` for every advanced-IRB
        customer. The engine must keep the row on the performing A-IRB
        path and emit a single aggregate DQ008 warning whose message
        carries the count of offending rows.
        """
        exposures = _exposure_lf(
            exposure_reference="EXP_AIRB_PERF",
            counterparty_reference="CP_PERF",
            is_defaulted=False,
            beel=0.10,
        )
        bundle = _build_bundle(
            exposures=exposures,
            counterparties=_counterparty_lf(counterparty_reference="CP_PERF", default_status=False),
            model_permissions=_model_permissions_lf(),
        )

        result = ExposureClassifier().classify(bundle, crr_irb_config)

        df = result.all_exposures.collect()
        assert df["is_defaulted"][0] is False
        assert df["approach"][0] == ApproachType.AIRB.value
        dq008 = [e for e in result.classification_errors if e.code == "DQ008"]
        assert len(dq008) == 1
        warning = dq008[0]
        assert "1 non-defaulted exposure" in warning.message
        assert warning.regulatory_reference == "PS1/26 Art. 181(1)(h)(ii); CRR Art. 158(5)"
        assert warning.field_name == "beel"

    def test_cp_defaulted_with_beel_routes_defaulted_no_warning(
        self,
        crr_irb_config: CalculationConfig,
    ) -> None:
        """cp_default_status=True + beel>0 → defaulted (BEEL legitimately consumed)."""
        exposures = _exposure_lf(
            exposure_reference="EXP_CP_DEF",
            counterparty_reference="CP_DEF",
            is_defaulted=False,
            beel=0.10,
        )
        bundle = _build_bundle(
            exposures=exposures,
            counterparties=_counterparty_lf(counterparty_reference="CP_DEF", default_status=True),
            model_permissions=_model_permissions_lf(),
        )

        result = ExposureClassifier().classify(bundle, crr_irb_config)

        df = result.all_exposures.collect()
        assert df["is_defaulted"][0] is True
        assert not any(e.code == "DQ008" for e in result.classification_errors)

    def test_row_default_flag_with_zero_beel_no_warning(
        self,
        crr_irb_config: CalculationConfig,
    ) -> None:
        """row-level is_defaulted=True with beel=0 → defaulted, no DQ008."""
        exposures = _exposure_lf(
            exposure_reference="EXP_ROW_DEF",
            counterparty_reference="CP_PERF",
            is_defaulted=True,
            beel=0.0,
        )
        bundle = _build_bundle(
            exposures=exposures,
            counterparties=_counterparty_lf(counterparty_reference="CP_PERF", default_status=False),
            model_permissions=_model_permissions_lf(),
        )

        result = ExposureClassifier().classify(bundle, crr_irb_config)

        df = result.all_exposures.collect()
        assert df["is_defaulted"][0] is True
        assert not any(e.code == "DQ008" for e in result.classification_errors)

    def test_bundle_typing(self) -> None:
        """Smoke check that the test setup produces a ClassifiedExposuresBundle."""
        # Sanity guard: if ClassifiedExposuresBundle is renamed, the module
        # import fails to collect; if it stops being a frozen dataclass bundle,
        # this assertion surfaces the contract drift instead of the more
        # involved scenarios.
        assert isinstance(ClassifiedExposuresBundle, type)
        assert dataclasses.is_dataclass(ClassifiedExposuresBundle)
