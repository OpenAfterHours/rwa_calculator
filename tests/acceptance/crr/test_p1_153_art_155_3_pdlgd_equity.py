"""
P1.153 — CRR Art. 155(3): PD/LGD equity approach (scenario CRR-J21).

Under CRR Art. 155(3), institutions with supervisory permission may apply
the PD/LGD approach to equity exposures using supervisory parameters from Art. 165:
    - PD floor:  Art. 165(1)(c) exchange-traded equity = 0.40%
    - LGD:       Art. 165(2) non-diversified-PE = 90%
    - M:         Art. 165(3) = 5 years (fixed)
Combined with the IRB corporate K formula (Art. 153(1)) and 1.06 scaling
(Art. 153), the worked exposure yields risk_weight ≈ 1.918731 (191.87%).

Hand calculation (CRR-J21):
    PD floor    = 0.0040  [Art. 165(1)(c)]
    LGD         = 0.90    [Art. 165(2)]
    M           = 5.0     [Art. 165(3)]
    scaling     = 1.06    [Art. 153]
    EAD         = 1,000,000
    f(PD)       = (1 - exp(-50*0.0040)) / (1 - exp(-50)) = 0.18126924692
    R           = 0.12*f + 0.24*(1-f) = 0.21824769037
    G(PD)       = N^-1(0.0040) = -2.65206980587
    conditional_pd = N[(G(PD) + sqrt(R/(1-R))*G(0.999)) / sqrt(1-R)] = 0.0859757
    K           = 0.90*0.0859757 - 0.0040*0.90 = 0.07367139
    b           = (0.11852 - 0.05478*ln(0.0040))^2 = 0.17722890
    MA          = (1 + (5-2.5)*b) / (1 - 1.5*b) = 1.96561
    RW          = K*12.5*1.06*MA = 1.918731  (191.87%)
    RWEA        = 1,918,731
    EL          = 0.0040*0.90*1,000,000 = 3,600
    cap check   = EL*12.5 + RWEA = 1,966,549 <= EAD*12.5 = 12,500,000 -> cap NOT binding

References:
    CRR Art. 155(3): PD/LGD approach for equity; 1.5x scaling absent default data
    CRR Art. 165(1)(c): PD floor exchange-traded equity = 0.40%
    CRR Art. 165(2): supervisory LGD = 90% (non-diversified-PE)
    CRR Art. 165(3): M = 5 years (fixed)
    CRR Art. 153(1): corporate IRB K formula
    CRR Art. 153: 1.06 scaling factor
"""

from __future__ import annotations

import dataclasses
from datetime import date
from decimal import Decimal

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.equity.calculator import EquityCalculator
from tests.fixtures.p1_153.p1_153 import (
    EXPECTED_CORRELATION,
    EXPECTED_EL,
    EXPECTED_K,
    EXPECTED_MATURITY_ADJUSTMENT,
    EXPECTED_RWA,
    EXPECTED_RISK_WEIGHT,
    LGD_SUPERVISORY,
    MATURITY_YEARS,
    PD_FLOOR,
    SCALING_FACTOR,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCENARIO_ID = "CRR-J21 / P1.153"
EAD = 1_000_000.0

# What IRB_SIMPLE exchange-traded equity would produce today (Art. 155(2)(a))
# = 290% risk weight => RWA = 2,900,000
_CURRENT_IRB_SIMPLE_EXCHANGE_TRADED_RW = 2.90
_CURRENT_IRB_SIMPLE_EXCHANGE_TRADED_RWA = 2_900_000.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_config_with_pdlgd_flag() -> CalculationConfig:
    """
    Build a CRR IRB config, adding equity_pd_lgd=True when that field exists.

    TODAY (pre-Wave-4): ``CalculationConfig`` does not have an ``equity_pd_lgd``
    field. We guard with ``hasattr`` so the test does not raise AttributeError.
    The test still reaches the assertion and fails on the golden numbers because
    the engine routes through IRB_SIMPLE (290%) instead of PD/LGD (191.87%).

    POST-WAVE-4: the engine-implementer adds ``equity_pd_lgd: bool = False`` to
    ``CalculationConfig``. ``hasattr`` returns True and the replace call activates
    the PD/LGD branch, making the test pass.
    """
    base = CalculationConfig.crr(
        reporting_date=date(2026, 6, 30),
        permission_mode=PermissionMode.IRB,
    )
    if hasattr(base, "equity_pd_lgd"):
        return dataclasses.replace(base, equity_pd_lgd=True)
    return base


def _build_equity_exposure_lf() -> pl.LazyFrame:
    """
    Build the EQ-PDLGD-001 exposure LazyFrame for the PD/LGD equity test.

    has_default_definition_info=True: Art. 155(3) — institution has adequate
    default-definition data, so the 1.5x scaling does NOT apply. This column
    is PROPOSED-NEW (Wave-4 adds it to EQUITY_EXPOSURE_SCHEMA); we pass it
    forward-compatibly. The equity calculator will ignore unknown columns today
    and process the column after Wave-4 adds support.
    """
    return pl.DataFrame(
        {
            "exposure_reference": ["EQ-PDLGD-001"],
            "counterparty_reference": ["CP-PDLGD-001"],
            "equity_type": ["exchange_traded"],
            "is_exchange_traded": [True],
            "ead_final": [EAD],
            "is_speculative": [False],
            "is_government_supported": [False],
            "is_diversified_portfolio": [False],
            "has_default_definition_info": [True],
        }
    ).lazy()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def crr_irb_pdlgd_config() -> CalculationConfig:
    """CRR IRB config with equity_pd_lgd=True (forward-compatible guard)."""
    return _build_config_with_pdlgd_flag()


@pytest.fixture(scope="module")
def equity_calculator() -> EquityCalculator:
    """EquityCalculator instance."""
    return EquityCalculator()


@pytest.fixture(scope="module")
def pdlgd_equity_result(
    equity_calculator: EquityCalculator,
    crr_irb_pdlgd_config: CalculationConfig,
) -> dict:
    """
    Calculate equity RWA for EQ-PDLGD-001 via calculate_branch.

    Returns the first (only) result row as a dict.
    """
    lf = _build_equity_exposure_lf()
    return equity_calculator.calculate_branch(lf, crr_irb_pdlgd_config).collect().to_dicts()[0]


# ---------------------------------------------------------------------------
# P1.153 — CRR Art. 155(3) PD/LGD Equity Tests
# ---------------------------------------------------------------------------


class TestP1153_CRRart1553_PdLgdEquityApproach:
    """
    P1.153 (CRR-J21): CRR Art. 155(3) PD/LGD equity approach.

    Exchange-traded equity, EAD=1,000,000, PD floor=0.40%, LGD=90%, M=5y,
    scaling=1.06 (Art. 153). Expected risk_weight ≈ 1.918731; RWA ≈ 1,918,731.

    PRE-Wave-4 failure: engine returns IRB_SIMPLE (290% = 2.90 RW, 2,900,000 RWA)
    because _determine_approach lacks the PD_LGD branch.
    POST-Wave-4 pass: equity_pd_lgd=True activates the new PD/LGD branch (≈1.918731).
    """

    def test_p1_153_crr_j21_risk_weight(
        self,
        pdlgd_equity_result: dict,
    ) -> None:
        """
        P1.153: exchange-traded equity PD/LGD risk_weight must be ≈ 1.918731.

        Arrange: equity_type=exchange_traded, is_exchange_traded=True,
                 EAD=1,000,000, has_default_definition_info=True,
                 CRR IRB + equity_pd_lgd=True config.
        Act: EquityCalculator.calculate_branch (PD/LGD branch).
        Assert: risk_weight ≈ 1.918731 (K*12.5*1.06*MA, Art. 155(3)/165).
        """
        # Act — result from fixture
        actual_rw = pdlgd_equity_result["risk_weight"]

        # Assert
        assert actual_rw == pytest.approx(EXPECTED_RISK_WEIGHT, rel=1e-4), (
            f"{SCENARIO_ID}: PD/LGD risk_weight must be ≈ {EXPECTED_RISK_WEIGHT:.5f} "
            f"(K*12.5*1.06*MA via Art. 155(3)/165). "
            f"Got {actual_rw:.5f}. "
            f"Pre-Wave-4 engine returns IRB_SIMPLE rate "
            f"{_CURRENT_IRB_SIMPLE_EXCHANGE_TRADED_RW:.2f} (Art. 155(2)(a) 290%)."
        )

    def test_p1_153_crr_j21_rwa(
        self,
        pdlgd_equity_result: dict,
    ) -> None:
        """
        P1.153: exchange-traded equity PD/LGD RWA must be ≈ 1,921,549.

        Arrange: EAD=1,000,000, risk_weight≈1.918731 (Art. 155(3)/165).
        Act: EquityCalculator.calculate_branch.
        Assert: rwa ≈ 1,918,731.
        """
        # Act — result from fixture
        actual_rwa = pdlgd_equity_result.get("rwa") or pdlgd_equity_result.get("rwa_final")

        # Assert
        assert actual_rwa == pytest.approx(EXPECTED_RWA, rel=1e-4), (
            f"{SCENARIO_ID}: RWA = risk_weight * EAD ≈ 1,921,549. "
            f"Got {actual_rwa:,.0f}. "
            f"Pre-Wave-4 engine returns {_CURRENT_IRB_SIMPLE_EXCHANGE_TRADED_RWA:,.0f} "
            f"(IRB_SIMPLE 290% * 1,000,000)."
        )

    def test_p1_153_crr_j21_approach_is_pd_lgd(
        self,
        equity_calculator: EquityCalculator,
        crr_irb_pdlgd_config: CalculationConfig,
    ) -> None:
        """
        P1.153: _determine_approach must return PD_LGD ("pd_lgd") when equity_pd_lgd=True.

        Arrange: CRR IRB config with equity_pd_lgd=True (forward-compatible guard).
        Act: equity_calculator._determine_approach(config).
        Assert: approach == "pd_lgd" (EquityApproach.PD_LGD.value once enum exists).

        Note: compares to the string "pd_lgd" to avoid AttributeError on
        EquityApproach.PD_LGD before Wave-4 adds the enum member.
        """
        # Act
        approach = equity_calculator._determine_approach(crr_irb_pdlgd_config)
        approach_str = approach.value if hasattr(approach, "value") else str(approach)

        # Assert — pre-Wave-4: approach is "irb_simple" => fails here
        assert approach_str == "pd_lgd", (
            f"{SCENARIO_ID}: _determine_approach must return 'pd_lgd' when equity_pd_lgd=True. "
            f"Got '{approach_str}'. "
            f"Pre-Wave-4 engine returns 'irb_simple' because PD_LGD enum member "
            f"and config flag do not yet exist."
        )

    def test_p1_153_crr_j21_ead_final(
        self,
        pdlgd_equity_result: dict,
    ) -> None:
        """
        P1.153: ead_final must equal the input EAD = 1,000,000.

        Arrange: fair_value / ead_final = 1,000,000.
        Act: EquityCalculator.calculate_branch.
        Assert: ead_final == 1,000,000.
        """
        actual_ead = pdlgd_equity_result["ead_final"]
        assert actual_ead == pytest.approx(EAD), (
            f"{SCENARIO_ID}: ead_final should equal input EAD {EAD:,.0f}. "
            f"Got {actual_ead:,.0f}."
        )

    def test_p1_153_crr_j21_pd_floor_parameter(self) -> None:
        """
        P1.153: Art. 165(1)(c) PD floor for exchange-traded equity must be 0.0040.

        Arrange: fixture constant from p1_153.py.
        Act: read PD_FLOOR from fixture module.
        Assert: PD_FLOOR == 0.0040.
        """
        assert PD_FLOOR == pytest.approx(0.0040, abs=1e-8), (
            f"{SCENARIO_ID}: Art. 165(1)(c) PD floor must be 0.0040 (0.40%). "
            f"Got {PD_FLOOR}."
        )

    def test_p1_153_crr_j21_lgd_parameter(self) -> None:
        """
        P1.153: Art. 165(2) supervisory LGD for non-diversified-PE must be 0.90.

        Arrange: fixture constant from p1_153.py.
        Act: read LGD_SUPERVISORY from fixture module.
        Assert: LGD_SUPERVISORY == 0.90.
        """
        assert LGD_SUPERVISORY == pytest.approx(0.90, abs=1e-8), (
            f"{SCENARIO_ID}: Art. 165(2) LGD must be 0.90 (90%). "
            f"Got {LGD_SUPERVISORY}."
        )

    def test_p1_153_crr_j21_maturity_parameter(self) -> None:
        """
        P1.153: Art. 165(3) fixed maturity must be 5.0 years.

        Arrange: fixture constant from p1_153.py.
        Act: read MATURITY_YEARS from fixture module.
        Assert: MATURITY_YEARS == 5.0.
        """
        assert MATURITY_YEARS == pytest.approx(5.0, abs=1e-8), (
            f"{SCENARIO_ID}: Art. 165(3) maturity must be 5.0 years. "
            f"Got {MATURITY_YEARS}."
        )

    def test_p1_153_crr_j21_scaling_factor_parameter(self) -> None:
        """
        P1.153: Art. 153 CRR scaling factor must be 1.06.

        Arrange: fixture constant from p1_153.py.
        Act: read SCALING_FACTOR from fixture module.
        Assert: SCALING_FACTOR == 1.06.
        """
        assert SCALING_FACTOR == pytest.approx(1.06, abs=1e-8), (
            f"{SCENARIO_ID}: Art. 153 scaling factor must be 1.06. "
            f"Got {SCALING_FACTOR}."
        )

    def test_p1_153_crr_j21_expected_correlation(self) -> None:
        """
        P1.153: expected Vasicek correlation R ≈ 0.218248.

        Cross-checks the hand-calc golden value from the fixture module.
        """
        assert EXPECTED_CORRELATION == pytest.approx(0.21824769037, rel=1e-6), (
            f"{SCENARIO_ID}: expected correlation ≈ 0.218248. "
            f"Got {EXPECTED_CORRELATION}."
        )

    def test_p1_153_crr_j21_expected_k(self) -> None:
        """
        P1.153: expected capital requirement K ≈ 0.073671.

        Cross-checks the hand-calc golden value from the fixture module.
        """
        assert EXPECTED_K == pytest.approx(0.07367139, rel=1e-5), (
            f"{SCENARIO_ID}: expected K ≈ 0.073671. Got {EXPECTED_K}."
        )

    def test_p1_153_crr_j21_expected_maturity_adjustment(self) -> None:
        """
        P1.153: expected maturity adjustment MA ≈ 1.965610.

        Cross-checks the hand-calc golden value from the fixture module.
        """
        assert EXPECTED_MATURITY_ADJUSTMENT == pytest.approx(1.96561, rel=1e-4), (
            f"{SCENARIO_ID}: expected MA ≈ 1.96561. Got {EXPECTED_MATURITY_ADJUSTMENT}."
        )

    def test_p1_153_crr_j21_expected_loss(self) -> None:
        """
        P1.153: expected EL = PD * LGD * EAD = 0.0040 * 0.90 * 1,000,000 = 3,600.

        Cross-checks the hand-calc golden value from the fixture module.
        """
        assert EXPECTED_EL == pytest.approx(3_600.0, abs=0.5), (
            f"{SCENARIO_ID}: expected EL = 3,600. Got {EXPECTED_EL}."
        )

    def test_p1_153_crr_j21_expected_rwa_golden(self) -> None:
        """
        P1.153: expected golden RWA ≈ 1,918,731.

        Cross-checks the hand-calc golden value from the fixture module.
        """
        assert EXPECTED_RWA == pytest.approx(1_918_731.0, rel=1e-4), (
            f"{SCENARIO_ID}: expected RWA ≈ 1,918,731. Got {EXPECTED_RWA}."
        )

    def test_p1_153_not_irb_simple_290_pct(
        self,
        pdlgd_equity_result: dict,
    ) -> None:
        """
        P1.153 regression: PD/LGD risk_weight must NOT be 2.90 (IRB Simple exchange-traded).

        Under Art. 155(3) with equity_pd_lgd=True, the engine must NOT fall
        through to the Art. 155(2)(a) 290% rate that apply to IRB Simple.

        Assert: risk_weight != 2.90.
        """
        actual_rw = pdlgd_equity_result["risk_weight"]
        assert actual_rw != pytest.approx(_CURRENT_IRB_SIMPLE_EXCHANGE_TRADED_RW, abs=1e-4), (
            f"{SCENARIO_ID} regression: risk_weight should not be "
            f"{_CURRENT_IRB_SIMPLE_EXCHANGE_TRADED_RW} (IRB Simple exchange-traded rate, "
            f"Art. 155(2)(a)). Got {actual_rw:.4f}. "
            f"With equity_pd_lgd=True the engine must use the PD/LGD formula (≈1.918731)."
        )
