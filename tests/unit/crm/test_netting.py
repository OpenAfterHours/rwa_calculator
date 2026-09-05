"""
Tests for on-balance sheet netting (CRR Article 195/219).

When a loan has a negative drawn amount (credit balance / deposit) and carries a
``netting_agreement_reference``, the absolute value of that negative balance
generates synthetic cash collateral that reduces other exposures carrying the
SAME reference — pro-rata by drawn EAD.

The netting agreement reference ALONE defines the set-off perimeter. Pools are
keyed on (netting_agreement_reference, currency) and siblings match on the
agreement reference only, so a deposit nets every positive-drawn loan sibling
under that agreement regardless of which counterparty within the agreement
holds which leg — across facilities and across counterparties alike. This
reverses the earlier (agreement, counterparty) keying by operator decision
dated 2026-09-04; the behaviour is gated by the cited pack Feature
``on_bs_netting_perimeter_is_agreement`` (enabled under both regimes), and
disabling that Feature restores the single-counterparty keying exactly.

A cross-counterparty (or null-counterparty) agreement still raises one CRM016
WARNING per agreement, but as an AUDIT-TRAIL record rather than a refusal: the
offset IS applied, and the warning records that Art. 205(a) enforceability
across all parties to the agreement must be evidenced.

Covers:
- No netting_agreement_reference column → no synthetic collateral generated
- SA: single negative + single positive loan sharing a reference → EAD reduced
- SA: single negative + two positive loans → pro-rata allocation
- Cross-counterparty netting APPLIES under a shared agreement + CRM016 audit
  record; same-counterparty cross-facility netting still applies; a
  null-counterparty deposit nets and still warns
- Feature disabled → the (agreement, counterparty) keying is restored
- Same facility but different/absent reference → no netting
- FIRB: netting reduces LGD (cash collateral path), not direct EAD
- Currency mismatch → FX haircut applied
- Netting exceeds exposure → EAD floored at 0
- Drawn-only scope (CRR Art. 219): contingents / facility_undrawn excluded
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

import polars as pl
import pytest
from tests.fixtures.resolved_bundle import make_classified_bundle
from tests.unit.crm._crm_bundles import empty_counterparty_lookup

from rwa_calc.contracts.bundles import ClassifiedExposuresBundle
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.contracts.errors import ERROR_CROSS_COUNTERPARTY_NETTING
from rwa_calc.domain.enums import ApproachType, PermissionMode
from rwa_calc.engine.crm.processor import CRMProcessor
from rwa_calc.rulebook import RulepackV0
from rwa_calc.rulebook.model import Citation, Feature

if TYPE_CHECKING:
    from rwa_calc.contracts.bundles import CRMAdjustedBundle
    from rwa_calc.rulebook.resolve import ResolvedRulepack

# The agreement-perimeter Feature. Named once so the disabled-control test and
# the engine cannot drift apart on the spelling.
NETTING_PERIMETER_FEATURE = "on_bs_netting_perimeter_is_agreement"

# ``pack`` is REQUIRED on both netting entry points: the Art. 195 set-off
# perimeter is a cited Feature with no engine-side default, because a default
# would fail open to the wider, RWA-reducing perimeter. The direct-call tests
# below therefore supply the CRR pack explicitly. None of their frames sets
# ``counterparty_reference``, so every row lands in one group under either
# perimeter and their expected values are perimeter-independent.
_PACK = RulepackV0.from_config(CalculationConfig.crr(reporting_date=date(2024, 12, 31))).pack

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


# -----------------------------------------------------------------------------
# Cross-counterparty perimeter fixture
#
# One netting agreement, two counterparties. The values live at module scope so
# the C11 adequacy assertions below read exactly what the rows are built from,
# rather than restating them.
# -----------------------------------------------------------------------------

AGREEMENT = "AGR1"
DEPOSIT_CP = "CPA"
LOAN_CP = "CPB"
DEPOSIT_BALANCE = -200.0
LOAN_DRAWN = 1000.0
NETTED_EAD = 800.0  # 1000 - 200; synthetic cash collateral carries a 0% haircut


def _cross_counterparty_rows(deposit_cp: str | None = DEPOSIT_CP) -> list[dict]:
    """A deposit and a loan under ONE agreement, held by DIFFERENT counterparties."""
    return [
        _netting_exposure(
            "NEG01",
            drawn=DEPOSIT_BALANCE,
            cp_ref=deposit_cp,
            facility_ref="FAC_A",
            agreement_ref=AGREEMENT,
        ),
        _netting_exposure(
            "POS01",
            drawn=LOAN_DRAWN,
            cp_ref=LOAN_CP,
            facility_ref="FAC_B",
            agreement_ref=AGREEMENT,
        ),
    ]


def _same_counterparty_rows() -> list[dict]:
    """Control: the same two legs, both held by the deposit's counterparty."""
    return [
        _netting_exposure(
            "NEG01",
            drawn=DEPOSIT_BALANCE,
            cp_ref=DEPOSIT_CP,
            facility_ref="FAC_A",
            agreement_ref=AGREEMENT,
        ),
        _netting_exposure(
            "POS01",
            drawn=LOAN_DRAWN,
            cp_ref=DEPOSIT_CP,
            facility_ref="FAC_B",
            agreement_ref=AGREEMENT,
        ),
    ]


def _assert_cross_counterparty_fixture_is_adequate() -> None:
    """C11 adequacy: this fixture must be able to tell the two perimeters apart.

    Every assertion here is a claim the test silently depends on. If any fails,
    the agreement perimeter and the (agreement, counterparty) perimeter agree on
    this data and the test proves nothing about which one the engine applies.
    """
    assert DEPOSIT_CP != LOAN_CP, (
        f"deposit and loan are both held by {LOAN_CP!r}, so the agreement perimeter "
        f"and the (agreement, counterparty) perimeter agree on this fixture and it "
        f"cannot distinguish them"
    )
    assert DEPOSIT_BALANCE < 0.0, (
        f"deposit balance {DEPOSIT_BALANCE} is not negative, so no netting pool is "
        f"generated and the loan keeps its full EAD under either perimeter"
    )
    assert abs(DEPOSIT_BALANCE) < LOAN_DRAWN, (
        f"loan {LOAN_DRAWN} does not exceed the deposit {abs(DEPOSIT_BALANCE)}, so a "
        f"netted EAD would floor at 0 - indistinguishable from a fully-consumed pool"
    )


def _pack_with_agreement_perimeter_disabled(config: CalculationConfig) -> ResolvedRulepack:
    """The run's resolved pack with the agreement-perimeter Feature flipped off."""
    return RulepackV0.from_config(config).pack.with_overrides(
        **{
            NETTING_PERIMETER_FEATURE: Feature(
                name=NETTING_PERIMETER_FEATURE,
                enabled=False,
                citation=Citation("CRR", "195", "agreement perimeter disabled for test"),
            )
        }
    )


def _ead(result: CRMAdjustedBundle, ref: str) -> float:
    """The post-CRM EAD of one exposure in a CRM bundle."""
    df = result.exposures.collect().filter(pl.col("exposure_reference") == ref)
    assert len(df) == 1, f"expected exactly one row for {ref}, got {len(df)}"
    value: float | None = df["ead_final"][0]
    assert value is not None, (
        f"{ref} published a null ead_final; a null and a legitimate zero are "
        f"different claims and only one of them is a netted exposure"
    )
    return value


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
        result = processor._generate_netting_collateral(exposures, pack=_PACK)
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
        result = processor._generate_netting_collateral(exposures, pack=_PACK)
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
        result = processor._generate_netting_collateral(exposures, pack=_PACK)
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
        result = processor._generate_netting_collateral(exposures, pack=_PACK)
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
        result = processor._generate_netting_collateral(exposures, pack=_PACK)
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
        result = processor._generate_netting_collateral(exposures, pack=_PACK)
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
        result = processor._generate_netting_collateral(exposures, pack=_PACK)
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
        result = processor._generate_netting_collateral(exposures, pack=_PACK)
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
    """The netting AGREEMENT is the perimeter - not the facility, not the counterparty."""

    def test_cross_counterparty_netting_applies_under_shared_agreement(
        self, processor: CRMProcessor, sa_config: CalculationConfig
    ):
        """A deposit nets a DIFFERENT counterparty's loan under the same agreement.

        Art. 195/205(a)/219 describe on-balance-sheet netting of reciprocal cash
        balances and the drawn-on-drawn mechanics without confining the perimeter
        to a single counterparty pair; by operator decision (2026-09-04) the
        netting agreement reference alone is the boundary. CPA's 200 credit
        balance therefore offsets CPB's 1000 loan under AGR1, giving the same
        EAD 800 as the same-counterparty control below.
        """
        # Arrange
        _assert_cross_counterparty_fixture_is_adequate()
        rows = _cross_counterparty_rows()

        # Act
        df = _run_crm(processor, sa_config, rows)

        # Assert
        pos = df.filter(pl.col("exposure_reference") == "POS01")
        assert pos["ead_final"][0] == pytest.approx(NETTED_EAD, abs=1.0)

    def test_same_counterparty_netting_still_applies(
        self, processor: CRMProcessor, sa_config: CalculationConfig
    ):
        """Control: a deposit nets a loan to the SAME counterparty across facilities.

        Both legs are counterparty CPA under agreement AGR1; the 200 credit
        balance offsets the 1000 loan, EAD 800. This case is unchanged by the
        perimeter move - it is what pins the reversal to the cross-counterparty
        leg rather than to netting in general.
        """
        # Arrange
        rows = _same_counterparty_rows()

        # Act
        df = _run_crm(processor, sa_config, rows)

        # Assert
        pos = df.filter(pl.col("exposure_reference") == "POS01")
        assert pos["ead_final"][0] == pytest.approx(NETTED_EAD, abs=1.0)

    def test_cross_counterparty_netting_emits_crm016(
        self, processor: CRMProcessor, sa_config: CalculationConfig
    ):
        """A spanning agreement raises exactly one CRM016 - as an AUDIT record.

        CRM016 stays a WARNING (``ErrorSeverity`` has no INFO level) and keeps its
        Art. 195 reference, but it now records an offset that WAS applied rather
        than one refused: enforceability against every party to the agreement
        (Art. 205(a)) has to be evidenced separately. So the same run must show
        the offset applied, and the message must no longer call it "disallowed".
        """
        # Arrange
        _assert_cross_counterparty_fixture_is_adequate()
        bundle = _make_bundle(pl.LazyFrame(_cross_counterparty_rows()))

        # Act
        result = processor.get_crm_unified_bundle(bundle, sa_config)

        # Assert
        warnings = [e for e in result.crm_errors if e.code == ERROR_CROSS_COUNTERPARTY_NETTING]
        assert len(warnings) == 1
        assert warnings[0].regulatory_reference == "CRR Art. 195"
        assert "disallowed" not in warnings[0].message.lower(), (
            f"CRM016 still describes the offset as refused: {warnings[0].message!r}"
        )
        assert "across 2 counterparties" in warnings[0].message, (
            f"CRM016 does not say HOW MANY counterparties the agreement spans; the "
            f"count is what makes it an audit record rather than a bare flag, and "
            f"it is what an Art. 205(a) reviewer scopes the evidence from: "
            f"{warnings[0].message!r}"
        )
        assert _ead(result, "POS01") == pytest.approx(NETTED_EAD, abs=1.0), (
            "the warning fired but the offset was not applied - CRM016 is the audit "
            "record of an APPLIED cross-counterparty offset, not a refusal"
        )

    def test_null_counterparty_deposit_nets_under_agreement_perimeter(
        self, processor: CRMProcessor, sa_config: CalculationConfig
    ):
        """A null counterparty no longer blocks netting - the join never reads it.

        Under the agreement perimeter the sibling join keys on
        ``netting_agreement_reference`` alone, so a deposit whose
        ``counterparty_reference`` is null still nets its AGR1 siblings: EAD 800.
        A null counterparty remains part of the CRM016 trigger, because it is
        exactly the case where enforceability cannot be read off the data.
        """
        # Arrange
        rows = _cross_counterparty_rows(deposit_cp=None)
        assert rows[0]["counterparty_reference"] is None, (
            "the deposit leg carries a counterparty, so this fixture does not "
            "exercise the null-counterparty path at all"
        )
        assert rows[1]["counterparty_reference"] is not None, (
            "the loan leg is also null-keyed, so both legs would share the null "
            "group and the test could not show the null being ignored"
        )
        bundle = _make_bundle(
            pl.LazyFrame(rows, schema_overrides={"counterparty_reference": pl.String})
        )

        # Act
        result = processor.get_crm_unified_bundle(bundle, sa_config)

        # Assert
        warnings = [e for e in result.crm_errors if e.code == ERROR_CROSS_COUNTERPARTY_NETTING]
        assert _ead(result, "POS01") == pytest.approx(NETTED_EAD, abs=1.0)
        assert len(warnings) == 1
        assert "unconfirmed (null) counterparty" in warnings[0].message, (
            f"CRM016 does not distinguish the null-counterparty case from an "
            f"ordinary multi-counterparty span, so the audit record cannot say "
            f"which party the enforceability evidence is missing for: "
            f"{warnings[0].message!r}"
        )

    def test_pool_allocates_pro_rata_across_three_counterparties(
        self, processor: CRMProcessor, sa_config: CalculationConfig
    ):
        """The pool is split pro-rata over ALL agreement siblings, whoever owes them.

        Three counterparties under AGR1: CPA holds a 300 deposit, CPB a 600 loan,
        CPC a 400 loan. Widening the perimeter also widens the pro-rata
        DENOMINATOR - the allocation basis becomes the agreement's total drawn
        (1000), not one counterparty's. A denominator still keyed on counterparty
        would hand each loan the whole pool, so this is the case the
        single-beneficiary tests above cannot see.

        The conservation assertion is the load-bearing one: the total EAD relief
        must equal the pool exactly. An over-allocating denominator relieves more
        than the deposit funds; an under-allocating one silently drops a sibling.
        """
        # Arrange
        rows = [
            _netting_exposure("NEG01", drawn=-300.0, cp_ref="CPA", agreement_ref=AGREEMENT),
            _netting_exposure("POS01", drawn=600.0, cp_ref="CPB", agreement_ref=AGREEMENT),
            _netting_exposure("POS02", drawn=400.0, cp_ref="CPC", agreement_ref=AGREEMENT),
        ]
        assert len({r["counterparty_reference"] for r in rows}) == 3, (
            "the three legs do not name three counterparties, so the agreement "
            "denominator and the counterparty denominator would coincide"
        )

        # Act
        result = processor.get_crm_unified_bundle(_make_bundle(pl.LazyFrame(rows)), sa_config)

        # Assert
        pos01 = _ead(result, "POS01")
        pos02 = _ead(result, "POS02")
        assert pos01 == pytest.approx(420.0, abs=1.0)  # 600 - 300*(600/1000)
        assert pos02 == pytest.approx(280.0, abs=1.0)  # 400 - 300*(400/1000)
        assert (600.0 - pos01) + (400.0 - pos02) == pytest.approx(300.0, abs=1.0), (
            "the allocated relief does not sum to the 300 netting pool - the "
            "pro-rata denominator is not the agreement's total drawn"
        )
        warnings = [e for e in result.crm_errors if e.code == ERROR_CROSS_COUNTERPARTY_NETTING]
        assert len(warnings) == 1
        assert "across 3 counterparties" in warnings[0].message, (
            f"CRM016 records the wrong span for a three-counterparty agreement; the "
            f"count must be the DISTINCT counterparties under the reference, not a "
            f"constant: {warnings[0].message!r}"
        )

    def test_feature_disabled_restores_single_counterparty_keying(
        self, processor: CRMProcessor, sa_config: CalculationConfig
    ):
        """Feature off -> pools key on (agreement, counterparty) exactly as before.

        The perimeter move is gated by the cited pack Feature
        ``on_bs_netting_perimeter_is_agreement``. With it disabled the
        cross-counterparty loan keeps its full 1000 EAD and the same-counterparty
        loan still nets to 800 - the pre-reversal behaviour.

        The third assertion is what stops this being a test that passes in both
        states (LESSONS C1.11): running the SAME cross-counterparty rows on the
        run's default pack must net them. Without it, "disabled" and "enabled"
        would be indistinguishable and the Feature could be a no-op.
        """
        # Arrange
        _assert_cross_counterparty_fixture_is_adequate()
        disabled = _pack_with_agreement_perimeter_disabled(sa_config)

        # Act
        cross_disabled = processor.get_crm_unified_bundle(
            _make_bundle(pl.LazyFrame(_cross_counterparty_rows())), sa_config, pack=disabled
        )
        same_disabled = processor.get_crm_unified_bundle(
            _make_bundle(pl.LazyFrame(_same_counterparty_rows())), sa_config, pack=disabled
        )
        cross_default = processor.get_crm_unified_bundle(
            _make_bundle(pl.LazyFrame(_cross_counterparty_rows())), sa_config
        )

        # Assert
        assert _ead(cross_disabled, "POS01") == pytest.approx(LOAN_DRAWN, abs=1.0)
        assert _ead(same_disabled, "POS01") == pytest.approx(NETTED_EAD, abs=1.0)
        assert _ead(cross_default, "POS01") == pytest.approx(NETTED_EAD, abs=1.0), (
            "the default pack did not net across counterparties, so the disabled "
            "assertions above hold in both states and the Feature guards nothing"
        )

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
        result = processor._generate_netting_collateral(exposures, pack=_PACK)
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
        result = processor._generate_netting_collateral(exposures, pack=_PACK)
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
        result = processor._generate_netting_collateral(exposures, pack=_PACK)
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
        result = processor._generate_netting_collateral(exposures, pack=_PACK)
        assert result is not None
        df = result.collect()
        # Pool = 300; only LOAN01 eligible. Contingent + facility_undrawn excluded.
        assert len(df) == 1
        row = df.row(0, named=True)
        assert row["beneficiary_reference"] == "LOAN01"
        assert row["market_value"] == pytest.approx(300.0)
