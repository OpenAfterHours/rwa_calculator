"""
P1.249 — CRR Art. 162(1): capital effect of the fixed F-IRB supervisory maturity.

Pipeline position:
    classify_approach -> apply_firb_lgd -> prepare_columns -> apply_all_formulas

Scenario (CRR-M-FIXED):
    One F-IRB corporate term loan, EAD GBP 1,000,000, internal PD 1.00%
    (above the CRR 0.03% Art. 163 floor), F-IRB supervisory LGD 45%
    (Art. 161(1)(a), senior unsecured non-FSE), reporting date 2025-12-31,
    maturity_date 2027-12-31.

    The engine's /365 ordinal-day year fraction gives a residual of exactly
    (2027 - 2025) + 365/365 - 365/365 = 2.0y, inside the Art. 162(2) [1, 5] clip,
    so the two limbs of Art. 162(1)/(2) are cleanly separated: M = 2.0y
    (date-derived, today's default) vs M = 2.5y (fixed, under the election).

Hand calculation (CRR Art. 153(1); R and K_base are M-independent):
    R  = 0.12 x (1-e^-50x0.01)/(1-e^-50) + 0.24 x (1 - (1-e^-50x0.01)/(1-e^-50))
       = 0.12 x 0.393469340 + 0.24 x 0.606530660
       = 0.192783679
    b  = (0.11852 - 0.05478 x ln(0.01))^2 = (0.11852 + 0.252271223)^2
       = 0.137486131
    K_base = LGD x [N( (1-R)^-0.5 x G(0.01) + (R/(1-R))^0.5 x G(0.999) ) - PD]
           = 0.45 x [N(-1.079093...) - 0.01] = 0.058622705

    Election OFF (M = 2.0y, Art. 162(2) — today's behaviour):
        MA  = (1 + (2.0 - 2.5) x b) / (1 - 1.5 x b) = 0.931256934 / 0.793770804
            = 1.173206334
        K   = 0.058622705 x 1.173206334 = 0.068776529
        RW  = K x 12.5 x 1.06 (Art. 153(1) CRR scaling factor) = 0.911289012
        RWA = 0.911289012 x 1,000,000 = 911,289.01

    Election ON (M = 2.5y, Art. 162(1) "all other exposures"):
        MA  = (1 + (2.5 - 2.5) x b) / (1 - 1.5 x b) = 1 / 0.793770804
            = 1.259809501
        K   = 0.058622705 x 1.259809501 = 0.073853441
        RW  = K x 12.5 x 1.06 = 0.978558095
        RWA = 978,558.09

    Capital direction: MA(2.5)/MA(2.0) = 1.073817507, i.e. +7.38% RWA
    (+GBP 67,269.08) for this exposure. The fixed 2.5y raises RWA for any F-IRB
    row whose date-derived M is below 2.5y and lowers it above 2.5y (up to the
    5-year cap, where MA(5)/MA(2.5) = 1.273...); EL is unchanged either way
    (PD x LGD x EAD = 4,500) because EL carries no maturity adjustment.

References:
    - CRR Art. 162(1): fixed F-IRB supervisory M — 0.5y repo-style / 2.5y other,
      with the Art. 143 permission able to substitute the Art. 162(2) derivation
    - CRR Art. 162(2): per-exposure date-derived M, capped at 5 years
    - CRR Art. 153(1): correlation, maturity adjustment, K and the 1.06 scaling factor
    - CRR Art. 161(1)(a): F-IRB supervisory LGD 45% (senior unsecured)
    - PS1/26 Art. 162(1): "[Note: Provision left blank]" — election inert under B31
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest
from tests.fixtures.contract_columns import pad_crm_exit_defaults as _pad

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import ApproachType, PermissionMode
from rwa_calc.engine.irb.transforms import (
    apply_all_formulas,
    apply_firb_lgd,
    classify_approach,
    prepare_columns,
)

# ---------------------------------------------------------------------------
# Scenario inputs
# ---------------------------------------------------------------------------

_REPORTING_DATE = date(2025, 12, 31)
_MATURITY_DATE = date(2027, 12, 31)  # residual exactly 2.0y on the /365 basis
_EAD = 1_000_000.0
_PD = 0.01
_LGD = 0.45

# ---------------------------------------------------------------------------
# Hand-calc expectations (module docstring)
# ---------------------------------------------------------------------------

_M_DEFAULT = 2.0
_M_ELECTED = 2.5

_MA_DEFAULT = 1.173206334
_MA_ELECTED = 1.259809501

_RW_DEFAULT = 0.911289012
_RW_ELECTED = 0.978558095

_RWA_DEFAULT = 911_289.01
_RWA_ELECTED = 978_558.09

_EL_EXPECTED = 4_500.0  # PD x LGD x EAD — no maturity adjustment on EL

# GBP 0.50 on a 6-figure RWA (~5e-7 relative) — three orders of magnitude tighter
# than the GBP 67,269 gap between the two limbs.
_ABS_TOL = 0.50


def _config(*, firb_fixed_maturity: bool) -> CalculationConfig:
    return CalculationConfig.crr(
        reporting_date=_REPORTING_DATE,
        permission_mode=PermissionMode.IRB,
        firb_fixed_maturity=firb_fixed_maturity,
    )


def _run(config: CalculationConfig, *, is_sft: bool = False) -> dict:
    """Run the CRR F-IRB transform chain over the single scenario exposure."""
    exposures = pl.LazyFrame(
        {
            "exposure_reference": ["LN_P1249"],
            "counterparty_reference": ["CP_P1249"],
            "exposure_class": ["corporate"],
            "approach": [ApproachType.FIRB.value],
            "pd": [_PD],
            "lgd": [_LGD],
            "seniority": ["senior"],
            "ead_final": [_EAD],
            "maturity_date": [_MATURITY_DATE],
            "is_sft": [is_sft],
        }
    )

    return (
        _pad(exposures)
        .pipe(classify_approach, config)
        .pipe(apply_firb_lgd, config)
        .pipe(prepare_columns, config)
        .pipe(apply_all_formulas, config)
        .collect()
        .to_dicts()[0]
    )


@pytest.fixture(scope="module")
def row_default() -> dict:
    """Election OFF — the historic Art. 162(2) date-derived M."""
    return _run(_config(firb_fixed_maturity=False))


@pytest.fixture(scope="module")
def row_elected() -> dict:
    """Election ON — Art. 162(1) fixed 2.5y for this non-repo-style exposure."""
    return _run(_config(firb_fixed_maturity=True))


class TestP1249Art1621FixedFIRBMaturityCapital:
    """CRR Art. 162(1): the fixed 2.5y M is an Art. 143 election, default off."""

    # -- Election OFF: today's numbers must be untouched --------------------

    def test_default_maturity_is_date_derived(self, row_default: dict) -> None:
        # Assert — residual 2.0y inside the Art. 162(2) [1, 5] clip
        assert row_default["maturity"] == pytest.approx(_M_DEFAULT)

    def test_default_rwa_matches_hand_calc(self, row_default: dict) -> None:
        # Assert — RW 0.911289012 x EAD 1,000,000 (NOT the 978,558.09 elected value)
        assert row_default["rwa"] == pytest.approx(_RWA_DEFAULT, abs=_ABS_TOL)
        assert row_default["risk_weight"] == pytest.approx(_RW_DEFAULT, abs=1e-8)
        assert row_default["maturity_adjustment"] == pytest.approx(_MA_DEFAULT, abs=1e-8)

    # -- Election ON: the Art. 162(1) capital number ------------------------

    def test_elected_maturity_is_the_fixed_two_and_a_half_years(self, row_elected: dict) -> None:
        # Assert
        assert row_elected["maturity"] == pytest.approx(_M_ELECTED)

    def test_elected_rwa_matches_hand_calc(self, row_elected: dict) -> None:
        # Assert — MA = 1/(1 - 1.5b), the M = 2.5y case
        assert row_elected["rwa"] == pytest.approx(_RWA_ELECTED, abs=_ABS_TOL)
        assert row_elected["risk_weight"] == pytest.approx(_RW_ELECTED, abs=1e-8)
        assert row_elected["maturity_adjustment"] == pytest.approx(_MA_ELECTED, abs=1e-8)

    def test_election_raises_rwa_by_the_maturity_adjustment_ratio(
        self, row_default: dict, row_elected: dict
    ) -> None:
        # Assert — the only moving part is MA; the ratio is 1/(1 - 1.5b) / MA(2.0)
        assert row_elected["rwa"] / row_default["rwa"] == pytest.approx(
            _MA_ELECTED / _MA_DEFAULT, abs=1e-9
        )
        assert row_elected["rwa"] - row_default["rwa"] == pytest.approx(67_269.08, abs=_ABS_TOL)

    def test_expected_loss_is_unchanged_by_the_election(
        self, row_default: dict, row_elected: dict
    ) -> None:
        # Assert — EL = PD x LGD x EAD carries no maturity adjustment
        assert row_default["expected_loss"] == pytest.approx(_EL_EXPECTED, abs=_ABS_TOL)
        assert row_elected["expected_loss"] == pytest.approx(_EL_EXPECTED, abs=_ABS_TOL)

    # -- Repo-style limb of the same sentence stays at 0.5y ------------------

    def test_repo_style_exposure_keeps_the_half_year_limb_under_the_election(self) -> None:
        # Arrange / Act — same exposure flagged is_sft
        row = _run(_config(firb_fixed_maturity=True), is_sft=True)

        # Assert — Art. 162(1) repo-style M = 0.5y, not the 2.5y "other" value
        assert row["maturity"] == pytest.approx(0.5)
        assert row["rwa"] < _RWA_DEFAULT
