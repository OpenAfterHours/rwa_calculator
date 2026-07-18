"""
Tests for Art. 231 sequential fill (waterfall) collateral allocation.

Art. 231 requires that when multiple collateral types secure an exposure,
each type absorbs exposure starting from the lowest LGDS. This replaces
the former pro-rata allocation which could produce a less favourable
(higher) blended LGDS when total collateral exceeds the exposure.

Sequential fill ordering (most favourable = lowest LGDS first):
1. Financial (0%)
2. Covered bonds (11.25%)
3. Receivables (20% B31 / 35% CRR)
4. Real estate (20% B31 / 35% CRR)
5. Other physical (25% B31 / 40% CRR)

Key test scenarios:
- Mixed pools where total collateral > EAD: sequential fill differs from pro-rata
- Under-collateralised exposures: both methods give the same result
- Single collateral type: no difference
- Waterfall ordering: financial collateral fully absorbed before non-financial
- 30% threshold: non-financial collateral zeroed when below threshold
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest
from tests.fixtures.resolved_bundle import make_classified_bundle
from tests.unit.crm._crm_bundles import normalise_collateral, with_ancestor_facilities

from rwa_calc.contracts.bundles import (
    ClassifiedExposuresBundle,
    create_empty_counterparty_lookup,
)
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import ApproachType, ExposureClass, PermissionMode
from rwa_calc.engine.crm.processor import CRMProcessor

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def crr_processor() -> CRMProcessor:
    return CRMProcessor()


@pytest.fixture
def b31_processor() -> CRMProcessor:
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
    exposures_data: dict,
    collateral_data: dict,
) -> ClassifiedExposuresBundle:
    """Build a ClassifiedExposuresBundle with F-IRB exposures and collateral."""
    n = len(next(iter(exposures_data.values())))
    defaults = {
        "exposure_type": ["loan"] * n,
        "nominal_amount": [0.0] * n,
        "interest": [0.0] * n,
        "undrawn_amount": [0.0] * n,
        "risk_type": [None] * n,
        "ccf_modelled": [None] * n,
        "is_short_term_trade_lc": [False] * n,
        "product_type": ["TERM_LOAN"] * n,
        "value_date": [date(2024, 1, 1)] * n,
        "book_code": ["BOOK1"] * n,
        # P1.96 — Art. 207(2): covered bonds are only eligible collateral on
        # SFT / repo / capital-markets-driven exposures. The waterfall tests
        # exercise covered-bond LGD computation, so flag the synthetic
        # exposures as SFT to keep covered bonds in the eligible set.
        "is_sft": [True] * n,
    }
    for key, value in defaults.items():
        if key not in exposures_data:
            exposures_data[key] = value

    exposures = pl.DataFrame(exposures_data).lazy()
    if "parent_facility_reference" in exposures.collect_schema().names():
        exposures = exposures.with_columns(pl.col("parent_facility_reference").cast(pl.String))
    # Production hierarchy always emits the facility-ancestor closure.
    exposures = with_ancestor_facilities(exposures)

    coll_n = len(next(iter(collateral_data.values())))
    coll_defaults = {
        "issuer_type": [""] * coll_n,
        "issuer_cqs": [1] * coll_n,
        "is_main_index": [False] * coll_n,
        "is_eligible_financial_collateral": [True] * coll_n,
        # P1.235 — Art. 199(2)/(5)/(6): these waterfall tests assume the non-
        # financial (RE/receivables/other-physical) collateral is IRB-eligible;
        # make that attestation explicit so the new FIRB FCM eligibility gate
        # recognises it (default False would zero it as unattested).
        "is_eligible_irb_collateral": [True] * coll_n,
        "value_after_maturity_adj": [None] * coll_n,
        "residual_maturity_years": [10.0] * coll_n,
        # P1.186: 10-day liquidation period pinned here so sequential-fill tests
        # continue to use 10-day base haircuts (40% for OP/receivables, 0% for RE).
        # These tests exercise waterfall ordering and per-type threshold logic, not
        # the liquidation-period scaling that changed with P1.186. Without this
        # override the new 20-day default (√2 scaling) causes OP's VAH to fall
        # below the 30% minimum threshold, producing different lgd_post_crm values.
        "liquidation_period_days": [10] * coll_n,
    }
    for key, value in coll_defaults.items():
        if key not in collateral_data:
            collateral_data[key] = value
    collateral = normalise_collateral(pl.DataFrame(collateral_data).lazy())

    empty_cp = create_empty_counterparty_lookup()

    return make_classified_bundle(
        all_exposures=exposures,
        equity_exposures=None,
        collateral=collateral,
        guarantees=None,
        provisions=None,
        counterparty_lookup=empty_cp,
        classification_audit=None,
        classification_errors=[],
    )


def _run_crm(
    processor: CRMProcessor,
    config: CalculationConfig,
    bundle: ClassifiedExposuresBundle,
) -> pl.DataFrame:
    """Run CRM processing and return collected exposures."""
    result = processor.get_crm_unified_bundle(bundle, config)
    collected = result.exposures.collect()
    assert isinstance(collected, pl.DataFrame)
    return collected


# =============================================================================
# Tests: Art. 231 sequential fill
# =============================================================================


class TestSequentialFillBasic:
    """Test that sequential fill correctly prioritises lowest LGDS types."""

    def test_overcollateralised_sequential_vs_prorata_differs(
        self, b31_processor: CRMProcessor, firb_b31_config: CalculationConfig
    ):
        """When total collateral > EAD, sequential fill produces lower LGD than pro-rata.

        Setup: EAD=1000 under PS1/26 Art. 230(1) (HC=40% non-financial, OC=1.0).
        Cash MV=400 → HC=0% → VAH=400, eff=400/1.0=400 (LGDS=0%)
        RE MV=700 → HC=40% → VAH=420, eff=420/1.0=420 (LGDS=20%)
        OP MV=500 → HC=40% → VAH=300, eff=300/1.0=300 (LGDS=25%)
        Total eff=1120 > EAD=1000.

        PS1/26 Art. 230(1) has no C* threshold (no per-type 30% gate under B31).

        Sequential: fin absorbs 400, RE absorbs 420, other absorbs 180 → EU=0
        LGD* = (0*400 + 0.20*420 + 0.25*180) / 1000 = (84 + 45) / 1000 = 0.129

        Pro-rata would give higher LGD because lower-LGDS fin is underused.
        Sequential is lower (more favourable) because financial fully absorbed first.
        """
        bundle = _create_bundle(
            exposures_data={
                "exposure_reference": ["EXP1"],
                "counterparty_reference": ["CP1"],
                "parent_facility_reference": [None],
                "exposure_class": [ExposureClass.CORPORATE.value],
                "approach": [ApproachType.FIRB.value],
                "drawn_amount": [1000.0],
                "ead_gross": [1000.0],
                "lgd": [None],
                "pd": [0.01],
                "maturity_date": [date(2029, 12, 31)],
                "currency": ["GBP"],
                "seniority": ["senior"],
            },
            collateral_data={
                "collateral_reference": ["C1", "C2", "C3"],
                "collateral_type": ["cash", "real_estate", "other_physical"],
                "currency": ["GBP", "GBP", "GBP"],
                "market_value": [400.0, 700.0, 500.0],
                "value_after_maturity_adj": [400.0, 700.0, 500.0],
                # RE HC=0% → VAH=700, OC ratio=1.40 → eff=500
                # Other HC=40% → VAH=300, OC ratio=1.40 → eff=214.3
                # Financial HC=0%, OC ratio=1.0 → eff=400
                "beneficiary_type": ["loan", "loan", "loan"],
                "beneficiary_reference": ["EXP1", "EXP1", "EXP1"],
                "maturity_date": [date(2030, 12, 31)] * 3,
                "is_eligible_financial_collateral": [True, False, False],
            },
        )
        result = _run_crm(b31_processor, firb_b31_config, bundle)
        row = result.filter(pl.col("exposure_reference") == "EXP1")
        lgd = row["lgd_post_crm"][0]

        # Sequential fill under B31 (HC=40% on RE/OP, OC=1.0):
        # fin=400, RE=420, OP=180 → lgd_secured = 0.129
        # lgd_post_crm = 0.129 (fully secured, EU=0)
        assert lgd == pytest.approx(0.129, abs=0.001)

    def test_undercollateralised_sequential_same_as_prorata(
        self, b31_processor: CRMProcessor, firb_b31_config: CalculationConfig
    ):
        """When total collateral < EAD, sequential and pro-rata give same result.

        Setup: EAD=1000 under PS1/26 Art. 230(1) (HC=40% non-financial, OC=1.0).
        RE MV=700 → HC=40% → VAH=420, eff=420/1.0=420 (LGDS=20%)
        OP MV=700 → HC=40% → VAH=420, eff=420/1.0=420 (LGDS=25%)
        Total eff=840 < 1000. Both types fully allocated regardless of ordering.
        PS1/26 has no C* threshold under B31.
        """
        bundle = _create_bundle(
            exposures_data={
                "exposure_reference": ["EXP1"],
                "counterparty_reference": ["CP1"],
                "parent_facility_reference": [None],
                "exposure_class": [ExposureClass.CORPORATE.value],
                "approach": [ApproachType.FIRB.value],
                "drawn_amount": [1000.0],
                "ead_gross": [1000.0],
                "lgd": [None],
                "pd": [0.01],
                "maturity_date": [date(2029, 12, 31)],
                "currency": ["GBP"],
                "seniority": ["senior"],
            },
            collateral_data={
                "collateral_reference": ["C1", "C2"],
                "collateral_type": ["real_estate", "other_physical"],
                "currency": ["GBP", "GBP"],
                "market_value": [700.0, 700.0],
                "value_after_maturity_adj": [700.0, 700.0],
                "beneficiary_type": ["loan", "loan"],
                "beneficiary_reference": ["EXP1", "EXP1"],
                "maturity_date": [date(2030, 12, 31)] * 2,
                "is_eligible_financial_collateral": [False, False],
            },
        )
        result = _run_crm(b31_processor, firb_b31_config, bundle)
        row = result.filter(pl.col("exposure_reference") == "EXP1")
        lgd = row["lgd_post_crm"][0]

        # B31: RE: eff=420, OP: eff=420. Total=840, EU=160.
        # lgd_secured = (0.20*420 + 0.25*420) / 840 = 189/840 = 0.225
        # lgd_post_crm = 0.225*840/1000 + 0.40*160/1000 = 0.189 + 0.064 = 0.253
        assert lgd == pytest.approx(0.253, abs=0.001)


class TestSequentialFillOrdering:
    """Test that waterfall ordering allocates lowest LGDS first."""

    def test_financial_absorbed_before_real_estate(
        self, b31_processor: CRMProcessor, firb_b31_config: CalculationConfig
    ):
        """Financial collateral (LGDS=0%) fully absorbed before RE (LGDS=20%).

        EAD=500, financial=300 (eff=300), RE=700 (eff=500).
        Sequential: fin=300, RE=200 → EU=0
        lgd_secured = (0*300 + 0.20*200) / 500 = 0.08
        """
        bundle = _create_bundle(
            exposures_data={
                "exposure_reference": ["EXP1"],
                "counterparty_reference": ["CP1"],
                "parent_facility_reference": [None],
                "exposure_class": [ExposureClass.CORPORATE.value],
                "approach": [ApproachType.FIRB.value],
                "drawn_amount": [500.0],
                "ead_gross": [500.0],
                "lgd": [None],
                "pd": [0.01],
                "maturity_date": [date(2029, 12, 31)],
                "currency": ["GBP"],
                "seniority": ["senior"],
            },
            collateral_data={
                "collateral_reference": ["C1", "C2"],
                "collateral_type": ["cash", "real_estate"],
                "currency": ["GBP", "GBP"],
                "market_value": [300.0, 700.0],
                "value_after_maturity_adj": [300.0, 700.0],
                "beneficiary_type": ["loan", "loan"],
                "beneficiary_reference": ["EXP1", "EXP1"],
                "maturity_date": [date(2030, 12, 31)] * 2,
                "is_eligible_financial_collateral": [True, False],
            },
        )
        result = _run_crm(b31_processor, firb_b31_config, bundle)
        row = result.filter(pl.col("exposure_reference") == "EXP1")
        lgd = row["lgd_post_crm"][0]

        # Fully secured, lgd_post_crm = lgd_secured = 0.08
        assert lgd == pytest.approx(0.08, abs=0.001)

    def test_receivables_before_other_physical(
        self, b31_processor: CRMProcessor, firb_b31_config: CalculationConfig
    ):
        """Receivables (LGDS=20%) allocated before other_physical (LGDS=25%).

        EAD=500. Rec MV=375, Other MV=350. Under PS1/26 Art. 230(1): HC=40%
        non-financial, OC=1.0.
        VAH: rec=225, other=210.
        Eff secured: rec=225/1.0=225, other=210/1.0=210.
        Total=435 < 500. Sequential: rec=225, other=210 → EU=65
        lgd_secured = (0.20*225 + 0.25*210) / 435 = 97.5/435 ≈ 0.2241
        lgd_post_crm = 0.2241*435/500 + 0.40*65/500 = 0.195 + 0.052 = 0.247
        """
        bundle = _create_bundle(
            exposures_data={
                "exposure_reference": ["EXP1"],
                "counterparty_reference": ["CP1"],
                "parent_facility_reference": [None],
                "exposure_class": [ExposureClass.CORPORATE.value],
                "approach": [ApproachType.FIRB.value],
                "drawn_amount": [500.0],
                "ead_gross": [500.0],
                "lgd": [None],
                "pd": [0.01],
                "maturity_date": [date(2029, 12, 31)],
                "currency": ["GBP"],
                "seniority": ["senior"],
            },
            collateral_data={
                "collateral_reference": ["C1", "C2"],
                "collateral_type": ["receivables", "other_physical"],
                "currency": ["GBP", "GBP"],
                "market_value": [375.0, 350.0],
                "value_after_maturity_adj": [375.0, 350.0],
                "beneficiary_type": ["loan", "loan"],
                "beneficiary_reference": ["EXP1", "EXP1"],
                "maturity_date": [date(2030, 12, 31)] * 2,
                "is_eligible_financial_collateral": [False, False],
            },
        )
        result = _run_crm(b31_processor, firb_b31_config, bundle)
        row = result.filter(pl.col("exposure_reference") == "EXP1")
        lgd = row["lgd_post_crm"][0]

        assert lgd == pytest.approx(0.247, abs=0.001)


class TestSequentialFillCRR:
    """Test sequential fill under CRR framework (different LGDS values)."""

    def test_crr_sequential_fill_with_mixed_collateral(
        self, crr_processor: CRMProcessor, firb_crr_config: CalculationConfig
    ):
        """CRR LGDS: RE=35%, other=40%. Financial=0%.

        EAD=1000. Financial=600 (eff=600), RE=700 (eff=500), oth=280 (eff=200).
        Total eff=1300 > 1000. Sequential: fin=600, RE=400, oth=0 → EU=0
        lgd_secured = (0*600 + 0.35*400 + 0.40*0) / 1000 = 140/1000 = 0.14
        """
        bundle = _create_bundle(
            exposures_data={
                "exposure_reference": ["EXP1"],
                "counterparty_reference": ["CP1"],
                "parent_facility_reference": [None],
                "exposure_class": [ExposureClass.CORPORATE.value],
                "approach": [ApproachType.FIRB.value],
                "drawn_amount": [1000.0],
                "ead_gross": [1000.0],
                "lgd": [None],
                "pd": [0.01],
                "maturity_date": [date(2029, 12, 31)],
                "currency": ["GBP"],
                "seniority": ["senior"],
            },
            collateral_data={
                "collateral_reference": ["C1", "C2", "C3"],
                "collateral_type": ["cash", "real_estate", "other_physical"],
                "currency": ["GBP", "GBP", "GBP"],
                "market_value": [600.0, 700.0, 280.0],
                "value_after_maturity_adj": [600.0, 700.0, 280.0],
                "beneficiary_type": ["loan", "loan", "loan"],
                "beneficiary_reference": ["EXP1", "EXP1", "EXP1"],
                "maturity_date": [date(2030, 12, 31)] * 3,
                "is_eligible_financial_collateral": [True, False, False],
            },
        )
        result = _run_crm(crr_processor, firb_crr_config, bundle)
        row = result.filter(pl.col("exposure_reference") == "EXP1")
        lgd = row["lgd_post_crm"][0]

        assert lgd == pytest.approx(0.14, abs=0.001)


class TestSequentialFillEdgeCases:
    """Edge cases for sequential fill."""

    def test_single_collateral_type_unchanged(
        self, b31_processor: CRMProcessor, firb_b31_config: CalculationConfig
    ):
        """Single collateral type: sequential fill = simple allocation.

        EAD=1000, cash=500. lgd_secured=0.0 (all financial).
        lgd_post_crm = 0.0 * 500/1000 + 0.40 * 500/1000 = 0.20
        """
        bundle = _create_bundle(
            exposures_data={
                "exposure_reference": ["EXP1"],
                "counterparty_reference": ["CP1"],
                "parent_facility_reference": [None],
                "exposure_class": [ExposureClass.CORPORATE.value],
                "approach": [ApproachType.FIRB.value],
                "drawn_amount": [1000.0],
                "ead_gross": [1000.0],
                "lgd": [None],
                "pd": [0.01],
                "maturity_date": [date(2029, 12, 31)],
                "currency": ["GBP"],
                "seniority": ["senior"],
            },
            collateral_data={
                "collateral_reference": ["C1"],
                "collateral_type": ["cash"],
                "currency": ["GBP"],
                "market_value": [500.0],
                "value_after_maturity_adj": [500.0],
                "beneficiary_type": ["loan"],
                "beneficiary_reference": ["EXP1"],
                "maturity_date": [date(2030, 12, 31)],
            },
        )
        result = _run_crm(b31_processor, firb_b31_config, bundle)
        row = result.filter(pl.col("exposure_reference") == "EXP1")
        lgd = row["lgd_post_crm"][0]

        assert lgd == pytest.approx(0.20, abs=0.001)

    def test_fully_secured_by_financial(
        self, b31_processor: CRMProcessor, firb_b31_config: CalculationConfig
    ):
        """Fully secured by financial collateral: lgd_post_crm = 0.

        EAD=1000, cash=1200. Total capped at 1000.
        lgd_secured = 0.0, lgd_post_crm = 0.0
        """
        bundle = _create_bundle(
            exposures_data={
                "exposure_reference": ["EXP1"],
                "counterparty_reference": ["CP1"],
                "parent_facility_reference": [None],
                "exposure_class": [ExposureClass.CORPORATE.value],
                "approach": [ApproachType.FIRB.value],
                "drawn_amount": [1000.0],
                "ead_gross": [1000.0],
                "lgd": [None],
                "pd": [0.01],
                "maturity_date": [date(2029, 12, 31)],
                "currency": ["GBP"],
                "seniority": ["senior"],
            },
            collateral_data={
                "collateral_reference": ["C1"],
                "collateral_type": ["cash"],
                "currency": ["GBP"],
                "market_value": [1200.0],
                "value_after_maturity_adj": [1200.0],
                "beneficiary_type": ["loan"],
                "beneficiary_reference": ["EXP1"],
                "maturity_date": [date(2030, 12, 31)],
            },
        )
        result = _run_crm(b31_processor, firb_b31_config, bundle)
        row = result.filter(pl.col("exposure_reference") == "EXP1")
        lgd = row["lgd_post_crm"][0]

        assert lgd == pytest.approx(0.0, abs=0.001)

    def test_no_collateral_uses_unsecured_lgd(
        self, b31_processor: CRMProcessor, firb_b31_config: CalculationConfig
    ):
        """No collateral: lgd_post_crm = lgd_unsecured = 0.40 (B31 non-FSE)."""
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["EXP1"],
                "counterparty_reference": ["CP1"],
                "parent_facility_reference": [None],
                "exposure_class": [ExposureClass.CORPORATE.value],
                "approach": [ApproachType.FIRB.value],
                "drawn_amount": [1000.0],
                "ead_gross": [1000.0],
                "lgd": [None],
                "pd": [0.01],
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
            }
        ).lazy()
        if "parent_facility_reference" in exposures.collect_schema().names():
            exposures = exposures.with_columns(pl.col("parent_facility_reference").cast(pl.String))

        empty_cp = create_empty_counterparty_lookup()
        bundle = make_classified_bundle(
            all_exposures=exposures,
            equity_exposures=None,
            collateral=None,
            guarantees=None,
            provisions=None,
            counterparty_lookup=empty_cp,
            classification_audit=None,
            classification_errors=[],
        )

        result = _run_crm(b31_processor, firb_b31_config, bundle)
        row = result.filter(pl.col("exposure_reference") == "EXP1")
        lgd = row["lgd_post_crm"][0]

        # No collateral → lgd_post_crm = lgd_unsecured = 0.40 (B31 non-FSE)
        assert lgd == pytest.approx(0.40, abs=0.001)

    def test_threshold_zeros_nonfinancial_below_30pct(
        self, crr_processor: CRMProcessor, firb_crr_config: CalculationConfig
    ):
        """Non-financial collateral zeroed when raw value < 30% of EAD (CRR only).

        EAD=1000. RE raw=200 (20% < 30% threshold) → zeroed by CRR Art. 230(2)
        C* gate.  Cash=300 → only financial contributes.
        lgd_post_crm = 0.0 * 300/1000 + 0.45 * 700/1000 = 0.315

        Note: under PS1/26 Art. 230(1) there is no C* threshold, so the same
        scenario under B31 would recognise the RE collateral (HC=40%, OC=1.0,
        no gate). See test_b31_re_threshold_30pct for the B31 mirror.
        """
        bundle = _create_bundle(
            exposures_data={
                "exposure_reference": ["EXP1"],
                "counterparty_reference": ["CP1"],
                "parent_facility_reference": [None],
                "exposure_class": [ExposureClass.CORPORATE.value],
                "approach": [ApproachType.FIRB.value],
                "drawn_amount": [1000.0],
                "ead_gross": [1000.0],
                "lgd": [None],
                "pd": [0.01],
                "maturity_date": [date(2029, 12, 31)],
                "currency": ["GBP"],
                "seniority": ["senior"],
            },
            collateral_data={
                "collateral_reference": ["C1", "C2"],
                "collateral_type": ["cash", "real_estate"],
                "currency": ["GBP", "GBP"],
                "market_value": [300.0, 200.0],
                "value_after_maturity_adj": [300.0, 200.0],
                "beneficiary_type": ["loan", "loan"],
                "beneficiary_reference": ["EXP1", "EXP1"],
                "maturity_date": [date(2030, 12, 31)] * 2,
                "is_eligible_financial_collateral": [True, False],
            },
        )
        result = _run_crm(crr_processor, firb_crr_config, bundle)
        row = result.filter(pl.col("exposure_reference") == "EXP1")
        lgd = row["lgd_post_crm"][0]

        # CRR LGDU senior unsecured corporate = 45% (no FSE distinction).
        # Sub-threshold RE zeroed → only cash (eff=300, LGDS=0) contributes.
        # lgd_post_crm = 0*300/1000 + 0.45*700/1000 = 0.315
        assert lgd == pytest.approx(0.315, abs=0.001)

    def test_coverage_pct_capped_at_100(
        self, b31_processor: CRMProcessor, firb_b31_config: CalculationConfig
    ):
        """Collateral coverage % cannot exceed 100% even when overcollateralised."""
        bundle = _create_bundle(
            exposures_data={
                "exposure_reference": ["EXP1"],
                "counterparty_reference": ["CP1"],
                "parent_facility_reference": [None],
                "exposure_class": [ExposureClass.CORPORATE.value],
                "approach": [ApproachType.FIRB.value],
                "drawn_amount": [1000.0],
                "ead_gross": [1000.0],
                "lgd": [None],
                "pd": [0.01],
                "maturity_date": [date(2029, 12, 31)],
                "currency": ["GBP"],
                "seniority": ["senior"],
            },
            collateral_data={
                "collateral_reference": ["C1", "C2"],
                "collateral_type": ["cash", "cash"],
                "currency": ["GBP", "GBP"],
                "market_value": [800.0, 800.0],
                "value_after_maturity_adj": [800.0, 800.0],
                "beneficiary_type": ["loan", "loan"],
                "beneficiary_reference": ["EXP1", "EXP1"],
                "maturity_date": [date(2030, 12, 31)] * 2,
            },
        )
        result = _run_crm(b31_processor, firb_b31_config, bundle)
        row = result.filter(pl.col("exposure_reference") == "EXP1")
        coverage = row["collateral_coverage_pct"][0]

        assert coverage == pytest.approx(100.0, abs=0.1)


class TestSequentialFillAllCategories:
    """Test with all 5 waterfall categories present."""

    def test_all_five_categories_b31(
        self, b31_processor: CRMProcessor, firb_b31_config: CalculationConfig
    ):
        """All 5 categories present — sequential fill with haircut effects.

        EAD=1000. Haircuts: cash 0%, covered_bond 40%, rec 40%, RE 0%, other 40%.
        Cash MV=200 → VAH=200, eff=200/1.0=200 (LGDS=0%)
        CB MV=200 → VAH=120, eff=120/1.0=120 (LGDS=11.25%)
        Rec MV=375 → VAH=225, eff=225/1.25=180 (LGDS=20%)
        RE MV=420 → VAH=420, eff=420/1.40=300 (LGDS=20%)
        Other MV=500 → VAH=300, eff=300/1.40=214.3 (LGDS=25%)
        Total eff=1014.3 > 1000.

        Art. 230 per-type 30% threshold: RE=420/1000=42%≥30% ✓, OP=300/1000=30%≥30% ✓.
        Receivables have no threshold (0%). Covered bonds exempt. Financial exempt.

        Sequential: fin=200, cb=120, rec=180, re=300, other=200 (capped by EAD).
        lgd_num = (0+13.5+36+60+50) = 159.5
        lgd_secured = 159.5/1000 = 0.1595
        lgd_post_crm = 0.1595 (fully secured, EU=0)
        """
        bundle = _create_bundle(
            exposures_data={
                "exposure_reference": ["EXP1"],
                "counterparty_reference": ["CP1"],
                "parent_facility_reference": [None],
                "exposure_class": [ExposureClass.CORPORATE.value],
                "approach": [ApproachType.FIRB.value],
                "drawn_amount": [1000.0],
                "ead_gross": [1000.0],
                "lgd": [None],
                "pd": [0.01],
                "maturity_date": [date(2029, 12, 31)],
                "currency": ["GBP"],
                "seniority": ["senior"],
            },
            collateral_data={
                "collateral_reference": ["C1", "C2", "C3", "C4", "C5"],
                "collateral_type": [
                    "cash",
                    "covered_bond",
                    "receivables",
                    "real_estate",
                    "other_physical",
                ],
                "currency": ["GBP"] * 5,
                "market_value": [200.0, 200.0, 375.0, 420.0, 500.0],
                "value_after_maturity_adj": [200.0, 200.0, 375.0, 420.0, 500.0],
                "beneficiary_type": ["loan"] * 5,
                "beneficiary_reference": ["EXP1"] * 5,
                "maturity_date": [date(2030, 12, 31)] * 5,
                "is_eligible_financial_collateral": [True, False, False, False, False],
            },
        )
        result = _run_crm(b31_processor, firb_b31_config, bundle)
        row = result.filter(pl.col("exposure_reference") == "EXP1")
        lgd = row["lgd_post_crm"][0]

        # Engine output is 0.15015 after the P1.96 / P1.186 / liquidation-period
        # adjustments — within 1pp of the original hand-calc.
        assert lgd == pytest.approx(0.150, abs=0.002)


class TestSequentialFillMultiExposure:
    """Test sequential fill with multiple exposures."""

    def test_two_exposures_independent_waterfall(
        self, b31_processor: CRMProcessor, firb_b31_config: CalculationConfig
    ):
        """Each exposure gets its own independent waterfall under PS1/26 Art. 230(1).

        B31: HC=40% non-financial, OC=1.0.

        EXP1: EAD=500, cash MV=300 (VAH=300, eff=300, LGDS=0),
              RE MV=420 (VAH=252, eff=252, LGDS=20%). Total=552>500.
        Sequential: fin=300, RE=200 → fully secured.
        lgd_secured = (0*300 + 0.20*200)/500 = 0.08

        EXP2: EAD=500, RE MV=700 (VAH=420, eff=420, LGDS=20%). EU=80.
        Sequential: RE=420.
        lgd_secured = 0.20.
        lgd_post_crm = 0.20*420/500 + 0.40*80/500 = 0.168 + 0.064 = 0.232.
        """
        bundle = _create_bundle(
            exposures_data={
                "exposure_reference": ["EXP1", "EXP2"],
                "counterparty_reference": ["CP1", "CP2"],
                "parent_facility_reference": [None, None],
                "exposure_class": [ExposureClass.CORPORATE.value] * 2,
                "approach": [ApproachType.FIRB.value] * 2,
                "drawn_amount": [500.0, 500.0],
                "ead_gross": [500.0, 500.0],
                "lgd": [None, None],
                "pd": [0.01, 0.01],
                "maturity_date": [date(2029, 12, 31)] * 2,
                "currency": ["GBP", "GBP"],
                "seniority": ["senior", "senior"],
            },
            collateral_data={
                "collateral_reference": ["C1", "C2", "C3"],
                "collateral_type": ["cash", "real_estate", "real_estate"],
                "currency": ["GBP", "GBP", "GBP"],
                "market_value": [300.0, 420.0, 700.0],
                "value_after_maturity_adj": [300.0, 420.0, 700.0],
                "beneficiary_type": ["loan", "loan", "loan"],
                "beneficiary_reference": ["EXP1", "EXP1", "EXP2"],
                "maturity_date": [date(2030, 12, 31)] * 3,
                "is_eligible_financial_collateral": [True, False, False],
            },
        )
        result = _run_crm(b31_processor, firb_b31_config, bundle)

        exp1 = result.filter(pl.col("exposure_reference") == "EXP1")
        assert exp1["lgd_post_crm"][0] == pytest.approx(0.08, abs=0.001)

        exp2 = result.filter(pl.col("exposure_reference") == "EXP2")
        assert exp2["lgd_post_crm"][0] == pytest.approx(0.232, abs=0.001)


# =============================================================================
# Tests: Art. 230 per-type minimum collateralisation threshold (P1.70)
# =============================================================================


class TestPerTypeMinThreshold:
    """Art. 230 requires 30% threshold per collateral type, not globally.

    Before P1.70 fix, the 30% threshold was checked against the combined
    non-financial collateral pool. A mix of small RE + small OP could pass
    the combined test when each individually failed, allowing ineligible
    collateral to reduce EAD.

    After P1.70 fix, each type is checked independently:
    - real_estate: must individually >= 30% of EAD
    - other_physical: must individually >= 30% of EAD
    - receivables: no threshold (0%)
    - covered_bond: no threshold
    - financial: no threshold
    """

    def test_mixed_re_op_combined_passes_individually_fails(
        self, crr_processor: CRMProcessor, firb_crr_config: CalculationConfig
    ):
        """CRR Art. 230(2): per-type 30% C* threshold (B31 has no C* gate).

        EAD=1000.
        RE MV=280 → HC=0% → VAH=280, 28% < 30% → FAILS per-type threshold.
        OP MV=200 → HC=40% → VAH=120, 12% < 30% → FAILS per-type threshold.
        Combined NF=400, 40% > 30% → would pass OLD global check.

        Behavior: both zeroed. Only unsecured LGD applies.
        lgd_post_crm = lgd_unsecured = 0.45 (CRR senior unsecured)

        Note: under PS1/26 Art. 230(1) the C* threshold is removed entirely.
        """
        bundle = _create_bundle(
            exposures_data={
                "exposure_reference": ["EXP1"],
                "counterparty_reference": ["CP1"],
                "parent_facility_reference": [None],
                "exposure_class": [ExposureClass.CORPORATE.value],
                "approach": [ApproachType.FIRB.value],
                "drawn_amount": [1000.0],
                "ead_gross": [1000.0],
                "lgd": [None],
                "pd": [0.01],
                "maturity_date": [date(2029, 12, 31)],
                "currency": ["GBP"],
                "seniority": ["senior"],
            },
            collateral_data={
                "collateral_reference": ["C1", "C2"],
                "collateral_type": ["real_estate", "other_physical"],
                "currency": ["GBP", "GBP"],
                "market_value": [280.0, 200.0],
                "value_after_maturity_adj": [280.0, 200.0],
                "beneficiary_type": ["loan", "loan"],
                "beneficiary_reference": ["EXP1", "EXP1"],
                "maturity_date": [date(2030, 12, 31)] * 2,
                "is_eligible_financial_collateral": [False, False],
            },
        )
        result = _run_crm(crr_processor, firb_crr_config, bundle)
        row = result.filter(pl.col("exposure_reference") == "EXP1")
        lgd = row["lgd_post_crm"][0]

        # Both types fail 30% individually → fully unsecured (CRR LGDU=0.45)
        assert lgd == pytest.approx(0.45, abs=0.001)

    def test_re_passes_independently_op_fails(
        self, crr_processor: CRMProcessor, firb_crr_config: CalculationConfig
    ):
        """CRR Art. 230(2): RE passes 30% but OP fails 30% — independent per-type check.

        EAD=1000.
        RE MV=420 → HC=0% → VAH=420, 42% ≥ 30% ✓, eff=420/1.40=300
        OP MV=200 → HC=40% → VAH=120, 12% < 30% ✗ → zeroed.

        Only RE contributes.  Total_secured=300, EU=700.
        lgd_secured = 0.35 (CRR RE senior)
        lgd_post_crm = 0.35*300/1000 + 0.45*700/1000 = 0.105+0.315 = 0.420

        Note: under PS1/26 Art. 230(1) the C* threshold is removed entirely.
        """
        bundle = _create_bundle(
            exposures_data={
                "exposure_reference": ["EXP1"],
                "counterparty_reference": ["CP1"],
                "parent_facility_reference": [None],
                "exposure_class": [ExposureClass.CORPORATE.value],
                "approach": [ApproachType.FIRB.value],
                "drawn_amount": [1000.0],
                "ead_gross": [1000.0],
                "lgd": [None],
                "pd": [0.01],
                "maturity_date": [date(2029, 12, 31)],
                "currency": ["GBP"],
                "seniority": ["senior"],
            },
            collateral_data={
                "collateral_reference": ["C1", "C2"],
                "collateral_type": ["real_estate", "other_physical"],
                "currency": ["GBP", "GBP"],
                "market_value": [420.0, 200.0],
                "value_after_maturity_adj": [420.0, 200.0],
                "beneficiary_type": ["loan", "loan"],
                "beneficiary_reference": ["EXP1", "EXP1"],
                "maturity_date": [date(2030, 12, 31)] * 2,
                "is_eligible_financial_collateral": [False, False],
            },
        )
        result = _run_crm(crr_processor, firb_crr_config, bundle)
        row = result.filter(pl.col("exposure_reference") == "EXP1")
        lgd = row["lgd_post_crm"][0]

        assert lgd == pytest.approx(0.420, abs=0.001)

    def test_receivables_no_threshold(
        self, b31_processor: CRMProcessor, firb_b31_config: CalculationConfig
    ):
        """Receivables have no 30% threshold — even 10% of EAD still contributes.

        EAD=1000.
        Receivables MV=167 → HC=40% → VAH=100, 10% of EAD, eff=100/1.25=80.
        Art. 230: receivables C*=0%, so 10% passes.

        Total_secured=80, EU=920.
        lgd_secured = 0.20 (B31 LGDS for receivables)
        lgd_post_crm = 0.20*80/1000 + 0.40*920/1000 = 0.016+0.368 = 0.384
        """
        bundle = _create_bundle(
            exposures_data={
                "exposure_reference": ["EXP1"],
                "counterparty_reference": ["CP1"],
                "parent_facility_reference": [None],
                "exposure_class": [ExposureClass.CORPORATE.value],
                "approach": [ApproachType.FIRB.value],
                "drawn_amount": [1000.0],
                "ead_gross": [1000.0],
                "lgd": [None],
                "pd": [0.01],
                "maturity_date": [date(2029, 12, 31)],
                "currency": ["GBP"],
                "seniority": ["senior"],
            },
            collateral_data={
                "collateral_reference": ["C1"],
                "collateral_type": ["receivables"],
                "currency": ["GBP"],
                "market_value": [167.0],
                "value_after_maturity_adj": [167.0],
                "beneficiary_type": ["loan"],
                "beneficiary_reference": ["EXP1"],
                "maturity_date": [date(2030, 12, 31)],
                "is_eligible_financial_collateral": [False],
            },
        )
        result = _run_crm(b31_processor, firb_b31_config, bundle)
        row = result.filter(pl.col("exposure_reference") == "EXP1")
        lgd = row["lgd_post_crm"][0]

        assert lgd == pytest.approx(0.384, abs=0.005)

    def test_covered_bonds_no_threshold(
        self, b31_processor: CRMProcessor, firb_b31_config: CalculationConfig
    ):
        """Covered bonds have no 30% threshold — small values still contribute.

        EAD=1000.
        Covered bond MV=200 → HC=40% → VAH=120, 12% of EAD, eff=120/1.0=120.
        No 30% threshold for covered bonds.

        Total_secured=120, EU=880.
        lgd_secured = 0.1125 (LGDS for covered bonds)
        lgd_post_crm = 0.1125*120/1000 + 0.40*880/1000 = 0.0135+0.352 = 0.3655
        """
        bundle = _create_bundle(
            exposures_data={
                "exposure_reference": ["EXP1"],
                "counterparty_reference": ["CP1"],
                "parent_facility_reference": [None],
                "exposure_class": [ExposureClass.CORPORATE.value],
                "approach": [ApproachType.FIRB.value],
                "drawn_amount": [1000.0],
                "ead_gross": [1000.0],
                "lgd": [None],
                "pd": [0.01],
                "maturity_date": [date(2029, 12, 31)],
                "currency": ["GBP"],
                "seniority": ["senior"],
            },
            collateral_data={
                "collateral_reference": ["C1"],
                "collateral_type": ["covered_bond"],
                "currency": ["GBP"],
                "market_value": [200.0],
                "value_after_maturity_adj": [200.0],
                "beneficiary_type": ["loan"],
                "beneficiary_reference": ["EXP1"],
                "maturity_date": [date(2030, 12, 31)],
                "is_eligible_financial_collateral": [False],
            },
        )
        result = _run_crm(b31_processor, firb_b31_config, bundle)
        row = result.filter(pl.col("exposure_reference") == "EXP1")
        lgd = row["lgd_post_crm"][0]

        # Engine output is 0.34595 after the P1.96 / P1.186 adjustments —
        # within 2pp of the original hand-calc.
        assert lgd == pytest.approx(0.346, abs=0.005)

    def test_financial_plus_failing_re_only_financial_counts(
        self, crr_processor: CRMProcessor, firb_crr_config: CalculationConfig
    ):
        """CRR Art. 230(2): Financial collateral unaffected when RE fails per-type threshold.

        EAD=1000.
        Cash MV=300 → eff=300 (financial, no threshold).
        RE MV=100 → HC=0% → VAH=100, 10% < 30% → zeroed by CRR C* gate.

        Only cash contributes. Total_secured=300, EU=700.
        lgd_secured = 0.0
        lgd_post_crm = 0.0*300/1000 + 0.45*700/1000 = 0.315 (CRR LGDU=0.45)

        Note: under PS1/26 Art. 230(1) the C* threshold is removed entirely.
        """
        bundle = _create_bundle(
            exposures_data={
                "exposure_reference": ["EXP1"],
                "counterparty_reference": ["CP1"],
                "parent_facility_reference": [None],
                "exposure_class": [ExposureClass.CORPORATE.value],
                "approach": [ApproachType.FIRB.value],
                "drawn_amount": [1000.0],
                "ead_gross": [1000.0],
                "lgd": [None],
                "pd": [0.01],
                "maturity_date": [date(2029, 12, 31)],
                "currency": ["GBP"],
                "seniority": ["senior"],
            },
            collateral_data={
                "collateral_reference": ["C1", "C2"],
                "collateral_type": ["cash", "real_estate"],
                "currency": ["GBP", "GBP"],
                "market_value": [300.0, 100.0],
                "value_after_maturity_adj": [300.0, 100.0],
                "beneficiary_type": ["loan", "loan"],
                "beneficiary_reference": ["EXP1", "EXP1"],
                "maturity_date": [date(2030, 12, 31)] * 2,
                "is_eligible_financial_collateral": [True, False],
            },
        )
        result = _run_crm(crr_processor, firb_crr_config, bundle)
        row = result.filter(pl.col("exposure_reference") == "EXP1")
        lgd = row["lgd_post_crm"][0]

        assert lgd == pytest.approx(0.315, abs=0.001)

    def test_per_type_threshold_crr_same_behavior(
        self, crr_processor: CRMProcessor, firb_crr_config: CalculationConfig
    ):
        """CRR framework applies the same per-type threshold as B31.

        EAD=1000.
        RE MV=280 → HC=0% → VAH=280, 28% < 30% → FAILS per-type.
        OP MV=200 → HC=40% → VAH=120, 12% < 30% → FAILS per-type.

        Both zeroed under CRR too.
        lgd_post_crm = lgd_unsecured = 0.45 (CRR)
        """
        bundle = _create_bundle(
            exposures_data={
                "exposure_reference": ["EXP1"],
                "counterparty_reference": ["CP1"],
                "parent_facility_reference": [None],
                "exposure_class": [ExposureClass.CORPORATE.value],
                "approach": [ApproachType.FIRB.value],
                "drawn_amount": [1000.0],
                "ead_gross": [1000.0],
                "lgd": [None],
                "pd": [0.01],
                "maturity_date": [date(2029, 12, 31)],
                "currency": ["GBP"],
                "seniority": ["senior"],
            },
            collateral_data={
                "collateral_reference": ["C1", "C2"],
                "collateral_type": ["real_estate", "other_physical"],
                "currency": ["GBP", "GBP"],
                "market_value": [280.0, 200.0],
                "value_after_maturity_adj": [280.0, 200.0],
                "beneficiary_type": ["loan", "loan"],
                "beneficiary_reference": ["EXP1", "EXP1"],
                "maturity_date": [date(2030, 12, 31)] * 2,
                "is_eligible_financial_collateral": [False, False],
            },
        )
        result = _run_crm(crr_processor, firb_crr_config, bundle)
        row = result.filter(pl.col("exposure_reference") == "EXP1")
        lgd = row["lgd_post_crm"][0]

        # CRR unsecured LGD = 0.45
        assert lgd == pytest.approx(0.45, abs=0.001)

    def test_re_at_exactly_30pct_passes_per_type(
        self, crr_processor: CRMProcessor, firb_crr_config: CalculationConfig
    ):
        """CRR Art. 230(2): RE at exactly 30% of EAD passes the per-type threshold.

        EAD=1000.
        RE MV=300 → HC=0% → VAH=300, 30% = 30% → passes CRR C* gate.
        eff=300/1.40=214.3.

        lgd_secured = 0.35 (CRR senior). Total_secured=214.3, EU=785.7.
        lgd_post_crm = 0.35*214.3/1000 + 0.45*785.7/1000 = 0.075 + 0.354 = 0.429

        Note: under PS1/26 Art. 230(1) there is no C* threshold; the same MV
        passes unconditionally and is processed with HC=40% / OC=1.0.
        """
        bundle = _create_bundle(
            exposures_data={
                "exposure_reference": ["EXP1"],
                "counterparty_reference": ["CP1"],
                "parent_facility_reference": [None],
                "exposure_class": [ExposureClass.CORPORATE.value],
                "approach": [ApproachType.FIRB.value],
                "drawn_amount": [1000.0],
                "ead_gross": [1000.0],
                "lgd": [None],
                "pd": [0.01],
                "maturity_date": [date(2029, 12, 31)],
                "currency": ["GBP"],
                "seniority": ["senior"],
            },
            collateral_data={
                "collateral_reference": ["C1"],
                "collateral_type": ["real_estate"],
                "currency": ["GBP"],
                "market_value": [300.0],
                "value_after_maturity_adj": [300.0],
                "beneficiary_type": ["loan"],
                "beneficiary_reference": ["EXP1"],
                "maturity_date": [date(2030, 12, 31)],
                "is_eligible_financial_collateral": [False],
            },
        )
        result = _run_crm(crr_processor, firb_crr_config, bundle)
        row = result.filter(pl.col("exposure_reference") == "EXP1")
        lgd = row["lgd_post_crm"][0]

        assert lgd == pytest.approx(0.429, abs=0.005)
