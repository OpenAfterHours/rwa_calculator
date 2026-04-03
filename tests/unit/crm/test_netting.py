"""
Tests for on-balance sheet netting (CRR Article 195).

When a loan has a negative drawn amount (credit balance / deposit) and is
covered by a netting agreement, the absolute value of that negative balance
generates synthetic cash collateral that reduces sibling exposures in the
same facility — pro-rata by EAD.

Covers:
- No netting flag → no synthetic collateral generated
- SA: single negative + single positive loan in same facility → EAD reduced
- SA: single negative + two positive loans → pro-rata allocation
- FIRB: netting reduces LGD (cash collateral path), not direct EAD
- Mixed netting / non-netting in facility → only netting-eligible benefit
- Currency mismatch → FX haircut applied
- No negative-drawn netting loans → no synthetic collateral
- Netting exceeds exposure → EAD floored at 0
- Missing column (backward compat) → returns None
- No parent_facility_reference → standalone loans excluded
- Multiple negative-drawn loans pool together
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.bundles import (
    ClassifiedExposuresBundle,
    CounterpartyLookup,
)
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


# =============================================================================
# Helpers
# =============================================================================


def _netting_exposure(
    ref: str,
    drawn: float,
    facility_ref: str = "FAC_01",
    cp_ref: str = "CP001",
    currency: str = "GBP",
    has_netting: bool = True,
    approach: str = ApproachType.SA.value,
    root_facility_ref: str | None = None,
    netting_facility_ref: str | None = None,
) -> dict:
    """Create an exposure row with netting fields."""
    row: dict = {
        "exposure_reference": ref,
        "counterparty_reference": cp_ref,
        "exposure_class": "corporate",
        "approach": approach,
        "drawn_amount": drawn,
        "interest": 0.0,
        "nominal_amount": 0.0,
        "risk_type": "FR",
        "lgd": 0.45,
        "seniority": "senior",
        "parent_facility_reference": facility_ref,
        "currency": currency,
        "maturity_date": None,
        "has_netting_agreement": has_netting,
    }
    if root_facility_ref is not None:
        row["root_facility_reference"] = root_facility_ref
    if netting_facility_ref is not None:
        row["netting_facility_reference"] = netting_facility_ref
    return row


def _make_bundle(
    exposures: pl.LazyFrame,
    collateral: pl.LazyFrame | None = None,
) -> ClassifiedExposuresBundle:
    """Build a ClassifiedExposuresBundle with optional collateral."""
    empty_cp = pl.LazyFrame(schema={"counterparty_reference": pl.String, "entity_type": pl.String})
    empty_mappings = pl.LazyFrame(
        schema={
            "child_counterparty_reference": pl.String,
            "parent_counterparty_reference": pl.String,
        }
    )
    empty_ultimate = pl.LazyFrame(
        schema={
            "counterparty_reference": pl.String,
            "ultimate_parent_reference": pl.String,
            "hierarchy_depth": pl.Int32,
        }
    )
    empty_ri = pl.LazyFrame(
        schema={
            "counterparty_reference": pl.String,
            "cqs": pl.Int8,
            "rating_type": pl.String,
        }
    )
    return ClassifiedExposuresBundle(
        all_exposures=exposures,
        sa_exposures=pl.LazyFrame(),
        irb_exposures=pl.LazyFrame(),
        slotting_exposures=pl.LazyFrame(),
        equity_exposures=None,
        counterparty_lookup=CounterpartyLookup(
            counterparties=empty_cp,
            parent_mappings=empty_mappings,
            ultimate_parent_mappings=empty_ultimate,
            rating_inheritance=empty_ri,
        ),
        collateral=collateral,
        guarantees=None,
        provisions=None,
    )


def _run_crm(
    processor: CRMProcessor,
    config: CalculationConfig,
    exposure_rows: list[dict],
    collateral: pl.LazyFrame | None = None,
) -> pl.DataFrame:
    """Run CRM pipeline and return collected result."""
    exposures = pl.LazyFrame(exposure_rows)
    bundle = _make_bundle(exposures, collateral)
    result = processor.get_crm_adjusted_bundle(bundle, config)
    df: pl.DataFrame = result.exposures.collect()
    return df


# =============================================================================
# Tests: _generate_netting_collateral
# =============================================================================


class TestNettingCollateralGeneration:
    """Unit tests for _generate_netting_collateral method."""

    def test_missing_column_returns_none(self, processor: CRMProcessor):
        """Backward compat: no has_netting_agreement column → None."""
        exposures = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001"],
                "drawn_amount": [1000.0],
                "ead_gross": [1000.0],
                "parent_facility_reference": ["FAC_01"],
                "currency": ["GBP"],
                "maturity_date": [None],
            }
        )
        result = processor._generate_netting_collateral(exposures)
        assert result is None

    def test_no_negative_drawn_returns_none(self, processor: CRMProcessor):
        """All positive drawn amounts → no synthetic collateral."""
        exposures = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001"],
                "drawn_amount": [1000.0],
                "ead_gross": [1000.0],
                "parent_facility_reference": ["FAC_01"],
                "currency": ["GBP"],
                "maturity_date": [None],
                "has_netting_agreement": [True],
            }
        )
        result = processor._generate_netting_collateral(exposures)
        assert result is not None  # returns a LazyFrame (may be empty)
        df = result.collect()
        assert len(df) == 0

    def test_no_parent_facility_excluded(self, processor: CRMProcessor):
        """Standalone loans (no parent_facility_reference) are excluded."""
        exposures = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001", "EXP002"],
                "drawn_amount": [-500.0, 1000.0],
                "ead_gross": [0.0, 1000.0],
                "parent_facility_reference": [None, None],
                "currency": ["GBP", "GBP"],
                "maturity_date": [None, None],
                "has_netting_agreement": [True, True],
            }
        )
        result = processor._generate_netting_collateral(exposures)
        assert result is not None
        df = result.collect()
        assert len(df) == 0

    def test_single_negative_single_positive(self, processor: CRMProcessor):
        """One negative + one positive → one synthetic collateral row."""
        exposures = pl.LazyFrame(
            {
                "exposure_reference": ["NEG01", "POS01"],
                "drawn_amount": [-200.0, 1000.0],
                "ead_gross": [0.0, 1000.0],
                "parent_facility_reference": ["FAC_01", "FAC_01"],
                "currency": ["GBP", "GBP"],
                "maturity_date": [None, None],
                "has_netting_agreement": [True, True],
            }
        )
        result = processor._generate_netting_collateral(exposures)
        df = result.collect()

        assert len(df) == 1
        row = df.row(0, named=True)
        assert row["collateral_reference"] == "NETTING_POS01"
        assert row["beneficiary_reference"] == "POS01"
        assert row["beneficiary_type"] == "loan"
        assert row["collateral_type"] == "cash"
        assert row["market_value"] == pytest.approx(200.0)
        assert row["is_eligible_financial_collateral"] is True
        assert row["is_eligible_irb_collateral"] is True
        assert row["currency"] == "GBP"

    def test_pro_rata_allocation(self, processor: CRMProcessor):
        """Netting pool split pro-rata by ead_gross among positive siblings."""
        exposures = pl.LazyFrame(
            {
                "exposure_reference": ["NEG01", "POS01", "POS02"],
                "drawn_amount": [-300.0, 600.0, 400.0],
                "ead_gross": [0.0, 600.0, 400.0],
                "parent_facility_reference": ["FAC_01", "FAC_01", "FAC_01"],
                "currency": ["GBP", "GBP", "GBP"],
                "maturity_date": [None, None, None],
                "has_netting_agreement": [True, True, True],
            }
        )
        result = processor._generate_netting_collateral(exposures)
        df = result.collect().sort("beneficiary_reference")

        assert len(df) == 2
        # POS01 gets 300 * (600/1000) = 180
        pos01 = df.filter(pl.col("beneficiary_reference") == "POS01")
        assert pos01["market_value"][0] == pytest.approx(180.0)
        # POS02 gets 300 * (400/1000) = 120
        pos02 = df.filter(pl.col("beneficiary_reference") == "POS02")
        assert pos02["market_value"][0] == pytest.approx(120.0)

    def test_multiple_negatives_pool_together(self, processor: CRMProcessor):
        """Multiple negative-drawn loans sum into one netting pool per facility."""
        exposures = pl.LazyFrame(
            {
                "exposure_reference": ["NEG01", "NEG02", "POS01"],
                "drawn_amount": [-100.0, -200.0, 1000.0],
                "ead_gross": [0.0, 0.0, 1000.0],
                "parent_facility_reference": ["FAC_01", "FAC_01", "FAC_01"],
                "currency": ["GBP", "GBP", "GBP"],
                "maturity_date": [None, None, None],
                "has_netting_agreement": [True, True, True],
            }
        )
        result = processor._generate_netting_collateral(exposures)
        df = result.collect()

        assert len(df) == 1
        # Pool = 100 + 200 = 300, all goes to POS01
        assert df["market_value"][0] == pytest.approx(300.0)

    def test_non_netting_siblings_still_benefit(self, processor: CRMProcessor):
        """All facility siblings benefit, even without their own netting flag."""
        exposures = pl.LazyFrame(
            {
                "exposure_reference": ["NEG01", "POS01", "POS02"],
                "drawn_amount": [-200.0, 1000.0, 500.0],
                "ead_gross": [0.0, 1000.0, 500.0],
                "parent_facility_reference": ["FAC_01", "FAC_01", "FAC_01"],
                "currency": ["GBP", "GBP", "GBP"],
                "maturity_date": [None, None, None],
                "has_netting_agreement": [True, True, False],
            }
        )
        result = processor._generate_netting_collateral(exposures)
        df = result.collect().sort("beneficiary_reference")

        # Both POS01 and POS02 benefit (netting agreement is on NEG01)
        assert len(df) == 2
        pos01 = df.filter(pl.col("beneficiary_reference") == "POS01")
        assert pos01["market_value"][0] == pytest.approx(200.0 * 1000 / 1500)
        pos02 = df.filter(pl.col("beneficiary_reference") == "POS02")
        assert pos02["market_value"][0] == pytest.approx(200.0 * 500 / 1500)


# =============================================================================
# Tests: End-to-end netting via CRM pipeline
# =============================================================================


class TestNettingSAEndToEnd:
    """SA pipeline: netting reduces EAD via synthetic cash collateral."""

    def test_sa_ead_reduced_by_netting(self, processor: CRMProcessor, sa_config: CalculationConfig):
        """SA: negative-drawn loan reduces sibling's EAD."""
        rows = [
            _netting_exposure("NEG01", drawn=-200.0),
            _netting_exposure("POS01", drawn=1000.0),
        ]
        df = _run_crm(processor, sa_config, rows)

        neg = df.filter(pl.col("exposure_reference") == "NEG01")
        pos = df.filter(pl.col("exposure_reference") == "POS01")

        # Negative-drawn: EAD = 0 (floored by drawn_for_ead)
        assert neg["ead_final"][0] == pytest.approx(0.0)
        # Positive-drawn: EAD reduced by 200 (cash collateral, 0% haircut)
        assert pos["ead_final"][0] == pytest.approx(800.0, abs=1.0)

    def test_sa_pro_rata_two_positive(self, processor: CRMProcessor, sa_config: CalculationConfig):
        """SA: netting pool split pro-rata across two positive siblings."""
        rows = [
            _netting_exposure("NEG01", drawn=-300.0),
            _netting_exposure("POS01", drawn=600.0),
            _netting_exposure("POS02", drawn=400.0),
        ]
        df = _run_crm(processor, sa_config, rows)

        pos01 = df.filter(pl.col("exposure_reference") == "POS01")
        pos02 = df.filter(pl.col("exposure_reference") == "POS02")

        # POS01: 600 - 300*(600/1000) = 600 - 180 = 420
        assert pos01["ead_final"][0] == pytest.approx(420.0, abs=1.0)
        # POS02: 400 - 300*(400/1000) = 400 - 120 = 280
        assert pos02["ead_final"][0] == pytest.approx(280.0, abs=1.0)

    def test_netting_exceeds_exposure_floors_at_zero(
        self, processor: CRMProcessor, sa_config: CalculationConfig
    ):
        """SA: netting pool exceeds exposure → EAD floored at 0."""
        rows = [
            _netting_exposure("NEG01", drawn=-500.0),
            _netting_exposure("POS01", drawn=100.0),
        ]
        df = _run_crm(processor, sa_config, rows)

        pos = df.filter(pl.col("exposure_reference") == "POS01")
        assert pos["ead_final"][0] == pytest.approx(0.0)

    def test_all_facility_siblings_benefit(
        self, processor: CRMProcessor, sa_config: CalculationConfig
    ):
        """All facility siblings benefit from netting, not just netting-flagged ones."""
        rows = [
            _netting_exposure("NEG01", drawn=-200.0, has_netting=True),
            _netting_exposure("POS01", drawn=1000.0, has_netting=True),
            _netting_exposure("POS02", drawn=500.0, has_netting=False),
        ]
        df = _run_crm(processor, sa_config, rows)

        pos01 = df.filter(pl.col("exposure_reference") == "POS01")
        pos02 = df.filter(pl.col("exposure_reference") == "POS02")

        # Pool=200 split pro-rata: POS01 gets 200*1000/1500=133.33, POS02 gets 200*500/1500=66.67
        assert pos01["ead_final"][0] == pytest.approx(1000.0 - 133.33, abs=1.0)
        assert pos02["ead_final"][0] == pytest.approx(500.0 - 66.67, abs=1.0)

    def test_currency_mismatch_fx_haircut(
        self, processor: CRMProcessor, sa_config: CalculationConfig
    ):
        """FX mismatch between negative and positive loans → 8% FX haircut."""
        rows = [
            _netting_exposure("NEG01", drawn=-1000.0, currency="EUR"),
            _netting_exposure("POS01", drawn=1000.0, currency="GBP"),
        ]
        df = _run_crm(processor, sa_config, rows)

        pos = df.filter(pl.col("exposure_reference") == "POS01")
        # Cash collateral in EUR, exposure in GBP → 8% FX haircut
        # Effective collateral = 1000 * (1 - 0.08) = 920
        # EAD = 1000 - 920 = 80
        assert pos["ead_final"][0] == pytest.approx(80.0, abs=1.0)

    def test_no_netting_flag_no_change(self, processor: CRMProcessor, sa_config: CalculationConfig):
        """No netting agreement → pipeline unchanged."""
        rows = [
            _netting_exposure("NEG01", drawn=-200.0, has_netting=False),
            _netting_exposure("POS01", drawn=1000.0, has_netting=False),
        ]
        df = _run_crm(processor, sa_config, rows)

        pos = df.filter(pl.col("exposure_reference") == "POS01")
        # No netting → EAD = drawn_amount (no collateral benefit)
        assert pos["ead_final"][0] == pytest.approx(1000.0)

    def test_netting_pool_exceeds_total_positive_ead(
        self, processor: CRMProcessor, sa_config: CalculationConfig
    ):
        """Pool exceeds total positive EAD → all siblings get ead_final=0."""
        rows = [
            _netting_exposure("LOAN_01", drawn=-100.0, has_netting=True),
            _netting_exposure("LOAN_02", drawn=10.0, has_netting=False),
            _netting_exposure("LOAN_03", drawn=20.0, has_netting=False),
            _netting_exposure("LOAN_04", drawn=5.0, has_netting=False),
        ]
        df = _run_crm(processor, sa_config, rows)

        for ref in ["LOAN_02", "LOAN_03", "LOAN_04"]:
            row = df.filter(pl.col("exposure_reference") == ref)
            assert row["ead_final"][0] == pytest.approx(0.0), f"{ref} should be fully netted"


class TestNettingFacilityHierarchy:
    """Netting across facility hierarchy levels."""

    def test_netting_via_root_facility(self, processor: CRMProcessor, sa_config: CalculationConfig):
        """Loans under different sub-facilities net via shared root facility."""
        rows = [
            _netting_exposure(
                "NEG01",
                drawn=-200.0,
                has_netting=True,
                facility_ref="FAC_SUB1",
                root_facility_ref="FAC_ROOT",
            ),
            _netting_exposure(
                "POS01",
                drawn=600.0,
                has_netting=False,
                facility_ref="FAC_SUB1",
                root_facility_ref="FAC_ROOT",
            ),
            _netting_exposure(
                "POS02",
                drawn=400.0,
                has_netting=False,
                facility_ref="FAC_SUB2",
                root_facility_ref="FAC_ROOT",
            ),
        ]
        df = _run_crm(processor, sa_config, rows)

        pos01 = df.filter(pl.col("exposure_reference") == "POS01")
        pos02 = df.filter(pl.col("exposure_reference") == "POS02")

        # Pool=200 split pro-rata via root: POS01=200*600/1000=120, POS02=200*400/1000=80
        assert pos01["ead_final"][0] == pytest.approx(480.0, abs=1.0)
        assert pos02["ead_final"][0] == pytest.approx(320.0, abs=1.0)

    def test_explicit_netting_facility_overrides_root(
        self, processor: CRMProcessor, sa_config: CalculationConfig
    ):
        """Explicit netting_facility_reference takes priority over root."""
        rows = [
            # Netting agreement is with FAC_SUB1 specifically, not root
            _netting_exposure(
                "NEG01",
                drawn=-200.0,
                has_netting=True,
                facility_ref="FAC_SUB1",
                root_facility_ref="FAC_ROOT",
                netting_facility_ref="FAC_SUB1",
            ),
            _netting_exposure(
                "POS01",
                drawn=1000.0,
                has_netting=False,
                facility_ref="FAC_SUB1",
                root_facility_ref="FAC_ROOT",
                netting_facility_ref=None,
            ),
            # POS02 is under a different sub-facility — should NOT benefit
            _netting_exposure(
                "POS02",
                drawn=500.0,
                has_netting=False,
                facility_ref="FAC_SUB2",
                root_facility_ref="FAC_ROOT",
                netting_facility_ref=None,
            ),
        ]
        df = _run_crm(processor, sa_config, rows)

        pos01 = df.filter(pl.col("exposure_reference") == "POS01")
        pos02 = df.filter(pl.col("exposure_reference") == "POS02")

        # Only POS01 shares netting group FAC_SUB1 with NEG01
        # POS02's netting group = root (FAC_ROOT) — different from NEG01's FAC_SUB1
        assert pos01["ead_final"][0] == pytest.approx(800.0, abs=1.0)
        assert pos02["ead_final"][0] == pytest.approx(500.0)

    def test_no_root_falls_back_to_parent(
        self, processor: CRMProcessor, sa_config: CalculationConfig
    ):
        """Without root_facility_reference, netting falls back to parent facility."""
        rows = [
            _netting_exposure("NEG01", drawn=-200.0, has_netting=True),
            _netting_exposure("POS01", drawn=1000.0, has_netting=False),
        ]
        df = _run_crm(processor, sa_config, rows)

        pos = df.filter(pl.col("exposure_reference") == "POS01")
        # Falls back to parent_facility_reference (FAC_01) — same as before
        assert pos["ead_final"][0] == pytest.approx(800.0, abs=1.0)


class TestNettingFIRBEndToEnd:
    """FIRB pipeline: netting reduces LGD via cash collateral path."""

    def test_firb_netting_reduces_lgd(
        self, processor: CRMProcessor, firb_config: CalculationConfig
    ):
        """FIRB: netting generates cash collateral → LGD reduction."""
        rows = [
            _netting_exposure("NEG01", drawn=-200.0, approach=ApproachType.FIRB.value),
            _netting_exposure("POS01", drawn=1000.0, approach=ApproachType.FIRB.value),
        ]
        df = _run_crm(processor, firb_config, rows)

        pos = df.filter(pl.col("exposure_reference") == "POS01")
        # Cash collateral has LGD = 0% in FIRB supervisory LGD table
        # With 200 cash against 1000 EAD, LGD should be < 45% (senior unsecured)
        assert pos["lgd_post_crm"][0] < 0.45


class TestNettingMissingColumn:
    """Backward compatibility when has_netting_agreement column is absent."""

    def test_missing_netting_column_pipeline_works(
        self, processor: CRMProcessor, sa_config: CalculationConfig
    ):
        """Pipeline works normally when has_netting_agreement column is missing."""
        rows = [
            {
                "exposure_reference": "EXP001",
                "counterparty_reference": "CP001",
                "exposure_class": "corporate",
                "approach": ApproachType.SA.value,
                "drawn_amount": 1000.0,
                "interest": 0.0,
                "nominal_amount": 0.0,
                "risk_type": "FR",
                "lgd": 0.45,
                "seniority": "senior",
                "parent_facility_reference": "FAC_01",
                "currency": "GBP",
                "maturity_date": None,
                # no has_netting_agreement column
            }
        ]
        df = _run_crm(processor, sa_config, rows)
        assert len(df) == 1
        assert df["ead_final"][0] == pytest.approx(1000.0)
