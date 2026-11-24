"""
Integration tests: the CRR Art. 202 double-default provider list, end to end.

The unit tests in ``tests/unit/test_irb_double_default.py`` drive
``apply_guarantee_substitution`` on hand-built frames. No registered portfolio
enables ``CalculationConfig.enable_double_default``, so nothing else shows that
the provider test reads the carriers the real CRM stage produces — the joined
``guarantor_entity_type`` and ``guarantor_exposure_class`` of the guarantor
counterparty. These tests run raw counterparties, ratings and a guarantee
through the real stages.

CRR Art. 202: "An institution may use institutions, investment firms, insurance
and reinsurance undertakings and export credit agencies as eligible providers of
unfunded credit protection which qualify for the treatment set out in Article
153(3) ...". A sovereign is not on that list; a bank is.

Shape: an A-IRB corporate borrower (internal PD 0.5%, own LGD 45%, ~5y), a
1,000,000 GBP loan fully guaranteed by a US counterparty with an internal PD of
0.05% and an external CQS 3. The A-IRB beneficiary routes the guarantor to
parameter substitution (CRR Art. 108(2) / 161(3)), giving the covered leg a
substitution RW well above the double-default RW_obligor x (0.15 + 160 x 0.0005),
so double default is beneficial wherever the provider is eligible.

Pipeline wired: HierarchyResolver -> ExposureClassifier -> CRMProcessor
    -> IRBCalculator. No mocking.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import polars as pl
import pytest

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.data.schemas import FX_RATES_SCHEMA, GUARANTEE_SCHEMA, RATINGS_SCHEMA
from rwa_calc.domain.enums import ApproachType, PermissionMode
from rwa_calc.engine.classify import ExposureClassifier
from rwa_calc.engine.crm.processor import CRMProcessor
from rwa_calc.engine.hierarchy import HierarchyResolver
from rwa_calc.engine.irb.calculator import IRBCalculator
from tests.fixtures.raw_bundle import make_raw_bundle

from .conftest import (
    _rows_to_lazyframe,
    make_counterparty,
    make_loan,
    make_model_permission,
    make_raw_data_bundle,
)

# =============================================================================
# HELPERS
# =============================================================================

_RATING_DATE = date(2024, 6, 1)
_MODEL_ID = "MODEL_01"
_GUARANTOR_PD = 0.0005


def _config(*, enable_double_default: bool) -> CalculationConfig:
    return CalculationConfig.crr(
        reporting_date=date(2024, 12, 31),
        permission_mode=PermissionMode.IRB,
        enable_double_default=enable_double_default,
    )


def _rating(
    counterparty_reference: str, *, pd: float | None = None, cqs: int | None = None
) -> dict[str, Any]:
    internal = pd is not None
    return {
        "rating_reference": f"RAT_{counterparty_reference}_{'int' if internal else 'ext'}",
        "counterparty_reference": counterparty_reference,
        "rating_type": "internal" if internal else "external",
        "rating_agency": "internal" if internal else "S&P",
        "rating_value": "BB" if internal else "BBB",
        "cqs": cqs,
        "pd": pd,
        "rating_date": _RATING_DATE,
        "is_solicited": True,
        "model_id": _MODEL_ID if internal else None,
    }


def _bundle(guarantor_entity_type: str) -> RawDataBundle:
    counterparties = [
        make_counterparty(
            counterparty_reference="BORROWER", entity_type="corporate", country_code="GB"
        ),
        make_counterparty(
            counterparty_reference="GUAR",
            entity_type=guarantor_entity_type,
            country_code="US",
            annual_revenue=0.0,
            total_assets=0.0,
        ),
    ]
    loans = [
        make_loan(
            loan_reference="LN1",
            counterparty_reference="BORROWER",
            currency="GBP",
            drawn_amount=1_000_000.0,
            interest=0.0,
            lgd=0.45,
        )
    ]
    ratings = [
        _rating("BORROWER", pd=0.005),
        _rating("GUAR", pd=_GUARANTOR_PD),
        _rating("GUAR", cqs=3),
    ]
    guarantees = [
        {
            "guarantee_reference": "G1",
            "guarantee_type": "guarantee",
            "guarantor": "GUAR",
            "currency": "GBP",
            "maturity_date": date(2030, 12, 31),
            "amount_covered": 1_000_000.0,
            "percentage_covered": None,
            "beneficiary_type": "loan",
            "beneficiary_reference": "LN1",
            "protection_type": "guarantee",
            "includes_restructuring": True,
        }
    ]
    fx_rates = [
        {"currency_from": "GBP", "currency_to": "GBP", "rate": 1.0},
        {"currency_from": "USD", "currency_to": "GBP", "rate": 0.78},
    ]
    base = make_raw_data_bundle(
        counterparties=counterparties,
        loans=loans,
        model_permissions=[
            make_model_permission(
                model_id=_MODEL_ID, exposure_class="corporate", approach="advanced_irb"
            )
        ],
    )
    return make_raw_bundle(
        facilities=base.facilities,
        loans=base.loans,
        counterparties=base.counterparties,
        facility_mappings=base.facility_mappings,
        lending_mappings=base.lending_mappings,
        org_mappings=base.org_mappings,
        contingents=base.contingents,
        collateral=base.collateral,
        guarantees=_rows_to_lazyframe(guarantees, GUARANTEE_SCHEMA),
        provisions=base.provisions,
        ratings=_rows_to_lazyframe(ratings, RATINGS_SCHEMA),
        specialised_lending=base.specialised_lending,
        equity_exposures=base.equity_exposures,
        fx_rates=_rows_to_lazyframe(fx_rates, FX_RATES_SCHEMA),
        model_permissions=base.model_permissions,
    )


def _guaranteed_leg(guarantor_entity_type: str, *, enable_double_default: bool) -> dict[str, Any]:
    config = _config(enable_double_default=enable_double_default)
    resolved = HierarchyResolver().resolve(_bundle(guarantor_entity_type), config)
    classified = ExposureClassifier().classify(resolved, config)
    crm = CRMProcessor().get_crm_unified_bundle(classified, config)
    irb = IRBCalculator().calculate_branch(
        crm.exposures.filter(
            pl.col("approach").is_in([ApproachType.FIRB.value, ApproachType.AIRB.value])
        ),
        config,
    )
    legs = irb.filter(pl.col("guaranteed_portion") > 0).collect()
    assert legs.height == 1, f"expected one guaranteed leg, got {legs.height}"
    return legs.row(0, named=True)


# =============================================================================
# CASES
# =============================================================================


class TestDoubleDefaultProviderEndToEnd:
    """Which guarantor counterparties reach double default through the real stages."""

    def test_bank_guarantor_takes_double_default(self) -> None:
        """A bank is an Art. 202 provider: DD applies, RW = RW_obligor x (0.15 + 160 x PD_g)."""
        # Arrange / Act
        row = _guaranteed_leg("bank", enable_double_default=True)

        # Assert
        assert row["is_airb"] is True, "the borrower must be A-IRB or DD cannot apply at all"
        assert row["guarantor_entity_type"] == "bank"
        assert row["is_double_default_eligible"] is True
        assert row["guarantee_status"] == "DOUBLE_DEFAULT"
        assert row["double_default_unfunded_protection"] == pytest.approx(1_000_000.0)
        multiplier = 0.15 + 160.0 * _GUARANTOR_PD
        assert row["risk_weight"] == pytest.approx(row["risk_weight_irb_original"] * multiplier)

    @pytest.mark.parametrize("guarantor_entity_type", ["sovereign", "financial_institution"])
    def test_non_art_202_guarantor_is_unaffected_by_enabling_double_default(
        self, guarantor_entity_type: str
    ) -> None:
        """A sovereign or generic financial-institution guarantor gets no double default.

        Enabling the CRR election must leave the covered leg exactly where it is
        with the election off: parameter substitution, its RWA, its EL. Before
        P1.203 both took double default (RW 0.2405 against a substitution RW of
        0.3571 on this shape).
        """
        # Arrange
        without_dd = _guaranteed_leg(guarantor_entity_type, enable_double_default=False)

        # Act
        with_dd = _guaranteed_leg(guarantor_entity_type, enable_double_default=True)

        # Assert
        assert with_dd["guarantor_entity_type"] == guarantor_entity_type
        assert with_dd["is_double_default_eligible"] is False
        assert with_dd["guarantee_status"] == "PD_PARAMETER_SUBSTITUTION"
        assert with_dd["double_default_unfunded_protection"] == pytest.approx(0.0)
        assert with_dd["risk_weight"] > with_dd["risk_weight_irb_original"] * (
            0.15 + 160.0 * _GUARANTOR_PD
        ), "the shape must make DD beneficial, or this test cannot see the provider gate"
        assert with_dd["rwa"] == pytest.approx(without_dd["rwa"], rel=1e-12)
        assert with_dd["expected_loss"] == pytest.approx(without_dd["expected_loss"], rel=1e-12)
