"""
P1.251 — B31 F-IRB UK residential-mortgage commitment CCF (Art. 166C(1)).

Pipeline position:
    HierarchyResolver -> CCFCalculator -> (CRM) -> IRBCalculator -> Aggregator

Scenario:
    PS1/26 Art. 166C(1) sets the F-IRB / Slotting off-balance-sheet exposure
    value as the item's nominal value times "the conversion factor that would be
    applicable to the off-balance sheet item under the Standardised Approach, as
    set out in Credit Risk: Standardised Approach (CRR) Part Article 111".
    Article 111(1) Table A1 Row 4(b) assigns a 50% conversion factor to "UK
    residential mortgage commitments that are not subject to a conversion factor
    of 10% or 100%".

    A UK residential-mortgage commitment tagged ``risk_type="OC"`` therefore
    takes 50%, not the generic Row 5 "other commitments" 40% — under the F-IRB
    approach exactly as under the SA.

Defect under test (pre-fix):
    The engine applied the Row 4(b) override to the SA CCF carrier only, so a
    B31 F-IRB commitment kept the Row 5 40% CCF: EAD 400,000 instead of 500,000,
    understating RWA by 92,316.80 on the exposure below.

Exposures under test (both fully undrawn, nominal GBP 1,000,000, corporate
F-IRB, PD 1%, LGD 45%, M 2.5y):

    FLAGGED  (P1251-RESI):    is_uk_residential_mortgage_commitment=True
        ccf 0.50 -> EAD 500,000 -> RWA 461,584.006960
    CONTROL  (P1251-CONTROL): is_uk_residential_mortgage_commitment=False
        ccf 0.40 -> EAD 400,000 -> RWA 369,267.205568

Hand-calc (PS1/26 Art. 153(1), corporate IRB RW function, no SME/infra factor
and no 1.06 scaling under Basel 3.1):
    w    = (1 - e^(-50 x 0.01)) / (1 - e^-50)     = 0.3934693403
    R    = 0.12w + 0.24(1 - w)                    = 0.1927836792
    b    = (0.11852 - 0.05478 ln 0.01)^2          = 0.1374861309
    cond = N[(N^-1(0.01) + sqrt(R) N^-1(0.999)) / sqrt(1 - R)]
                                                  = 0.1402726785
    MA   = (1 + (2.5 - 2.5)b) / (1 - 1.5b)        = 1.2598095009
    K    = 0.45 x (cond - 0.01) x MA              = 0.0738534411
    RW   = K x 12.5                               = 0.9231680139
    RWA(FLAGGED) = 0.9231680139 x 500,000         = 461,584.006960
    RWA(CONTROL) = 0.9231680139 x 400,000         = 369,267.205568
    Delta = 92,316.801392 (exactly 25% more RWA on the flagged commitment)

References:
    - PS1/26 Art. 166C(1): F-IRB / Slotting OBS exposure value = SA CCF x nominal
    - PS1/26 Art. 111(1) Table A1 Row 4(b): UK residential mortgage commitments
      not subject to a 10% or 100% conversion factor -> 50%
    - PS1/26 Art. 111(1) Table A1 Row 5: any other commitment -> 40%
    - PS1/26 Art. 153(1): corporate IRB risk-weight function
    - src/rwa_calc/engine/ccf.py: CCFCalculator._compute_ccf
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.engine.ccf import CCFCalculator
from rwa_calc.engine.irb import IRBCalculator
from tests.fixtures.contract_columns import pad_crm_exit_defaults

# ---------------------------------------------------------------------------
# Scenario constants
# ---------------------------------------------------------------------------

FLAGGED_REF = "P1251-RESI"
CONTROL_REF = "P1251-CONTROL"

NOMINAL = 1_000_000.0

EXPECTED_CCF_FLAGGED = 0.50  # Table A1 Row 4(b)
EXPECTED_CCF_CONTROL = 0.40  # Table A1 Row 5
EXPECTED_EAD_FLAGGED = 500_000.0
EXPECTED_EAD_CONTROL = 400_000.0

# Art. 153(1) corporate RW at PD=1%, LGD=45%, M=2.5y (see module docstring)
EXPECTED_RW = 0.9231680139
EXPECTED_RWA_FLAGGED = 461_584.006960
EXPECTED_RWA_CONTROL = 369_267.205568


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def b31_config() -> CalculationConfig:
    """Basel 3.1 steady-state configuration."""
    return CalculationConfig.basel_3_1(reporting_date=date(2027, 6, 30))


@pytest.fixture(scope="module")
def p1_251_results(b31_config: CalculationConfig) -> pl.DataFrame:
    """
    Run the flagged / control commitment pair through CCF then IRB.

    Both rows are identical apart from the Row 4(b) flag, so every difference in
    the output is attributable to the conversion factor.
    """
    # Arrange — two fully-undrawn corporate F-IRB commitments
    exposures = pl.DataFrame(
        {
            "exposure_reference": [FLAGGED_REF, CONTROL_REF],
            "drawn_amount": [0.0, 0.0],
            "nominal_amount": [NOMINAL, NOMINAL],
            "risk_type": ["OC", "OC"],
            "approach": ["foundation_irb", "foundation_irb"],
            "is_uk_residential_mortgage_commitment": [True, False],
            "exposure_class": ["CORPORATE", "CORPORATE"],
            "pd": [0.01, 0.01],
            "lgd": [0.45, 0.45],
            "maturity": [2.5, 2.5],
        }
    ).lazy()

    # Act — CCF stage, then the IRB branch on the resulting exposure value
    with_ccf = CCFCalculator().apply_ccf(exposures, b31_config)
    irb_input = with_ccf.with_columns(pl.col("ead_pre_crm").alias("ead_final"))
    return IRBCalculator().calculate_branch(pad_crm_exit_defaults(irb_input), b31_config).collect()


def _row(df: pl.DataFrame, reference: str) -> dict:
    """Return the single result row for ``reference``."""
    rows = df.filter(pl.col("exposure_reference") == reference).to_dicts()
    assert len(rows) == 1, f"expected 1 row for {reference!r}, got {len(rows)}"
    return rows[0]


# ---------------------------------------------------------------------------
# FLAGGED — the Row 4(b) commitment
# ---------------------------------------------------------------------------


class TestP1251FlaggedResiCommitment:
    """B31 F-IRB UK residential-mortgage commitment: 50% CCF and its capital."""

    def test_flagged_ccf_is_50_pct(self, p1_251_results: pl.DataFrame) -> None:
        """FLAGGED: ccf == 0.50 (Table A1 Row 4(b) via Art. 166C(1)).

        Arrange: OC commitment, flag True, F-IRB, Basel 3.1.
        Act:     CCFCalculator.apply_ccf.
        Assert:  ccf == 0.50.

        Pre-fix failure: ccf == 0.40 — the override never reached the F-IRB CCF.
        """
        # Arrange
        row = _row(p1_251_results, FLAGGED_REF)

        # Assert
        assert row["ccf"] == pytest.approx(EXPECTED_CCF_FLAGGED, abs=1e-9), (
            "Art. 166C(1) makes the F-IRB conversion factor the Art. 111 SA one, "
            f"so Row 4(b) applies: expected 0.50, got {row['ccf']:.4f}."
        )

    def test_flagged_ead_is_500k(self, p1_251_results: pl.DataFrame) -> None:
        """FLAGGED: ead_final == 500,000 (1,000,000 x 0.50).

        Arrange: nominal 1,000,000 fully undrawn.
        Act:     CCFCalculator.apply_ccf -> ead_pre_crm.
        Assert:  ead_final == 500,000.

        Pre-fix failure: 400,000 (1,000,000 x 0.40).
        """
        # Arrange
        row = _row(p1_251_results, FLAGGED_REF)

        # Assert
        assert row["ead_final"] == pytest.approx(EXPECTED_EAD_FLAGGED, rel=1e-9)

    def test_flagged_rwa_is_461584(self, p1_251_results: pl.DataFrame) -> None:
        """FLAGGED: rwa_final == 461,584.006960 (RW 0.9231680139 x EAD 500,000).

        Arrange: PD 1%, LGD 45%, M 2.5y corporate F-IRB (Art. 153(1)).
        Act:     CCFCalculator.apply_ccf -> IRBCalculator.calculate_branch.
        Assert:  rwa_final == 461,584.006960.

        Pre-fix failure: 369,267.205568 — the 40% CCF understates RWA by
        92,316.801392.
        """
        # Arrange
        row = _row(p1_251_results, FLAGGED_REF)

        # Assert
        assert row["risk_weight"] == pytest.approx(EXPECTED_RW, rel=1e-9)
        assert row["rwa_final"] == pytest.approx(EXPECTED_RWA_FLAGGED, rel=1e-9), (
            f"expected RWA {EXPECTED_RWA_FLAGGED:,.6f} (RW {EXPECTED_RW} x 500,000), "
            f"got {row['rwa_final']:,.6f}."
        )


# ---------------------------------------------------------------------------
# CONTROL — the unflagged Row 5 commitment
# ---------------------------------------------------------------------------


class TestP1251ControlOtherCommitment:
    """Regression guard: an unflagged commitment keeps the Row 5 40% CCF."""

    def test_control_ccf_is_40_pct(self, p1_251_results: pl.DataFrame) -> None:
        """CONTROL: ccf == 0.40 (Table A1 Row 5 — flag False, no override).

        Arrange: identical OC commitment with flag False.
        Act:     CCFCalculator.apply_ccf.
        Assert:  ccf == 0.40.
        """
        # Arrange
        row = _row(p1_251_results, CONTROL_REF)

        # Assert
        assert row["ccf"] == pytest.approx(EXPECTED_CCF_CONTROL, abs=1e-9)

    def test_control_ead_and_rwa_unchanged(self, p1_251_results: pl.DataFrame) -> None:
        """CONTROL: EAD 400,000 and RWA 369,267.205568 are untouched by the fix.

        Arrange: identical OC commitment with flag False.
        Act:     CCFCalculator.apply_ccf -> IRBCalculator.calculate_branch.
        Assert:  ead_final == 400,000 and rwa_final == 369,267.205568.
        """
        # Arrange
        row = _row(p1_251_results, CONTROL_REF)

        # Assert
        assert row["ead_final"] == pytest.approx(EXPECTED_EAD_CONTROL, rel=1e-9)
        assert row["rwa_final"] == pytest.approx(EXPECTED_RWA_CONTROL, rel=1e-9)

    def test_flagged_rwa_is_exactly_125_pct_of_control(self, p1_251_results: pl.DataFrame) -> None:
        """The 40% -> 50% CCF step is the ONLY difference: RWA ratio == 1.25.

        Arrange: the flagged / control pair differ only in the Row 4(b) flag.
        Act:     CCFCalculator.apply_ccf -> IRBCalculator.calculate_branch.
        Assert:  rwa_final(FLAGGED) / rwa_final(CONTROL) == 0.50 / 0.40 = 1.25.
        """
        # Arrange
        flagged = _row(p1_251_results, FLAGGED_REF)
        control = _row(p1_251_results, CONTROL_REF)

        # Assert
        assert flagged["rwa_final"] / control["rwa_final"] == pytest.approx(1.25, rel=1e-9)
