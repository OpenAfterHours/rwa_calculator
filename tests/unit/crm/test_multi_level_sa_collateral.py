"""
Tests for multi-level collateral allocation for SA EAD reduction.

When collateral is pledged at facility or counterparty level (via beneficiary_type),
child exposures must receive the collateral benefit pro-rata by EAD for SA EAD reduction,
and the haircut calculator must resolve FX haircuts at all levels.

Covers:
- Direct collateral still reduces SA EAD (baseline)
- Facility-level collateral reduces SA EAD for child exposures
- Facility-level collateral split pro-rata across multiple children
- Counterparty-level collateral split pro-rata across multiple children
- Mixed direct + facility + counterparty collateral stacks
- Facility collateral does NOT reduce IRB EAD (IRB uses LGD path)
- EAD cannot go below 0 when collateral exceeds exposure
- FX haircut applied for facility-level collateral with currency mismatch
- No FX haircut when facility-level collateral same currency as exposure
"""

from __future__ import annotations

import math
from datetime import date

import polars as pl
import pytest
from tests.unit.crm._crm_bundles import empty_counterparty_lookup

from rwa_calc.contracts.bundles import ClassifiedExposuresBundle
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import ApproachType, PermissionMode
from rwa_calc.engine.crm.processor import CRMProcessor

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def processor() -> CRMProcessor:
    return CRMProcessor()


@pytest.fixture
def sa_config() -> CalculationConfig:
    return CalculationConfig.crr(
        reporting_date=date(2024, 12, 31),
        permission_mode=PermissionMode.STANDARDISED,
    )


@pytest.fixture
def firb_config() -> CalculationConfig:
    return CalculationConfig.crr(
        reporting_date=date(2024, 12, 31),
        permission_mode=PermissionMode.IRB,
    )


@pytest.fixture
def b31_processor() -> CRMProcessor:
    return CRMProcessor(is_basel_3_1=True)


@pytest.fixture
def b31_firb_config() -> CalculationConfig:
    return CalculationConfig.basel_3_1(
        reporting_date=date(2030, 6, 30),
        permission_mode=PermissionMode.IRB,
    )


# =============================================================================
# Helpers
# =============================================================================


def _make_bundle(
    exposures: pl.LazyFrame,
    collateral: pl.LazyFrame,
) -> ClassifiedExposuresBundle:
    """Build a ClassifiedExposuresBundle with collateral only."""
    return ClassifiedExposuresBundle(
        all_exposures=exposures,
        equity_exposures=None,
        counterparty_lookup=empty_counterparty_lookup(),
        collateral=collateral,
        guarantees=None,
        provisions=None,
    )


def _sa_exposure(
    ref: str,
    drawn: float,
    nominal: float = 0.0,
    facility_ref: str = "FAC_DEFAULT",
    cp_ref: str = "CP001",
    currency: str = "GBP",
) -> dict:
    """Create an SA exposure row."""
    return {
        "exposure_reference": ref,
        "counterparty_reference": cp_ref,
        "exposure_class": "corporate",
        "approach": ApproachType.SA.value,
        "drawn_amount": drawn,
        "interest": 0.0,
        "nominal_amount": nominal,
        "risk_type": "FR" if math.isclose(nominal, 0.0, abs_tol=1e-10) else "MR",
        "lgd": 0.45,
        "seniority": "senior",
        "parent_facility_reference": facility_ref,
        "currency": currency,
        "maturity_date": None,
    }


def _irb_exposure(
    ref: str,
    drawn: float,
    nominal: float = 0.0,
    facility_ref: str = "FAC_DEFAULT",
    cp_ref: str = "CP001",
) -> dict:
    """Create an FIRB exposure row."""
    return {
        "exposure_reference": ref,
        "counterparty_reference": cp_ref,
        "exposure_class": "corporate",
        "approach": ApproachType.FIRB.value,
        "drawn_amount": drawn,
        "interest": 0.0,
        "nominal_amount": nominal,
        "risk_type": "FR" if math.isclose(nominal, 0.0, abs_tol=1e-10) else "MR",
        "lgd": 0.45,
        "seniority": "senior",
        "parent_facility_reference": facility_ref,
        "currency": "GBP",
        "maturity_date": None,
    }


def _cash_collateral(
    beneficiary_ref: str,
    market_value: float | None = 0.0,
    beneficiary_type: str = "exposure",
    currency: str = "GBP",
    pledge_percentage: float | None = None,
) -> dict:
    """Create a cash collateral row with all required haircut fields.

    Pass ``pledge_percentage`` (with ``market_value=None``/0) to express a
    percentage pledge that resolves against the beneficiary's EAD.
    """
    return {
        "collateral_reference": f"COLL_{beneficiary_ref}",
        "beneficiary_reference": beneficiary_ref,
        "beneficiary_type": beneficiary_type,
        "collateral_type": "cash",
        "market_value": market_value,
        "currency": currency,
        "issuer_cqs": None,
        "issuer_type": None,
        "residual_maturity_years": None,
        "is_eligible_financial_collateral": True,
        "pledge_percentage": pledge_percentage,
        "collateral_maturity_date": None,
    }


def _run_crm_with_liq_period(
    processor: CRMProcessor,
    config: CalculationConfig,
    exposure_rows: list[dict],
    collateral_rows: list[dict],
    liquidation_period_days: int = 10,
) -> pl.DataFrame:
    """Run CRM pipeline with an explicit liquidation period override.

    P1.186: used by tests that pin a specific liquidation period to isolate
    logic other than the secured-lending period default (which changed to 20).
    """
    exposures = pl.LazyFrame(exposure_rows)
    collateral_schema = {
        "collateral_reference": pl.String,
        "beneficiary_reference": pl.String,
        "beneficiary_type": pl.String,
        "collateral_type": pl.String,
        "market_value": pl.Float64,
        "currency": pl.String,
        "issuer_cqs": pl.Int64,
        "issuer_type": pl.String,
        "residual_maturity_years": pl.Float64,
        "is_eligible_financial_collateral": pl.Boolean,
        "pledge_percentage": pl.Float64,
        "collateral_maturity_date": pl.Date,
    }
    collateral = pl.LazyFrame(collateral_rows, schema=collateral_schema).with_columns(
        pl.lit(liquidation_period_days).alias("liquidation_period_days")
    )
    bundle = _make_bundle(exposures, collateral)
    result = processor.get_crm_unified_bundle(bundle, config)
    df: pl.DataFrame = result.exposures.collect()
    return df


def _run_crm(
    processor: CRMProcessor,
    config: CalculationConfig,
    exposure_rows: list[dict],
    collateral_rows: list[dict],
) -> pl.DataFrame:
    """Run CRM pipeline and return collected result."""
    exposures = pl.LazyFrame(exposure_rows)
    collateral_schema = {
        "collateral_reference": pl.String,
        "beneficiary_reference": pl.String,
        "beneficiary_type": pl.String,
        "collateral_type": pl.String,
        "market_value": pl.Float64,
        "currency": pl.String,
        "issuer_cqs": pl.Int64,
        "issuer_type": pl.String,
        "residual_maturity_years": pl.Float64,
        "is_eligible_financial_collateral": pl.Boolean,
        "pledge_percentage": pl.Float64,
        "collateral_maturity_date": pl.Date,
    }
    collateral = pl.LazyFrame(collateral_rows, schema=collateral_schema)
    bundle = _make_bundle(exposures, collateral)
    result = processor.get_crm_unified_bundle(bundle, config)
    df: pl.DataFrame = result.exposures.collect()
    return df


# =============================================================================
# Tests: SA EAD Reduction Multi-Level
# =============================================================================


class TestDirectCollateralBaseline:
    """Baseline: direct collateral still works as before."""

    def test_direct_collateral_reduces_sa_ead(
        self, processor: CRMProcessor, sa_config: CalculationConfig
    ):
        """Direct collateral (beneficiary_type='exposure') reduces SA EAD."""
        result = _run_crm(
            processor,
            sa_config,
            [_sa_exposure("EXP001", drawn=1000.0)],
            [_cash_collateral("EXP001", market_value=400.0, beneficiary_type="exposure")],
        )
        row = result.filter(pl.col("exposure_reference") == "EXP001")
        ead_after = row["ead_after_collateral"][0]
        assert ead_after == pytest.approx(600.0, abs=1.0)


class TestFacilityLevelCollateral:
    """Facility-level collateral flows to child exposures."""

    def test_facility_collateral_reduces_sa_ead_single_child(
        self, processor: CRMProcessor, sa_config: CalculationConfig
    ):
        """Facility cash collateral with one child reduces that child's SA EAD."""
        result = _run_crm(
            processor,
            sa_config,
            [_sa_exposure("EXP001", drawn=1000.0, facility_ref="FAC001")],
            [_cash_collateral("FAC001", market_value=400.0, beneficiary_type="facility")],
        )
        row = result.filter(pl.col("exposure_reference") == "EXP001")
        ead_after = row["ead_after_collateral"][0]
        # Single child gets 100% of facility collateral → 1000 - 400 = 600
        assert ead_after == pytest.approx(600.0, abs=1.0)

    def test_facility_collateral_reduces_sa_ead_pro_rata(
        self, processor: CRMProcessor, sa_config: CalculationConfig
    ):
        """Facility collateral split pro-rata across multiple children by EAD."""
        # EXP001: drawn=600 (60%), EXP002: drawn=400 (40%), total=1000
        # Collateral: 500 → EXP001 gets 300, EXP002 gets 200
        result = _run_crm(
            processor,
            sa_config,
            [
                _sa_exposure("EXP001", drawn=600.0, facility_ref="FAC001"),
                _sa_exposure("EXP002", drawn=400.0, facility_ref="FAC001"),
            ],
            [_cash_collateral("FAC001", market_value=500.0, beneficiary_type="facility")],
        )
        row1 = result.filter(pl.col("exposure_reference") == "EXP001")
        row2 = result.filter(pl.col("exposure_reference") == "EXP002")
        # EXP001: 600 - (500 * 600/1000) = 600 - 300 = 300
        assert row1["ead_after_collateral"][0] == pytest.approx(300.0, abs=1.0)
        # EXP002: 400 - (500 * 400/1000) = 400 - 200 = 200
        assert row2["ead_after_collateral"][0] == pytest.approx(200.0, abs=1.0)


class TestCounterpartyLevelCollateral:
    """Counterparty-level collateral flows to child exposures."""

    def test_counterparty_collateral_reduces_sa_ead_pro_rata(
        self, processor: CRMProcessor, sa_config: CalculationConfig
    ):
        """Counterparty collateral split pro-rata across all exposures for that CP."""
        # EXP001: drawn=700 (70%), EXP002: drawn=300 (30%), total=1000
        # Collateral: 200 → EXP001 gets 140, EXP002 gets 60
        result = _run_crm(
            processor,
            sa_config,
            [
                _sa_exposure("EXP001", drawn=700.0, cp_ref="CP001"),
                _sa_exposure("EXP002", drawn=300.0, cp_ref="CP001"),
            ],
            [_cash_collateral("CP001", market_value=200.0, beneficiary_type="counterparty")],
        )
        row1 = result.filter(pl.col("exposure_reference") == "EXP001")
        row2 = result.filter(pl.col("exposure_reference") == "EXP002")
        # EXP001: 700 - (200 * 700/1000) = 700 - 140 = 560
        assert row1["ead_after_collateral"][0] == pytest.approx(560.0, abs=1.0)
        # EXP002: 300 - (200 * 300/1000) = 300 - 60 = 240
        assert row2["ead_after_collateral"][0] == pytest.approx(240.0, abs=1.0)


class TestMixedLevelCollateral:
    """Stacking direct + facility + counterparty collateral."""

    def test_mixed_level_collateral_combines_all_levels(
        self, processor: CRMProcessor, sa_config: CalculationConfig
    ):
        """Direct + facility + counterparty collateral all contribute to SA EAD reduction."""
        # Single exposure with drawn=1000, under FAC001, counterparty CP001
        # Direct collateral: 100
        # Facility collateral: 200 (100% to single child)
        # Counterparty collateral: 150 (100% to single cp exposure)
        # Total: 450 → EAD = 1000 - 450 = 550
        result = _run_crm(
            processor,
            sa_config,
            [_sa_exposure("EXP001", drawn=1000.0, facility_ref="FAC001", cp_ref="CP001")],
            [
                _cash_collateral("EXP001", market_value=100.0, beneficiary_type="exposure"),
                _cash_collateral("FAC001", market_value=200.0, beneficiary_type="facility"),
                _cash_collateral("CP001", market_value=150.0, beneficiary_type="counterparty"),
            ],
        )
        row = result.filter(pl.col("exposure_reference") == "EXP001")
        ead_after = row["ead_after_collateral"][0]
        assert ead_after == pytest.approx(550.0, abs=1.0)


class TestIRBExposuresUnaffected:
    """FIRB exposures: collateral affects LGD, not EAD."""

    def test_facility_collateral_does_not_reduce_irb_ead(
        self, processor: CRMProcessor, firb_config: CalculationConfig
    ):
        """FIRB exposure EAD unchanged by facility-level collateral (LGD path handles it)."""
        result = _run_crm(
            processor,
            firb_config,
            [_irb_exposure("EXP001", drawn=1000.0, facility_ref="FAC001")],
            [_cash_collateral("FAC001", market_value=400.0, beneficiary_type="facility")],
        )
        row = result.filter(pl.col("exposure_reference") == "EXP001")
        # IRB: EAD after collateral = ead_gross (unchanged)
        assert row["ead_after_collateral"][0] == pytest.approx(1000.0, abs=1.0)


class TestCollateralCap:
    """EAD cannot go below 0."""

    def test_collateral_capped_at_ead(self, processor: CRMProcessor, sa_config: CalculationConfig):
        """SA EAD after collateral is floored at 0 when collateral exceeds exposure."""
        result = _run_crm(
            processor,
            sa_config,
            [_sa_exposure("EXP001", drawn=500.0, facility_ref="FAC001")],
            [_cash_collateral("FAC001", market_value=800.0, beneficiary_type="facility")],
        )
        row = result.filter(pl.col("exposure_reference") == "EXP001")
        assert row["ead_after_collateral"][0] == pytest.approx(0.0, abs=0.01)


class TestFXHaircutMultiLevel:
    """FX haircut correctly applied for facility-level collateral."""

    def test_facility_collateral_fx_haircut_applied(
        self, processor: CRMProcessor, sa_config: CalculationConfig
    ):
        """FX haircut on facility-level collateral when currencies differ.

        P1.186: liquidation_period_days=10 is injected via with_columns to pin
        the 10-day capital-market FX haircut (8%). This test verifies that the
        FX haircut applies to facility-level collateral with a currency mismatch;
        it is not testing liquidation-period scaling. The new pipeline default
        is 20-day (11.314% FX haircut).
        """
        # Exposure in GBP, collateral in USD → 8% FX haircut (10-day explicit)
        # Cash has 0% collateral haircut, so adjusted = 400 * (1 - 0.0 - 0.08) = 368
        # EAD = 1000 - 368 = 632
        result = _run_crm_with_liq_period(
            processor,
            sa_config,
            [_sa_exposure("EXP001", drawn=1000.0, facility_ref="FAC001", currency="GBP")],
            [
                _cash_collateral(
                    "FAC001", market_value=400.0, beneficiary_type="facility", currency="USD"
                )
            ],
            liquidation_period_days=10,  # P1.186: explicit 10-day
        )
        row = result.filter(pl.col("exposure_reference") == "EXP001")
        ead_after = row["ead_after_collateral"][0]
        # With maturity adjustment factor applied (cash residual_maturity_years=None → 10.0 → factor=1.0)
        # So adjusted = 400 * (1 - 0.08) = 368, EAD = 1000 - 368 = 632
        assert ead_after == pytest.approx(632.0, abs=1.0)

    def test_facility_collateral_same_currency_no_fx_haircut(
        self, processor: CRMProcessor, sa_config: CalculationConfig
    ):
        """No FX haircut when facility collateral and exposure share same currency."""
        # Both in GBP → 0% FX haircut; cash 0% collateral haircut → adjusted = 400
        # EAD = 1000 - 400 = 600
        result = _run_crm(
            processor,
            sa_config,
            [_sa_exposure("EXP001", drawn=1000.0, facility_ref="FAC001", currency="GBP")],
            [
                _cash_collateral(
                    "FAC001", market_value=400.0, beneficiary_type="facility", currency="GBP"
                )
            ],
        )
        row = result.filter(pl.col("exposure_reference") == "EXP001")
        ead_after = row["ead_after_collateral"][0]
        assert ead_after == pytest.approx(600.0, abs=1.0)


def _with_ancestors(row: dict, ancestors: list[str]) -> dict:
    """Attach an ancestor_facilities list (parent + ancestors up to root) to a row."""
    return {**row, "ancestor_facilities": ancestors}


class TestNestedFacilityCollateralCascade:
    """Collateral pledged at an ancestor facility cascades down the facility tree.

    The HierarchyResolver supplies ``ancestor_facilities`` (parent + all
    ancestors incl. self). These tests inject it directly to exercise the CRM
    cascade in isolation: a pledge at a grandparent facility must reach every
    descendant loan/contingent, pro-rata by ead_for_crm.
    """

    def test_grandparent_pct_pledge_covers_all_firb_children(
        self, processor: CRMProcessor, firb_config: CalculationConfig
    ):
        """FIRB user scenario: cash pledge_percentage=1.0 at the grandparent FAC_1
        fully secures every loan + contingent sitting under the child FAC_2."""
        anc = ["FAC_2", "FAC_1"]
        exposures = [
            _with_ancestors(_irb_exposure("L1", drawn=600.0, facility_ref="FAC_2"), anc),
            _with_ancestors(_irb_exposure("L2", drawn=400.0, facility_ref="FAC_2"), anc),
            _with_ancestors(
                _irb_exposure("C1", drawn=0.0, nominal=200.0, facility_ref="FAC_2"), anc
            ),
        ]
        result = _run_crm(
            processor,
            firb_config,
            exposures,
            [
                _cash_collateral(
                    "FAC_1",
                    market_value=None,
                    beneficiary_type="facility",
                    pledge_percentage=1.0,
                )
            ],
        )
        for ref in ("L1", "L2", "C1"):
            row = result.filter(pl.col("exposure_reference") == ref)
            assert row["lgd_post_crm"][0] == pytest.approx(0.0), ref
            assert row["collateral_coverage_pct"][0] == pytest.approx(100.0, abs=0.5), ref

    def test_grandparent_amount_pledge_covers_all_sa_children(
        self, processor: CRMProcessor, sa_config: CalculationConfig
    ):
        """SA: an explicit cash amount equal to the FAC_1 subtree EAD at the
        grandparent drives every descendant's ead_after_collateral to zero."""
        anc = ["FAC_2", "FAC_1"]
        exposures = [
            _with_ancestors(_sa_exposure("L1", drawn=600.0, facility_ref="FAC_2"), anc),
            _with_ancestors(_sa_exposure("L2", drawn=400.0, facility_ref="FAC_2"), anc),
            _with_ancestors(
                _sa_exposure("C1", drawn=0.0, nominal=200.0, facility_ref="FAC_2"), anc
            ),
        ]
        # Subtree ead_for_crm = 600 + 400 + 200 (contingent at 100% nominal) = 1200
        result = _run_crm(
            processor,
            sa_config,
            exposures,
            [_cash_collateral("FAC_1", market_value=1200.0, beneficiary_type="facility")],
        )
        for ref in ("L1", "L2", "C1"):
            row = result.filter(pl.col("exposure_reference") == ref)
            assert row["ead_after_collateral"][0] == pytest.approx(0.0, abs=0.01), ref

    def test_subtree_pledge_does_not_leak_to_sibling_subtree(
        self, processor: CRMProcessor, sa_config: CalculationConfig
    ):
        """A pledge at a specific facility covers only that facility's subtree,
        not a sibling facility sharing the same root."""
        exposures = [
            _with_ancestors(
                _sa_exposure("EA", drawn=500.0, facility_ref="FAC_A"), ["FAC_A", "ROOT"]
            ),
            _with_ancestors(
                _sa_exposure("EB", drawn=300.0, facility_ref="FAC_B"), ["FAC_B", "ROOT"]
            ),
        ]
        result = _run_crm(
            processor,
            sa_config,
            exposures,
            [_cash_collateral("FAC_A", market_value=500.0, beneficiary_type="facility")],
        )
        ea = result.filter(pl.col("exposure_reference") == "EA")
        eb = result.filter(pl.col("exposure_reference") == "EB")
        assert ea["ead_after_collateral"][0] == pytest.approx(0.0, abs=0.01)
        # Sibling under FAC_B must be untouched by the FAC_A pledge
        assert eb["ead_after_collateral"][0] == pytest.approx(300.0, abs=0.01)

    def test_root_pledge_covers_all_subtrees(
        self, processor: CRMProcessor, sa_config: CalculationConfig
    ):
        """A pledge at the shared root covers both child subtrees pro-rata."""
        exposures = [
            _with_ancestors(
                _sa_exposure("EA", drawn=500.0, facility_ref="FAC_A"), ["FAC_A", "ROOT"]
            ),
            _with_ancestors(
                _sa_exposure("EB", drawn=300.0, facility_ref="FAC_B"), ["FAC_B", "ROOT"]
            ),
        ]
        result = _run_crm(
            processor,
            sa_config,
            exposures,
            [_cash_collateral("ROOT", market_value=800.0, beneficiary_type="facility")],
        )
        for ref in ("EA", "EB"):
            row = result.filter(pl.col("exposure_reference") == ref)
            assert row["ead_after_collateral"][0] == pytest.approx(0.0, abs=0.01), ref

    def test_stacked_pledges_at_two_levels_sum(
        self, processor: CRMProcessor, sa_config: CalculationConfig
    ):
        """Pledges at both the parent and grandparent stack on the descendant."""
        anc = ["FAC_2", "FAC_1"]
        exposures = [_with_ancestors(_sa_exposure("L1", drawn=1000.0, facility_ref="FAC_2"), anc)]
        result = _run_crm(
            processor,
            sa_config,
            exposures,
            [
                _cash_collateral("FAC_2", market_value=400.0, beneficiary_type="facility"),
                _cash_collateral("FAC_1", market_value=600.0, beneficiary_type="facility"),
            ],
        )
        row = result.filter(pl.col("exposure_reference") == "L1")
        # 400 (parent) + 600 (grandparent) = 1000 fully covers the 1000 drawn
        assert row["ead_after_collateral"][0] == pytest.approx(0.0, abs=0.01)

    def test_grandparent_cash_pledge_cascades_under_basel_3_1(
        self, b31_processor: CRMProcessor, b31_firb_config: CalculationConfig
    ):
        """The cascade also holds under Basel 3.1 (PS1/26 Art. 230(1) FCM): a
        grandparent cash pledge_percentage=1.0 fully secures every FIRB
        descendant under FAC_2."""
        anc = ["FAC_2", "FAC_1"]
        exposures = [
            _with_ancestors(_irb_exposure("L1", drawn=600.0, facility_ref="FAC_2"), anc),
            _with_ancestors(_irb_exposure("L2", drawn=400.0, facility_ref="FAC_2"), anc),
            _with_ancestors(
                _irb_exposure("C1", drawn=0.0, nominal=200.0, facility_ref="FAC_2"), anc
            ),
        ]
        result = _run_crm(
            b31_processor,
            b31_firb_config,
            exposures,
            [
                _cash_collateral(
                    "FAC_1",
                    market_value=None,
                    beneficiary_type="facility",
                    pledge_percentage=1.0,
                )
            ],
        )
        for ref in ("L1", "L2", "C1"):
            row = result.filter(pl.col("exposure_reference") == ref)
            assert row["lgd_post_crm"][0] == pytest.approx(0.0), ref
            assert row["collateral_coverage_pct"][0] == pytest.approx(100.0, abs=0.5), ref

    def test_b31_grandparent_cascade_matches_direct_parent_baseline(
        self, b31_processor: CRMProcessor, b31_firb_config: CalculationConfig
    ):
        """Framework-agnostic: under Basel 3.1 a real-estate pledge at the
        grandparent yields byte-identical coverage/LGD to the same pledge at the
        exposure's direct facility (any reduction is the B31 RE haircut, not a
        cascade artefact)."""

        def _run(pledge_at: str, ancestors: list[str]) -> dict:
            exposures = [
                _with_ancestors(_irb_exposure("L1", drawn=600.0, facility_ref="FAC_2"), ancestors),
                _with_ancestors(_irb_exposure("L2", drawn=400.0, facility_ref="FAC_2"), ancestors),
            ]
            re_collateral = {
                "collateral_reference": f"COLL_{pledge_at}",
                "beneficiary_reference": pledge_at,
                "beneficiary_type": "facility",
                "collateral_type": "real_estate",
                "market_value": None,
                "currency": "GBP",
                "issuer_cqs": None,
                "issuer_type": None,
                "residual_maturity_years": None,
                "is_eligible_financial_collateral": False,
                "pledge_percentage": 1.0,
                "collateral_maturity_date": None,
            }
            result = _run_crm(b31_processor, b31_firb_config, exposures, [re_collateral])
            return {
                r["exposure_reference"]: r["lgd_post_crm"]
                for r in result.select("exposure_reference", "lgd_post_crm").to_dicts()
            }

        direct = _run("FAC_2", ["FAC_2"])  # single-level baseline
        grand = _run("FAC_1", ["FAC_2", "FAC_1"])  # nested grandparent pledge
        assert grand == pytest.approx(direct)
