"""
P1.273 — CRR Art. 199(7) with Art. 211: lease exposures treated as collateralised.

Where the Art. 211 conditions are met, an exposure arising from a leasing
transaction "may be treated in the same manner as loans collateralised by the
type of property leased" (CRR Art. 199(7); PRA PS1/26 Art. 199(7), both retaining
Art. 211). The leased asset is supplied as an ordinary non-financial collateral
row (``other_physical`` for equipment/plant, ``real_estate`` for property leases)
pledged to the lease exposure, and the lessor attests the lease-specific Art. 211
conditions via ``is_lease_collateral_attested``. That attestation is an
INDEPENDENT recognition route through the FIRB Foundation Collateral Method: it
subsumes Art. 211(a) (the Art. 208/210 property-eligibility that
``is_eligible_irb_collateral`` otherwise attests), so a lessor row needs neither
the general IRB flag nor a separate lease marker.

Without the attestation (null/False and no general IRB flag) the leased asset is
not recognised — the Art. 199(2)/(5)/(6) FCM gate zeroes ``effectively_secured``
and the secured LGD reverts to the unsecured supervisory value (45% CRR / 40%
B31 for a senior corporate non-FSE), i.e. the pre-P1.273 conservative behaviour.

Pipeline position:
    tests/unit — direct CRMProcessor.get_crm_unified_bundle drive.

References:
    - CRR Art. 199(7): lease exposures treated as collateralised per Art. 211.
    - CRR Art. 211: requirements for treating lease exposures as collateralised.
    - CRR Art. 230: F-IRB Foundation Collateral Method / OC ratios.
    - CRR Art. 161(1)(a): LGDU senior unsecured corporate = 45%.
    - PS1/26 Art. 161(1)(aa): LGDU senior unsecured non-FSE corporate = 40%.
    - IMPLEMENTATION_PLAN.md: P1.273.
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest
from tests.fixtures.resolved_bundle import make_classified_bundle
from tests.unit.crm._crm_bundles import normalise_collateral, with_ancestor_facilities

from rwa_calc.contracts.bundles import (
    ClassifiedExposuresBundle,
    CRMAdjustedBundle,
    create_empty_counterparty_lookup,
)
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.contracts.errors import ERROR_INELIGIBLE_IRB_COLLATERAL
from rwa_calc.domain.enums import ApproachType, ExposureClass, PermissionMode
from rwa_calc.engine.crm.processor import CRMProcessor

# =============================================================================
# Constants
# =============================================================================

CRR_LGDU_SENIOR: float = 0.45  # CRR Art. 161(1)(a) senior unsecured corporate
B31_LGDU_SENIOR: float = 0.40  # PS1/26 Art. 161(1)(aa) senior unsecured non-FSE
# CRR other_physical FCM hand-calc (£10m exposure, £10m leased asset):
#   Art. 230(2) other-physical FCM haircut 40% -> £6m; OC=1.4× ->
#   effectively_secured = 6m/1.4 = £4.285714m; unsecured = £5.714286m;
#   LGD* = (0.40·4.285714m + 0.45·5.714286m)/10m = 0.428571 (LGDS 40%, LGDU 45%).
CRR_SECURED_LGD_OTHER_PHYSICAL: float = 0.428571

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def processor() -> CRMProcessor:
    return CRMProcessor()


@pytest.fixture
def firb_crr_config() -> CalculationConfig:
    return CalculationConfig.crr(
        reporting_date=date(2024, 12, 31),
        permission_mode=PermissionMode.IRB,
    )


@pytest.fixture
def firb_b31_config() -> CalculationConfig:
    return CalculationConfig.basel_3_1(
        reporting_date=date(2030, 6, 30),
        permission_mode=PermissionMode.IRB,
    )


# =============================================================================
# Helpers
# =============================================================================


def _create_bundle(
    collateral_type: str,
    *,
    is_eligible_irb_collateral: bool,
    is_lease_collateral_attested: bool | None,
    original_maturity_years: float = 7.0,
) -> ClassifiedExposuresBundle:
    """Build a single F-IRB lessor bundle with one leased-asset collateral row.

    £10m senior corporate lease exposure, £10m leased asset of
    ``collateral_type``. The Art. 211 attestation (``is_lease_collateral_attested``)
    and the general IRB flag (``is_eligible_irb_collateral``) drive the recognition
    route under test.
    """
    exposures = pl.DataFrame(
        {
            "exposure_reference": ["EXP1"],
            "counterparty_reference": ["CP1"],
            "parent_facility_reference": [None],
            "exposure_class": [ExposureClass.CORPORATE.value],
            "approach": [ApproachType.FIRB.value],
            "drawn_amount": [10_000_000.0],
            "ead_gross": [10_000_000.0],
            "lgd": [None],
            "pd": [0.02],
            "maturity_date": [date(2029, 12, 31)],
            "currency": ["GBP"],
            "seniority": ["senior"],
            "exposure_type": ["loan"],
            "nominal_amount": [0.0],
            "interest": [0.0],
            "undrawn_amount": [0.0],
            "risk_type": [None],
            "ccf_modelled": [None],
            "is_short_term_trade_lc": [False],
            "product_type": ["TERM_LOAN"],
            "value_date": [date(2024, 1, 1)],
            "book_code": ["BOOK1"],
            "is_sft": [False],
        }
    ).lazy()
    exposures = exposures.with_columns(pl.col("parent_facility_reference").cast(pl.String))
    exposures = with_ancestor_facilities(exposures)

    collateral = normalise_collateral(
        pl.DataFrame(
            {
                "collateral_reference": ["LEASE1"],
                "collateral_type": [collateral_type],
                "currency": ["GBP"],
                "market_value": [10_000_000.0],
                "value_after_maturity_adj": [10_000_000.0],
                "beneficiary_type": ["loan"],
                "beneficiary_reference": ["EXP1"],
                "maturity_date": [date(2035, 12, 31)],
                "issuer_type": [""],
                "issuer_cqs": [1],
                "is_main_index": [False],
                "is_eligible_financial_collateral": [False],
                "is_eligible_irb_collateral": [is_eligible_irb_collateral],
                "is_lease_collateral_attested": [is_lease_collateral_attested],
                "residual_maturity_years": [10.0],
                # Original lease term (a finance lease intrinsically has one).
                "original_maturity_years": [original_maturity_years],
                "liquidation_period_days": [10],
            },
            schema_overrides={
                "is_lease_collateral_attested": pl.Boolean,
                "original_maturity_years": pl.Float64,
            },
        ).lazy()
    )

    return make_classified_bundle(
        all_exposures=exposures,
        equity_exposures=None,
        collateral=collateral,
        guarantees=None,
        provisions=None,
        counterparty_lookup=create_empty_counterparty_lookup(),
        classification_audit=None,
        classification_errors=[],
    )


def _run(
    processor: CRMProcessor,
    config: CalculationConfig,
    bundle: ClassifiedExposuresBundle,
) -> CRMAdjustedBundle:
    return processor.get_crm_unified_bundle(bundle, config)


def _lgd_post_crm(result: CRMAdjustedBundle) -> float:
    row = result.exposures.collect().filter(pl.col("exposure_reference") == "EXP1")
    return row["lgd_post_crm"][0]


def _crm014_errors(result: CRMAdjustedBundle) -> list:
    return [e for e in result.crm_errors if e.code == ERROR_INELIGIBLE_IRB_COLLATERAL]


# =============================================================================
# Tests: Art. 211 lease attestation recognises the leased asset
# =============================================================================


class TestLeaseAttestationRecognised:
    """Art. 199(7)/211: an attested leased asset reduces F-IRB LGD via the FCM."""

    def test_lease_attested_other_physical_reduces_lgd_crr(
        self, processor: CRMProcessor, firb_crr_config: CalculationConfig
    ) -> None:
        """CRR: a lease-attested other-physical asset is recognised — LGD* < LGDU.

        The general IRB flag is False: recognition comes SOLELY from the Art. 211
        lease attestation, proving it is an independent route. LGD* = 0.428571
        (Art. 230(2) haircut 40%, OC=1.4×, LGDS other_physical = 40%, LGDU = 45%).
        """
        bundle = _create_bundle(
            "other_physical",
            is_eligible_irb_collateral=False,
            is_lease_collateral_attested=True,
        )

        result = _run(processor, firb_crr_config, bundle)

        lgd = _lgd_post_crm(result)
        assert lgd == pytest.approx(CRR_SECURED_LGD_OTHER_PHYSICAL, abs=1e-3)
        assert lgd < CRR_LGDU_SENIOR

    def test_lease_attested_emits_no_warning_crr(
        self, processor: CRMProcessor, firb_crr_config: CalculationConfig
    ) -> None:
        """A lease-attested leased asset is eligible, so no CRM014 warning fires."""
        bundle = _create_bundle(
            "other_physical",
            is_eligible_irb_collateral=False,
            is_lease_collateral_attested=True,
        )

        result = _run(processor, firb_crr_config, bundle)

        assert _crm014_errors(result) == []

    def test_lease_attested_other_physical_reduces_lgd_b31(
        self, processor: CRMProcessor, firb_b31_config: CalculationConfig
    ) -> None:
        """B31: a lease-attested other-physical asset is recognised — LGD < LGDU (40%)."""
        bundle = _create_bundle(
            "other_physical",
            is_eligible_irb_collateral=False,
            is_lease_collateral_attested=True,
        )

        result = _run(processor, firb_b31_config, bundle)

        assert _lgd_post_crm(result) < B31_LGDU_SENIOR

    def test_lease_attested_real_estate_reduces_lgd_crr(
        self, processor: CRMProcessor, firb_crr_config: CalculationConfig
    ) -> None:
        """CRR: a property lease (real_estate leased asset) is likewise recognised."""
        bundle = _create_bundle(
            "real_estate",
            is_eligible_irb_collateral=False,
            is_lease_collateral_attested=True,
        )

        result = _run(processor, firb_crr_config, bundle)

        assert _lgd_post_crm(result) < CRR_LGDU_SENIOR


# =============================================================================
# Tests: without the attestation the pre-P1.273 conservative behaviour holds
# =============================================================================


class TestNoLeaseAttestationConservative:
    """No Art. 211 attestation (and no general IRB flag) -> unsecured LGD."""

    def test_unattested_lease_reverts_to_lgdu_crr(
        self, processor: CRMProcessor, firb_crr_config: CalculationConfig
    ) -> None:
        """LOAD-BEARING: with neither flag the leased asset is not recognised.

        The Art. 199 FCM gate zeroes effectively_secured and LGD reverts to the
        senior unsecured supervisory value (45%) — the conservative pre-P1.273
        lessor treatment.
        """
        bundle = _create_bundle(
            "other_physical",
            is_eligible_irb_collateral=False,
            is_lease_collateral_attested=None,
        )

        result = _run(processor, firb_crr_config, bundle)

        assert _lgd_post_crm(result) == pytest.approx(CRR_LGDU_SENIOR, abs=1e-6)

    def test_unattested_lease_emits_crm014(
        self, processor: CRMProcessor, firb_crr_config: CalculationConfig
    ) -> None:
        """Unattested leased asset accumulates exactly one CRM014 warning."""
        bundle = _create_bundle(
            "other_physical",
            is_eligible_irb_collateral=False,
            is_lease_collateral_attested=None,
        )

        result = _run(processor, firb_crr_config, bundle)

        warnings = _crm014_errors(result)
        assert len(warnings) == 1
        assert warnings[0].exposure_reference == "EXP1"

    def test_attestation_alone_changes_outcome_crr(
        self, processor: CRMProcessor, firb_crr_config: CalculationConfig
    ) -> None:
        """The lease attestation alone must move LGD (guards against a no-op route)."""
        attested = _lgd_post_crm(
            _run(
                processor,
                firb_crr_config,
                _create_bundle(
                    "other_physical",
                    is_eligible_irb_collateral=False,
                    is_lease_collateral_attested=True,
                ),
            )
        )
        unattested = _lgd_post_crm(
            _run(
                processor,
                firb_crr_config,
                _create_bundle(
                    "other_physical",
                    is_eligible_irb_collateral=False,
                    is_lease_collateral_attested=None,
                ),
            )
        )
        assert attested < unattested


# =============================================================================
# Tests: backward compatibility — general IRB route unaffected
# =============================================================================


class TestGeneralIrbRouteUnaffected:
    """The pre-existing is_eligible_irb_collateral route is not disturbed."""

    def test_general_irb_flag_still_recognises_without_lease_attestation(
        self, processor: CRMProcessor, firb_crr_config: CalculationConfig
    ) -> None:
        """A pledged (non-lease) asset with the general flag but null lease flag is recognised."""
        bundle = _create_bundle(
            "other_physical",
            is_eligible_irb_collateral=True,
            is_lease_collateral_attested=None,
        )

        result = _run(processor, firb_crr_config, bundle)

        assert _lgd_post_crm(result) < CRR_LGDU_SENIOR
        assert _crm014_errors(result) == []


# =============================================================================
# Tests: the lease route is scoped to leased PROPERTY (Art. 211 -> Art. 208/210)
# =============================================================================


class TestLeaseRouteScopedToProperty:
    """Art. 211 concerns leased property: the route is real_estate / other_physical only."""

    def test_lease_attested_receivables_not_recognised_crr(
        self, processor: CRMProcessor, firb_crr_config: CalculationConfig
    ) -> None:
        """LOAD-BEARING: a lease-attested receivables row gains NO eligibility via the lease route.

        Art. 211(a) routes to Art. 208 (immovable property) / 210 (other physical) —
        receivables are neither. A short (<=1y) receivable so the Art. 199(5)
        maturity cap cannot mask the category guard: with only the lease flag set it
        must still revert to LGDU and raise one CRM014 (it needs its own
        is_eligible_irb_collateral to be recognised).
        """
        bundle = _create_bundle(
            "receivables",
            is_eligible_irb_collateral=False,
            is_lease_collateral_attested=True,
            original_maturity_years=0.5,
        )

        result = _run(processor, firb_crr_config, bundle)

        assert _lgd_post_crm(result) == pytest.approx(CRR_LGDU_SENIOR, abs=1e-6)
        assert len(_crm014_errors(result)) == 1

    def test_general_flag_still_recognises_receivables_crr(
        self, processor: CRMProcessor, firb_crr_config: CalculationConfig
    ) -> None:
        """Control: a short receivable with the general IRB flag is still recognised."""
        bundle = _create_bundle(
            "receivables",
            is_eligible_irb_collateral=True,
            is_lease_collateral_attested=None,
            original_maturity_years=0.5,
        )

        result = _run(processor, firb_crr_config, bundle)

        assert _lgd_post_crm(result) < CRR_LGDU_SENIOR
        assert _crm014_errors(result) == []
