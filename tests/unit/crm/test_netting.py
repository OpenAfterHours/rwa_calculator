"""
Tests for on-balance sheet netting (CRR Article 195/219).

When a loan has a negative drawn amount (credit balance / deposit) and carries a
``netting_agreement_reference``, the absolute value of that negative balance
generates synthetic cash collateral that reduces other exposures carrying the
SAME reference — pro-rata by drawn EAD.

Netting pools are keyed on (netting_agreement_reference, currency,
counterparty_reference): the agreement is the set-off boundary, the
counterparty is the Art. 195 eligibility boundary. A deposit nets only
exposures to the SAME counterparty under the agreement — across facilities is
fine (reciprocal balances with one counterparty), across counterparties is
not (P1.238). A cross-counterparty agreement raises a CRM016 warning and the
disallowed offset is not applied; a null counterparty_reference never matches
a pool (conservatively excluded + warned).

Covers:
- No netting_agreement_reference column → no synthetic collateral generated
- SA: single negative + single positive loan sharing a reference → EAD reduced
- SA: single negative + two positive loans → pro-rata allocation
- Cross-counterparty netting disallowed (Art. 195) + CRM016; same-counterparty
  cross-facility netting still applies; null-counterparty deposit excluded
- Same facility but different/absent reference → no netting
- FIRB: netting reduces LGD (cash collateral path), not direct EAD
- Currency mismatch → FX haircut applied
- Netting exceeds exposure → EAD floored at 0
- Drawn-only scope (CRR Art. 219): contingents / facility_undrawn excluded
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest
from tests.fixtures.resolved_bundle import make_classified_bundle
from tests.unit.crm._crm_bundles import empty_counterparty_lookup

from rwa_calc.contracts.bundles import ClassifiedExposuresBundle
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.contracts.errors import ERROR_CROSS_COUNTERPARTY_NETTING
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
    cp_ref: str | None = "CP001",
    currency: str = "GBP",
    agreement_ref: str | None = "AGR01",
    approach: str = ApproachType.SA.value,
) -> dict:
    """Create an exposure row carrying a netting agreement reference.

    ``agreement_ref`` defaults to a shared value so the common single-facility
    case nets; pass ``None`` to opt an exposure out of netting entirely.
    """
    return {
        "exposure_reference": ref,
        "exposure_type": "loan",
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
        "original_currency": currency,
        "maturity_date": None,
        "netting_agreement_reference": agreement_ref,
    }


def _make_bundle(
    exposures: pl.LazyFrame,
    collateral: pl.LazyFrame | None = None,
) -> ClassifiedExposuresBundle:
    """Build a ClassifiedExposuresBundle with optional collateral."""
    return make_classified_bundle(
        all_exposures=exposures,
        equity_exposures=None,
        counterparty_lookup=empty_counterparty_lookup(),
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
    result = processor.get_crm_unified_bundle(bundle, config)
    df: pl.DataFrame = result.exposures.collect()
    return df


# =============================================================================
# Tests: _generate_netting_collateral
# =============================================================================


class TestNettingCollateralGeneration:
    """Unit tests for _generate_netting_collateral method."""

    def test_missing_column_returns_none(self, processor: CRMProcessor):
        """No netting_agreement_reference column → None."""
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
                "netting_agreement_reference": ["AGR01"],
            }
        )
        result = processor._generate_netting_collateral(exposures)
        assert result is not None  # returns a LazyFrame (may be empty)
        df = result.collect()
        assert len(df) == 0

    def test_no_parent_facility_still_nets_via_agreement_ref(self, processor: CRMProcessor):
        """Facility is irrelevant: standalone loans net via a shared reference."""
        exposures = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001", "EXP002"],
                "drawn_amount": [-500.0, 1000.0],
                "ead_gross": [0.0, 1000.0],
                "parent_facility_reference": [None, None],
                "currency": ["GBP", "GBP"],
                "maturity_date": [None, None],
                "netting_agreement_reference": ["AGR01", "AGR01"],
            }
        )
        result = processor._generate_netting_collateral(exposures)
        assert result is not None
        df = result.collect()
        # Pool = 500 from EXP001, fully benefits EXP002 — no facility needed.
        assert len(df) == 1
        assert df["beneficiary_reference"][0] == "EXP002"
        assert df["market_value"][0] == pytest.approx(500.0)

    def test_single_negative_single_positive(self, processor: CRMProcessor):
        """One negative + one positive sharing a reference → one synthetic row."""
        exposures = pl.LazyFrame(
            {
                "exposure_reference": ["NEG01", "POS01"],
                "drawn_amount": [-200.0, 1000.0],
                "ead_gross": [0.0, 1000.0],
                "parent_facility_reference": ["FAC_01", "FAC_01"],
                "currency": ["GBP", "GBP"],
                "maturity_date": [None, None],
                "netting_agreement_reference": ["AGR01", "AGR01"],
            }
        )
        result = processor._generate_netting_collateral(exposures)
        assert result is not None
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
        """Netting pool split pro-rata by drawn portion among positive siblings."""
        exposures = pl.LazyFrame(
            {
                "exposure_reference": ["NEG01", "POS01", "POS02"],
                "drawn_amount": [-300.0, 600.0, 400.0],
                "ead_gross": [0.0, 600.0, 400.0],
                "parent_facility_reference": ["FAC_01", "FAC_01", "FAC_01"],
                "currency": ["GBP", "GBP", "GBP"],
                "maturity_date": [None, None, None],
                "netting_agreement_reference": ["AGR01", "AGR01", "AGR01"],
            }
        )
        result = processor._generate_netting_collateral(exposures)
        assert result is not None
        df = result.collect().sort("beneficiary_reference")

        assert len(df) == 2
        # POS01 gets 300 * (600/1000) = 180
        pos01 = df.filter(pl.col("beneficiary_reference") == "POS01")
        assert pos01["market_value"][0] == pytest.approx(180.0)
        # POS02 gets 300 * (400/1000) = 120
        pos02 = df.filter(pl.col("beneficiary_reference") == "POS02")
        assert pos02["market_value"][0] == pytest.approx(120.0)

    def test_multiple_negatives_pool_together(self, processor: CRMProcessor):
        """Multiple negative-drawn loans sum into one pool per reference."""
        exposures = pl.LazyFrame(
            {
                "exposure_reference": ["NEG01", "NEG02", "POS01"],
                "drawn_amount": [-100.0, -200.0, 1000.0],
                "ead_gross": [0.0, 0.0, 1000.0],
                "parent_facility_reference": ["FAC_01", "FAC_01", "FAC_01"],
                "currency": ["GBP", "GBP", "GBP"],
                "maturity_date": [None, None, None],
                "netting_agreement_reference": ["AGR01", "AGR01", "AGR01"],
            }
        )
        result = processor._generate_netting_collateral(exposures)
        assert result is not None
        df = result.collect()

        assert len(df) == 1
        # Pool = 100 + 200 = 300, all goes to POS01
        assert df["market_value"][0] == pytest.approx(300.0)

    def test_all_siblings_sharing_reference_benefit(self, processor: CRMProcessor):
        """Every exposure carrying the same reference benefits pro-rata."""
        exposures = pl.LazyFrame(
            {
                "exposure_reference": ["NEG01", "POS01", "POS02"],
                "drawn_amount": [-200.0, 1000.0, 500.0],
                "ead_gross": [0.0, 1000.0, 500.0],
                "parent_facility_reference": ["FAC_01", "FAC_01", "FAC_01"],
                "currency": ["GBP", "GBP", "GBP"],
                "maturity_date": [None, None, None],
                "netting_agreement_reference": ["AGR01", "AGR01", "AGR01"],
            }
        )
        result = processor._generate_netting_collateral(exposures)
        assert result is not None
        df = result.collect().sort("beneficiary_reference")

        assert len(df) == 2
        pos01 = df.filter(pl.col("beneficiary_reference") == "POS01")
        assert pos01["market_value"][0] == pytest.approx(200.0 * 1000 / 1500)
        pos02 = df.filter(pl.col("beneficiary_reference") == "POS02")
        assert pos02["market_value"][0] == pytest.approx(200.0 * 500 / 1500)

    def test_different_reference_excluded(self, processor: CRMProcessor):
        """A sibling carrying a different reference does NOT benefit."""
        exposures = pl.LazyFrame(
            {
                "exposure_reference": ["NEG01", "POS01", "POS02"],
                "drawn_amount": [-200.0, 1000.0, 500.0],
                "ead_gross": [0.0, 1000.0, 500.0],
                "parent_facility_reference": ["FAC_01", "FAC_01", "FAC_01"],
                "currency": ["GBP", "GBP", "GBP"],
                "maturity_date": [None, None, None],
                # POS02 is under a DIFFERENT agreement despite the same facility.
                "netting_agreement_reference": ["AGR01", "AGR01", "AGR02"],
            }
        )
        result = processor._generate_netting_collateral(exposures)
        assert result is not None
        df = result.collect()

        # Only POS01 shares AGR01 with the deposit; full pool of 200 to POS01.
        assert len(df) == 1
        assert df["beneficiary_reference"][0] == "POS01"
        assert df["market_value"][0] == pytest.approx(200.0)


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

    def test_all_siblings_with_reference_benefit(
        self, processor: CRMProcessor, sa_config: CalculationConfig
    ):
        """Every exposure carrying the shared reference benefits from netting."""
        rows = [
            _netting_exposure("NEG01", drawn=-200.0),
            _netting_exposure("POS01", drawn=1000.0),
            _netting_exposure("POS02", drawn=500.0),
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
        """FX mismatch between negative and positive loans → 8% FX haircut.

        P1.186: pre-built synthetic collateral with liquidation_period_days=10 is
        passed directly so this test asserts the 10-day capital-market FX haircut
        (8%). It tests FX haircut propagation through netting logic, not
        liquidation-period scaling. The new pipeline default is 20-day (11.314%).
        """
        # P1.186: pass pre-built netting collateral with liquidation_period_days=10
        # to pin the 10-day FX haircut (8%). The negative EUR loan (NEG01) nets
        # against the GBP positive loan (POS01), producing synthetic EUR cash collateral.
        prebuilt_collateral = pl.LazyFrame(
            {
                "collateral_reference": ["NETTING_POS01"],
                "collateral_type": ["cash"],
                "currency": ["EUR"],  # source currency from negative loan
                "market_value": [1000.0],
                "beneficiary_type": ["loan"],
                "beneficiary_reference": ["POS01"],
                "issuer_cqs": [None],
                "issuer_type": [None],
                "residual_maturity_years": [None],
                "is_eligible_financial_collateral": [True],
                "liquidation_period_days": [10],  # P1.186: explicit 10-day
            },
            schema={
                "collateral_reference": pl.String,
                "collateral_type": pl.String,
                "currency": pl.String,
                "market_value": pl.Float64,
                "beneficiary_type": pl.String,
                "beneficiary_reference": pl.String,
                "issuer_cqs": pl.Int8,
                "issuer_type": pl.String,
                "residual_maturity_years": pl.Float64,
                "is_eligible_financial_collateral": pl.Boolean,
                "liquidation_period_days": pl.Int32,
            },
        )
        # Use agreement_ref=None to disable internal netting generation;
        # pre-built collateral above provides the equivalent cash collateral.
        no_netting_rows = [
            _netting_exposure("NEG01", drawn=-1000.0, currency="EUR", agreement_ref=None),
            _netting_exposure("POS01", drawn=1000.0, currency="GBP", agreement_ref=None),
        ]
        df = _run_crm(processor, sa_config, no_netting_rows, collateral=prebuilt_collateral)

        pos = df.filter(pl.col("exposure_reference") == "POS01")
        # Cash collateral in EUR, exposure in GBP → 8% FX haircut (10-day)
        # Effective collateral = 1000 * (1 - 0.08) = 920
        # EAD = 1000 - 920 = 80
        assert pos["ead_final"][0] == pytest.approx(80.0, abs=1.0)

    def test_no_agreement_ref_no_change(
        self, processor: CRMProcessor, sa_config: CalculationConfig
    ):
        """No netting agreement reference → pipeline unchanged."""
        rows = [
            _netting_exposure("NEG01", drawn=-200.0, agreement_ref=None),
            _netting_exposure("POS01", drawn=1000.0, agreement_ref=None),
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
            _netting_exposure("LOAN_01", drawn=-100.0),
            _netting_exposure("LOAN_02", drawn=10.0),
            _netting_exposure("LOAN_03", drawn=20.0),
            _netting_exposure("LOAN_04", drawn=5.0),
        ]
        df = _run_crm(processor, sa_config, rows)

        for ref in ["LOAN_02", "LOAN_03", "LOAN_04"]:
            row = df.filter(pl.col("exposure_reference") == ref)
            assert row["ead_final"][0] == pytest.approx(0.0), f"{ref} should be fully netted"


class TestNettingByAgreementReference:
    """Netting follows the agreement reference, not facility or counterparty."""

    def test_cross_counterparty_netting_disallowed(
        self, processor: CRMProcessor, sa_config: CalculationConfig
    ):
        """P1.238 — Art. 195: a deposit does NOT net a loan to a DIFFERENT counterparty.

        On-balance-sheet netting is limited to mutual claims between the institution
        and a single counterparty (CRR/PS1-26 Art. 195). A credit balance for
        counterparty A under agreement AGR1 must not offset a loan to counterparty B
        under the same agreement — even across facilities. POS01 keeps its full EAD.
        """
        rows = [
            _netting_exposure(
                "NEG01", drawn=-200.0, cp_ref="CPA", facility_ref="FAC_A", agreement_ref="AGR1"
            ),
            _netting_exposure(
                "POS01", drawn=1000.0, cp_ref="CPB", facility_ref="FAC_B", agreement_ref="AGR1"
            ),
        ]
        df = _run_crm(processor, sa_config, rows)

        pos = df.filter(pl.col("exposure_reference") == "POS01")
        assert pos["ead_final"][0] == pytest.approx(1000.0, abs=1.0)

    def test_same_counterparty_netting_still_applies(
        self, processor: CRMProcessor, sa_config: CalculationConfig
    ):
        """Control: a deposit DOES net a loan to the SAME counterparty (Art. 195).

        Both legs are counterparty CPA under agreement AGR1 (across facilities);
        the £200 credit balance offsets the £1000 loan → EAD £800.
        """
        rows = [
            _netting_exposure(
                "NEG01", drawn=-200.0, cp_ref="CPA", facility_ref="FAC_A", agreement_ref="AGR1"
            ),
            _netting_exposure(
                "POS01", drawn=1000.0, cp_ref="CPA", facility_ref="FAC_B", agreement_ref="AGR1"
            ),
        ]
        df = _run_crm(processor, sa_config, rows)

        pos = df.filter(pl.col("exposure_reference") == "POS01")
        assert pos["ead_final"][0] == pytest.approx(800.0, abs=1.0)

    def test_cross_counterparty_netting_emits_crm016(
        self, processor: CRMProcessor, sa_config: CalculationConfig
    ):
        """A netting agreement spanning >1 counterparty raises one CRM016 warning."""
        rows = [
            _netting_exposure(
                "NEG01", drawn=-200.0, cp_ref="CPA", facility_ref="FAC_A", agreement_ref="AGR1"
            ),
            _netting_exposure(
                "POS01", drawn=1000.0, cp_ref="CPB", facility_ref="FAC_B", agreement_ref="AGR1"
            ),
        ]
        bundle = _make_bundle(pl.LazyFrame(rows))
        result = processor.get_crm_unified_bundle(bundle, sa_config)

        warnings = [e for e in result.crm_errors if e.code == ERROR_CROSS_COUNTERPARTY_NETTING]
        assert len(warnings) == 1

    def test_null_counterparty_deposit_excluded(
        self, processor: CRMProcessor, sa_config: CalculationConfig
    ):
        """P1.238 — a deposit whose counterparty is NULL cannot confirm reciprocity.

        Netting benefit requires POSITIVE confirmation of a same-counterparty
        relationship (Art. 195), so a null-counterparty deposit is conservatively
        excluded — the loan keeps its full EAD — and a CRM016 warning is raised.
        """
        rows = [
            _netting_exposure("NEG01", drawn=-200.0, cp_ref=None, agreement_ref="AGR1"),
            _netting_exposure("POS01", drawn=1000.0, cp_ref="CPA", agreement_ref="AGR1"),
        ]
        bundle = _make_bundle(
            pl.LazyFrame(rows, schema_overrides={"counterparty_reference": pl.String})
        )
        result = processor.get_crm_unified_bundle(bundle, sa_config)

        df = result.exposures.collect()
        pos = df.filter(pl.col("exposure_reference") == "POS01")
        warnings = [e for e in result.crm_errors if e.code == ERROR_CROSS_COUNTERPARTY_NETTING]

        assert pos["ead_final"][0] == pytest.approx(1000.0, abs=1.0)
        assert len(warnings) == 1

    def test_only_matching_reference_nets_in_same_facility(
        self, processor: CRMProcessor, sa_config: CalculationConfig
    ):
        """Same facility, different references → only the matching loan nets."""
        rows = [
            _netting_exposure("NEG01", drawn=-200.0, facility_ref="FAC_01", agreement_ref="AGR1"),
            _netting_exposure("POS01", drawn=1000.0, facility_ref="FAC_01", agreement_ref="AGR1"),
            # POS02 shares the facility but a different agreement → must NOT net.
            _netting_exposure("POS02", drawn=500.0, facility_ref="FAC_01", agreement_ref="AGR2"),
        ]
        df = _run_crm(processor, sa_config, rows)

        pos01 = df.filter(pl.col("exposure_reference") == "POS01")
        pos02 = df.filter(pl.col("exposure_reference") == "POS02")

        assert pos01["ead_final"][0] == pytest.approx(800.0, abs=1.0)
        assert pos02["ead_final"][0] == pytest.approx(500.0)

    def test_same_facility_no_reference_no_netting(
        self, processor: CRMProcessor, sa_config: CalculationConfig
    ):
        """Without an agreement reference, shared facility does NOT net."""
        rows = [
            _netting_exposure("NEG01", drawn=-200.0, facility_ref="FAC_01", agreement_ref=None),
            _netting_exposure("POS01", drawn=1000.0, facility_ref="FAC_01", agreement_ref=None),
        ]
        df = _run_crm(processor, sa_config, rows)

        pos = df.filter(pl.col("exposure_reference") == "POS01")
        assert pos["ead_final"][0] == pytest.approx(1000.0)


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
    """Pipeline works when the netting_agreement_reference column is absent."""

    def test_missing_netting_column_pipeline_works(
        self, processor: CRMProcessor, sa_config: CalculationConfig
    ):
        """Pipeline works normally when netting_agreement_reference is missing."""
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
                # no netting_agreement_reference column
            }
        ]
        df = _run_crm(processor, sa_config, rows)
        assert len(df) == 1
        assert df["ead_final"][0] == pytest.approx(1000.0)


# =============================================================================
# Tests: Drawn-only scope (CRR Art. 219)
# =============================================================================


class TestNettingDrawnOnlyScope:
    """CRR Art. 219: OBS netting is drawn-on-drawn cash netting only.

    Contingents and synthetic facility_undrawn rows are off-balance-sheet
    and ineligible to receive the netting benefit even when they carry the
    agreement reference. Pro-rata allocation among eligible loan siblings is
    by drawn portion (on_bs_for_ead), not by ead_for_crm.
    """

    def test_contingent_excluded_from_netting(self, processor: CRMProcessor):
        """Contingent off-BS rows must NOT receive netting benefit."""
        # Mirrors post-classifier state: exposure_type + on_bs_for_ead present.
        exposures = pl.LazyFrame(
            {
                "exposure_reference": ["NEG01", "LOAN01", "CONT01"],
                "drawn_amount": [-300.0, 600.0, 0.0],
                "interest": [0.0, 0.0, 0.0],
                "on_bs_for_ead": [0.0, 600.0, 0.0],
                "ead_for_crm": [0.0, 600.0, 400.0],
                "ead_gross": [0.0, 600.0, 400.0],
                "exposure_type": ["loan", "loan", "contingent"],
                "parent_facility_reference": ["FAC_01", "FAC_01", "FAC_01"],
                "currency": ["GBP", "GBP", "GBP"],
                "maturity_date": [None, None, None],
                "netting_agreement_reference": ["AGR01", "AGR01", "AGR01"],
            }
        )
        result = processor._generate_netting_collateral(exposures)
        assert result is not None
        df = result.collect()
        # Pool = 300; only LOAN01 is an eligible beneficiary.
        assert len(df) == 1
        row = df.row(0, named=True)
        assert row["beneficiary_reference"] == "LOAN01"
        assert row["market_value"] == pytest.approx(300.0)

    def test_facility_undrawn_excluded_from_netting(self, processor: CRMProcessor):
        """Synthetic facility_undrawn rows must NOT receive netting benefit."""
        exposures = pl.LazyFrame(
            {
                "exposure_reference": ["NEG01", "LOAN01", "FAC_UNDRAWN_01"],
                "drawn_amount": [-200.0, 500.0, 0.0],
                "interest": [0.0, 0.0, 0.0],
                "on_bs_for_ead": [0.0, 500.0, 0.0],
                "ead_for_crm": [0.0, 500.0, 1000.0],  # large off-BS headroom
                "ead_gross": [0.0, 500.0, 750.0],
                "exposure_type": ["loan", "loan", "facility_undrawn"],
                "parent_facility_reference": ["FAC_01", "FAC_01", "FAC_01"],
                "currency": ["GBP", "GBP", "GBP"],
                "maturity_date": [None, None, None],
                "netting_agreement_reference": ["AGR01", "AGR01", "AGR01"],
            }
        )
        result = processor._generate_netting_collateral(exposures)
        assert result is not None
        df = result.collect()
        # Pool = 200; full benefit to LOAN01, facility_undrawn excluded.
        assert len(df) == 1
        row = df.row(0, named=True)
        assert row["beneficiary_reference"] == "LOAN01"
        assert row["market_value"] == pytest.approx(200.0)

    def test_pro_rata_uses_drawn_not_ead_for_crm(self, processor: CRMProcessor):
        """Pro-rata basis is on_bs_for_ead, not ead_for_crm."""
        # LOAN_A: 400 drawn, no off-BS.   LOAN_B: 100 drawn, 900 off-BS nominal.
        # OLD (buggy) basis ead_for_crm = 400 vs 1000 -> 57.14 / 142.86
        # NEW (correct) basis on_bs_for_ead = 400 vs 100 -> 160 / 40
        exposures = pl.LazyFrame(
            {
                "exposure_reference": ["NEG01", "LOAN_A", "LOAN_B"],
                "drawn_amount": [-200.0, 400.0, 100.0],
                "interest": [0.0, 0.0, 0.0],
                "on_bs_for_ead": [0.0, 400.0, 100.0],
                "ead_for_crm": [0.0, 400.0, 1000.0],
                "ead_gross": [0.0, 400.0, 775.0],
                "exposure_type": ["loan", "loan", "loan"],
                "parent_facility_reference": ["FAC_01", "FAC_01", "FAC_01"],
                "currency": ["GBP", "GBP", "GBP"],
                "maturity_date": [None, None, None],
                "netting_agreement_reference": ["AGR01", "AGR01", "AGR01"],
            }
        )
        result = processor._generate_netting_collateral(exposures)
        assert result is not None
        df = result.collect().sort("beneficiary_reference")
        loan_a = df.filter(pl.col("beneficiary_reference") == "LOAN_A")["market_value"][0]
        loan_b = df.filter(pl.col("beneficiary_reference") == "LOAN_B")["market_value"][0]
        assert loan_a == pytest.approx(160.0)
        assert loan_b == pytest.approx(40.0)

    def test_mixed_facility_only_drawn_loan_benefits(self, processor: CRMProcessor):
        """Reference mixing all three exposure types: only the drawn loan benefits."""
        exposures = pl.LazyFrame(
            {
                "exposure_reference": ["NEG01", "LOAN01", "CONT01", "FAC_U_01"],
                "drawn_amount": [-300.0, 500.0, 0.0, 0.0],
                "interest": [0.0, 0.0, 0.0, 0.0],
                "on_bs_for_ead": [0.0, 500.0, 0.0, 0.0],
                "ead_for_crm": [0.0, 500.0, 800.0, 1200.0],
                "ead_gross": [0.0, 500.0, 400.0, 600.0],
                "exposure_type": ["loan", "loan", "contingent", "facility_undrawn"],
                "parent_facility_reference": ["FAC_01"] * 4,
                "currency": ["GBP"] * 4,
                "maturity_date": [None] * 4,
                "netting_agreement_reference": ["AGR01"] * 4,
            }
        )
        result = processor._generate_netting_collateral(exposures)
        assert result is not None
        df = result.collect()
        # Pool = 300; only LOAN01 eligible. Contingent + facility_undrawn excluded.
        assert len(df) == 1
        row = df.row(0, named=True)
        assert row["beneficiary_reference"] == "LOAN01"
        assert row["market_value"] == pytest.approx(300.0)
