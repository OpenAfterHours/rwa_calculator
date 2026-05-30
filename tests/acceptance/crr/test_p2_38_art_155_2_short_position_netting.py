"""
P2.38 — CRR Art. 155(2) non-trading-book short-position netting (scenario CRR-J21).

Under CRR Art. 155(2), short positions held in the non-trading book may offset
long positions in the *same individual stock* provided:
  (a) the hedge is explicit, AND
  (b) the hedge covers at least one year.

Hand calculation:
    IRB Simple RW (exchange_traded) = 2.90  [Art. 155(2)(a)]
    Long  (EQ-NET-LONG):  position_value = +1,000,000
    Short (EQ-NET-SHORT): position_value =   -400,000
    Net long = max(0, L + S) = max(0, 1_000_000 + (-400_000)) = 600_000
    EAD_final (long, netted) = 600_000
    RWA (long) = 600_000 × 2.90 = 1_740_000
    RWA (short, absorbed) = 0

Anti-confound: netted 1_740_000 < no-netting long-only 2_900_000 (netting fired).

References:
    CRR Art. 155(1)-(2): IRB Simple Risk Weight Method + netting rule
    docs/specifications/crr/equity-approach.md L140-143
"""

from __future__ import annotations

import dataclasses
from typing import cast

import polars as pl
import pytest
from tests.fixtures.p2_38.p2_38 import (
    COUNTERPARTY_REF,
    EXPECTED_EAD_FINAL_LONG,
    EXPECTED_EAD_FINAL_SHORT,
    EXPECTED_RWA_LONG,
    EXPECTED_RWA_SHORT,
    EXPECTED_RWA_TOTAL,
    IRB_SIMPLE_RW_EXCHANGE_TRADED,
    LONG_EXPOSURE_REF,
    NO_NETTING_BASELINE_RWA,
    REPORTING_DATE,
    SHORT_EXPOSURE_REF,
    create_p238_equity_exposures,
)

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.equity.calculator import EquityCalculator

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCENARIO_ID = "CRR-J21 / P2.38"

# ---------------------------------------------------------------------------
# Config builder
# ---------------------------------------------------------------------------


def _build_config() -> CalculationConfig:
    """
    Build a CRR IRB config with equity_pd_lgd=False so the equity calculator
    routes to EquityApproach.IRB_SIMPLE (Art. 155(2)).

    equity_pd_lgd defaults to False on CalculationConfig, so we use replace
    only when the attribute exists (forward-compatible guard) — same pattern
    as test_p1_153.
    """
    base = CalculationConfig.crr(
        reporting_date=REPORTING_DATE,
        permission_mode=PermissionMode.IRB,
    )
    if hasattr(base, "equity_pd_lgd"):
        return dataclasses.replace(base, equity_pd_lgd=False)
    return base


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def crr_irb_config() -> CalculationConfig:
    """CRR IRB config with equity_pd_lgd=False — routes to IRB_SIMPLE."""
    return _build_config()


@pytest.fixture(scope="module")
def equity_calculator() -> EquityCalculator:
    """EquityCalculator instance."""
    return EquityCalculator()


@pytest.fixture(scope="module")
def netting_result(
    equity_calculator: EquityCalculator,
    crr_irb_config: CalculationConfig,
) -> pl.DataFrame:
    """
    Run calculate_branch on the P2.38 two-row fixture and return the collected
    DataFrame (both long and short rows).

    The fixture carries the three new netting columns (position_value,
    issuer_reference, is_explicitly_hedged) forward-compatibly.  Before
    engine Wave 4 the equity calculator ignores them; after Wave 4 it nets.
    """
    exposures_lf = create_p238_equity_exposures().lazy()
    result = equity_calculator.calculate_branch(exposures_lf, crr_irb_config).collect()
    return cast(pl.DataFrame, result)


@pytest.fixture(scope="module")
def long_row(netting_result: pl.DataFrame) -> dict:
    """The long (EQ-NET-LONG) result row as a dict."""
    rows = netting_result.filter(pl.col("exposure_reference") == LONG_EXPOSURE_REF).to_dicts()
    assert len(rows) == 1, f"{SCENARIO_ID}: expected exactly one long row, got {len(rows)}"
    return rows[0]


@pytest.fixture(scope="module")
def short_row(netting_result: pl.DataFrame) -> dict:
    """The short (EQ-NET-SHORT) result row as a dict."""
    rows = netting_result.filter(pl.col("exposure_reference") == SHORT_EXPOSURE_REF).to_dicts()
    assert len(rows) == 1, f"{SCENARIO_ID}: expected exactly one short row, got {len(rows)}"
    return rows[0]


# ---------------------------------------------------------------------------
# P2.38 — CRR Art. 155(2) Short-Position Netting Tests
# ---------------------------------------------------------------------------


class TestP238CRRart1552ShortPositionNetting:
    """
    P2.38 (CRR-J21): CRR Art. 155(2) non-trading-book short-position netting.

    Long EQ-NET-LONG +1,000,000 and Short EQ-NET-SHORT -400,000 on the same
    issuer (ISSUER-A), both exchange_traded, both explicitly hedged.

    Expected post-netting:
        long ead_final  = 600,000  (L + S = 1,000,000 - 400,000)
        long risk_weight = 2.90    (Art. 155(2) exchange-traded)
        long rwa        = 1,740,000
        short rwa       = 0        (absorbed into the long)
        total RWA       = 1,740,000 (< 2,900,000 un-netted baseline)

    Pre-Wave-4 failure: engine has no netting logic → long row carries
        ead_final=1,000,000, rwa=2,900,000.
    Post-Wave-4 pass: netting fires → ead_final=600,000, rwa=1,740,000.
    """

    def test_p2_38_crr_j21_long_ead_final_is_netted(
        self,
        long_row: dict,
    ) -> None:
        """
        P2.38: long row ead_final must equal 600,000 (post-netting net long).

        Arrange: position_value=+1,000,000 (long), -400,000 (short),
                 same issuer_reference, is_explicitly_hedged=True, CRR IRB.
        Act: EquityCalculator.calculate_branch — netting branch (Art. 155(2)).
        Assert: ead_final == 600,000.

        Pre-Wave-4: ead_final == 1,000,000 (no netting) — AssertionError here.
        """
        # Act — result from fixture
        actual_ead = long_row["ead_final"]

        # Assert
        assert actual_ead == pytest.approx(EXPECTED_EAD_FINAL_LONG, rel=1e-6), (
            f"{SCENARIO_ID}: long row ead_final must be {EXPECTED_EAD_FINAL_LONG:,.0f} "
            f"(net long after Art. 155(2) netting: 1,000,000 - 400,000). "
            f"Got {actual_ead:,.0f}. "
            f"Pre-Wave-4 engine has no netting — returns 1,000,000 (un-netted long)."
        )

    def test_p2_38_crr_j21_long_risk_weight_is_exchange_traded(
        self,
        long_row: dict,
    ) -> None:
        """
        P2.38: long row risk_weight must be 2.90 (Art. 155(2) exchange-traded).

        Arrange: equity_type=exchange_traded, is_exchange_traded=True, CRR IRB.
        Act: EquityCalculator.calculate_branch.
        Assert: risk_weight == 2.90.
        """
        # Act — result from fixture
        actual_rw = long_row["risk_weight"]

        # Assert
        assert actual_rw == pytest.approx(IRB_SIMPLE_RW_EXCHANGE_TRADED, abs=1e-4), (
            f"{SCENARIO_ID}: long row risk_weight must be {IRB_SIMPLE_RW_EXCHANGE_TRADED} "
            f"(Art. 155(2)(a) exchange-traded 290%). Got {actual_rw}."
        )

    def test_p2_38_crr_j21_long_rwa_is_netted(
        self,
        long_row: dict,
    ) -> None:
        """
        P2.38: long row rwa must equal 1,740,000 (600,000 × 2.90).

        Arrange: netted EAD=600,000, RW=2.90.
        Act: EquityCalculator.calculate_branch.
        Assert: rwa == 1,740,000.

        Pre-Wave-4: rwa == 2,900,000 (1,000,000 × 2.90, no netting) — AssertionError.
        """
        # Act — result from fixture
        actual_rwa = long_row.get("rwa") or long_row.get("rwa_final")

        # Assert
        assert actual_rwa == pytest.approx(EXPECTED_RWA_LONG, rel=1e-6), (
            f"{SCENARIO_ID}: long row rwa must be {EXPECTED_RWA_LONG:,.0f} "
            f"(600,000 × 2.90 = 1,740,000 after Art. 155(2) netting). "
            f"Got {actual_rwa:,.0f}. "
            f"Pre-Wave-4 engine returns {NO_NETTING_BASELINE_RWA:,.0f} "
            f"(1,000,000 × 2.90, netting absent)."
        )

    def test_p2_38_crr_j21_short_rwa_is_zero_absorbed(
        self,
        short_row: dict,
    ) -> None:
        """
        P2.38: short row rwa must be 0 (position absorbed by the long).

        Arrange: short EQ-NET-SHORT absorbed into the netted long.
        Act: EquityCalculator.calculate_branch.
        Assert: rwa == 0.

        Pre-Wave-4: short treated as standalone long at abs(fair_value)=400,000
            → rwa = 400,000 × 2.90 = 1,160,000 — AssertionError here.
        """
        # Act — result from fixture
        actual_rwa = short_row.get("rwa") or short_row.get("rwa_final") or 0.0

        # Assert
        assert actual_rwa == pytest.approx(EXPECTED_RWA_SHORT, abs=1.0), (
            f"{SCENARIO_ID}: short row rwa must be {EXPECTED_RWA_SHORT:,.0f} (absorbed). "
            f"Got {actual_rwa:,.0f}. "
            f"Pre-Wave-4 engine treats short as standalone long: "
            f"400,000 × 2.90 = 1,160,000."
        )

    def test_p2_38_crr_j21_issuer_a_total_rwa(
        self,
        netting_result: pl.DataFrame,
    ) -> None:
        """
        P2.38: Issuer-A total RWA across both rows must equal 1,740,000.

        Arrange: both rows share counterparty_reference == CP-ISSUER-A.
        Act: sum rwa column over both rows.
        Assert: total == 1,740,000.

        Pre-Wave-4: total = 2,900,000 + 1,160,000 = 4,060,000 (both rows treated
        as standalone longs).
        """
        # Arrange — filter by counterparty
        counterparty_col = (
            "counterparty_reference" if "counterparty_reference" in netting_result.columns else None
        )

        if counterparty_col is not None:
            issuer_rows = netting_result.filter(pl.col(counterparty_col) == COUNTERPARTY_REF)
        else:
            issuer_rows = netting_result

        # Act — sum rwa over all issuer rows
        rwa_col = "rwa" if "rwa" in issuer_rows.columns else "rwa_final"
        total_rwa = issuer_rows[rwa_col].sum()

        # Assert
        assert total_rwa == pytest.approx(EXPECTED_RWA_TOTAL, rel=1e-6), (
            f"{SCENARIO_ID}: Issuer-A total RWA must be {EXPECTED_RWA_TOTAL:,.0f}. "
            f"Got {total_rwa:,.0f}. "
            f"Expected 1,740,000 (netted long only). "
            f"Pre-Wave-4: both rows standalone → total much larger."
        )

    def test_p2_38_crr_j21_anti_confound_netted_lt_unnested(
        self,
        netting_result: pl.DataFrame,
    ) -> None:
        """
        P2.38 anti-confound: total Issuer-A RWA must be strictly < 2,900,000
        (the un-netted long-only figure, confirming netting fired).

        Arrange: total from both rows.
        Act: sum rwa.
        Assert: total < 2,900,000.

        This assertion also fails pre-Wave-4 because total > 2,900,000 when
        the short is treated as a standalone long.
        """
        rwa_col = "rwa" if "rwa" in netting_result.columns else "rwa_final"
        total_rwa = netting_result[rwa_col].sum()

        assert total_rwa < NO_NETTING_BASELINE_RWA, (
            f"{SCENARIO_ID}: total RWA {total_rwa:,.0f} must be strictly < "
            f"{NO_NETTING_BASELINE_RWA:,.0f} (un-netted long-only baseline). "
            f"Pre-Wave-4 total exceeds the un-netted long-only figure."
        )

    def test_p2_38_crr_j21_net_ead_lt_gross_long(
        self,
        long_row: dict,
    ) -> None:
        """
        P2.38 anti-confound: netted long ead_final must be < 1,000,000 (gross long).

        Assert: ead_final < 1,000,000.

        Pre-Wave-4: ead_final == 1,000,000 → assertion fails.
        """
        actual_ead = long_row["ead_final"]
        assert actual_ead < 1_000_000.0, (
            f"{SCENARIO_ID}: netted long ead_final {actual_ead:,.0f} must be < 1,000,000 "
            f"(gross long before netting). "
            f"Pre-Wave-4 engine returns ead_final=1,000,000 (no netting applied)."
        )

    def test_p2_38_crr_j21_short_ead_final_is_zero(
        self,
        short_row: dict,
    ) -> None:
        """
        P2.38: short row ead_final must be 0 after netting (position absorbed).

        Assert: ead_final == 0.

        Pre-Wave-4: ead_final == 400,000 (fair_value basis, no netting).
        """
        actual_ead = short_row["ead_final"]
        assert actual_ead == pytest.approx(EXPECTED_EAD_FINAL_SHORT, abs=1.0), (
            f"{SCENARIO_ID}: short row ead_final must be {EXPECTED_EAD_FINAL_SHORT:,.0f} "
            f"(absorbed by the long). Got {actual_ead:,.0f}. "
            f"Pre-Wave-4 engine returns 400,000 (abs(fair_value), netting absent)."
        )
