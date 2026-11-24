"""Unit tests for the volatility adjustment (HC) on non-financial F-IRB collateral.

CRR and PS1/26 value non-financial collateral differently, and the difference is
the whole of the Art. 230 mechanism:

- CRR Art. 229 values the collateral C itself: "the market value or mortgage
  lending value" of property net of prior claims (229(1)), "the amount
  receivable" (229(2)), and "Institutions shall value physical collateral other
  than immovable property at its market value" (229(3)). Art. 230(2) Table 5 has
  only LGD*, C* and C** columns, with no haircut column. The only reductions are
  the C* gate and the C** divisor (1.25 / 1.40).
- PS1/26 Art. 230(1) builds ES "after the application of: (a) the volatility
  adjustment applicable for the type of collateral (HC), as specified in
  paragraph 2". The paragraph 2 table sets HC at 40% for receivables, immovable
  property and other physical collateral, and C*/C** are deleted.

The defect pinned here (plan item D4.75): CRR applied the 40% PS1/26 HC to
genuine other-physical collateral and then also divided by the 1.40 C** divisor,
counting the haircut twice. A 40%-covered pledge, inside C*, was valued at 24%,
fell below C* and reverted to LGDU with a spurious CRM022.

The 40% row is also the conservative fall-through for collateral the Art. 224
lookup cannot place (``financial_collateral``, ``covered_bonds``, an issuer-less
``bond``, ``ciu``, an unrecognised string). Those rows keep it in both regimes;
the guards below pin that.

References:
- CRR Art. 229(1)-(3): value of non-financial collateral
- CRR Art. 230(1)-(2) Table 5: C* / C** and LGD*, no HC
- PS1/26 Art. 230(1)-(2): ES after HC; HC 40% for each non-financial type
- CRR Art. 161(1)(a) / PS1/26 Art. 161(1)(aa): senior unsecured LGDU 45% / 40%
- CRR Annex II C 08.01 col 0200: other physical collateral at the Art. 229(3)
  value (CRR) / PS1/26 Annex II OF 08.01 cols 0190-0210: the adjusted Ci
"""

from __future__ import annotations

import math
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
from rwa_calc.contracts.errors import ERROR_BELOW_MIN_COLLATERALISATION
from rwa_calc.domain.enums import ApproachType, ExposureClass, PermissionMode
from rwa_calc.engine.crm.haircuts import HaircutCalculator
from rwa_calc.engine.crm.processor import CRMProcessor

# =============================================================================
# Constants
# =============================================================================

EAD: float = 1_000_000.0
MV: float = 1_000_000.0

# HC by regime for genuine non-financial collateral: CRR Art. 229 has none,
# PS1/26 Art. 230(2) sets 40% for every type.
FCM_HC: dict[str, float] = {"crr": 0.0, "b31": 0.40}

# The conservative fall-through for collateral the Art. 224 lookup cannot place,
# scaled to the 20-day secured-lending period (Art. 224(2)(a), Art. 226(2)):
# 0.40 x sqrt(20/10).
FALL_THROUGH_HC: float = 0.40 * math.sqrt(2.0)

# Hand-calculated F-IRB LGD*, senior corporate, E = 1m.
# CRR: C = MV (no HC). C/E >= C* (30%) -> secured = min(C / C**, E) at LGDS,
#      remainder at LGDU 45%. LGDS: other physical 40%, real estate 35%.
# B31: ES = MV x (1 - 0.40). LGD* = LGDU x (E - ES)/E + LGDS x ES/E with LGDU 40%;
#      LGDS: other physical 25%, immovable property 20%.
#
# other_physical 400k (C/E = 40%, inside [C*, C* / (1 - 0.40)) = [30%, 50%)):
#   CRR: secured 285,714.29 -> 0.40 x 0.285714 + 0.45 x 0.714286 = 0.435714
#   B31: ES 240,000 -> 0.40 x 0.76 + 0.25 x 0.24 = 0.364
# other_physical 1.4m (C = C** x E exactly):
#   CRR: secured = E -> 0.40
#   B31: ES = min(840,000, E) -> 0.40 x 0.16 + 0.25 x 0.84 = 0.274
# real_estate 400k (control: property never carried an HC under CRR):
#   CRR: 0.35 x 0.285714 + 0.45 x 0.714286 = 0.421429
#   B31: ES 240,000 -> 0.40 x 0.76 + 0.20 x 0.24 = 0.352
FIRB_LGD: dict[tuple[str, str, float], float] = {
    ("crr", "other_physical", 400_000.0): 0.435714,
    ("b31", "other_physical", 400_000.0): 0.364,
    ("crr", "other_physical", 1_400_000.0): 0.40,
    ("b31", "other_physical", 1_400_000.0): 0.274,
    ("crr", "real_estate", 400_000.0): 0.421429,
    ("b31", "real_estate", 400_000.0): 0.352,
}

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def processor() -> CRMProcessor:
    return CRMProcessor()


def _config(regime: str) -> CalculationConfig:
    if regime == "crr":
        return CalculationConfig.crr(
            reporting_date=date(2024, 12, 31), permission_mode=PermissionMode.IRB
        )
    return CalculationConfig.basel_3_1(
        reporting_date=date(2030, 6, 30), permission_mode=PermissionMode.IRB
    )


# =============================================================================
# Helpers
# =============================================================================


def _collateral_lf(collateral_type: str) -> pl.LazyFrame:
    """One same-currency, non-SFT pledge shaped for ``HaircutCalculator.apply_haircuts``.

    ``issuer_type`` is null, so a ``bond`` row has no issuer to place it by.
    """
    return pl.LazyFrame(
        {
            "collateral_reference": ["COLL1"],
            "collateral_type": [collateral_type],
            "currency": ["GBP"],
            "market_value": [MV],
            "nominal_value": [MV],
            "issuer_type": pl.Series([None], dtype=pl.String),
            "issuer_cqs": pl.Series([None], dtype=pl.Int8),
            "residual_maturity_years": pl.Series([None], dtype=pl.Float64),
            "exposure_currency": ["GBP"],
            "original_currency": ["GBP"],
            "is_eligible_financial_collateral": [True],
            "is_eligible_irb_collateral": [True],
        }
    )


def _haircut_row(collateral_type: str, regime: str) -> dict:
    collateral = _collateral_lf(collateral_type)
    result = HaircutCalculator().apply_haircuts(collateral, _config(regime)).collect()
    return result.row(0, named=True)


def _bundle(collateral_type: str, market_value: float) -> ClassifiedExposuresBundle:
    """One £1m senior corporate-SME F-IRB exposure with one attested pledge."""
    exposures = pl.DataFrame(
        {
            "exposure_reference": ["EXP1"],
            "counterparty_reference": ["CP1"],
            "parent_facility_reference": pl.Series([None], dtype=pl.String),
            "exposure_class": [ExposureClass.CORPORATE_SME.value],
            "approach": [ApproachType.FIRB.value],
            "drawn_amount": [EAD],
            "ead_gross": [EAD],
            "lgd": pl.Series([None], dtype=pl.Float64),
            "pd": [0.02],
            "maturity_date": [date(2029, 12, 31)],
            "currency": ["GBP"],
            "seniority": ["senior"],
            "exposure_type": ["loan"],
            "nominal_amount": [0.0],
            "interest": [0.0],
            "undrawn_amount": [0.0],
            "risk_type": pl.Series([None], dtype=pl.String),
            "ccf_modelled": pl.Series([None], dtype=pl.Float64),
            "is_short_term_trade_lc": [False],
            "product_type": ["TERM_LOAN"],
            "value_date": [date(2024, 1, 1)],
            "book_code": ["BOOK1"],
            "is_sft": [False],
        }
    ).lazy()
    exposures = with_ancestor_facilities(exposures)

    collateral = normalise_collateral(
        pl.DataFrame(
            {
                "collateral_reference": ["COLL1"],
                "collateral_type": [collateral_type],
                "currency": ["GBP"],
                "market_value": [market_value],
                "value_after_maturity_adj": [market_value],
                "beneficiary_type": ["loan"],
                "beneficiary_reference": ["EXP1"],
                "maturity_date": [date(2035, 12, 31)],
                "issuer_type": [""],
                "issuer_cqs": [1],
                "is_main_index": [False],
                "is_eligible_financial_collateral": [False],
                "is_eligible_irb_collateral": [True],
                "residual_maturity_years": [10.0],
                "original_maturity_years": [15.0],
                "liquidation_period_days": [10],
            }
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
    processor: CRMProcessor, regime: str, collateral_type: str, market_value: float
) -> CRMAdjustedBundle:
    return processor.get_crm_unified_bundle(_bundle(collateral_type, market_value), _config(regime))


def _exposure_row(result: CRMAdjustedBundle) -> dict:
    collected = result.exposures.collect()
    return collected.filter(pl.col("exposure_reference") == "EXP1").row(0, named=True)


def _crm022(result: CRMAdjustedBundle) -> list:
    return [e for e in result.crm_errors if e.code == ERROR_BELOW_MIN_COLLATERALISATION]


# =============================================================================
# Tests: the haircut stage
# =============================================================================


class TestGenuineNonFinancialHaircut:
    """HC on genuine non-financial collateral is the regime's Art. 229/230 value."""

    @pytest.mark.parametrize("regime", ["crr", "b31"])
    @pytest.mark.parametrize(
        "collateral_type", ["other_physical", "equipment", "inventory", "other", "Other_Physical"]
    )
    def test_other_physical_collateral_takes_the_regime_hc(
        self, regime: str, collateral_type: str
    ) -> None:
        """CRR Art. 229(3) market value (HC 0); PS1/26 Art. 230(2) HC 40%."""
        # Arrange / Act
        row = _haircut_row(collateral_type, regime)

        # Assert
        assert row["collateral_haircut"] == pytest.approx(FCM_HC[regime], abs=1e-12)
        assert row["value_after_haircut"] == pytest.approx(MV * (1.0 - FCM_HC[regime]))

    @pytest.mark.parametrize("regime", ["crr", "b31"])
    @pytest.mark.parametrize("collateral_type", ["real_estate", "property", "receivables"])
    def test_property_and_receivables_keep_their_regime_hc(
        self, regime: str, collateral_type: str
    ) -> None:
        """Siblings that were already right: CRR 0 (Art. 229(1)-(2)), PS1/26 40%."""
        # Arrange / Act
        row = _haircut_row(collateral_type, regime)

        # Assert
        assert row["collateral_haircut"] == pytest.approx(FCM_HC[regime], abs=1e-12)


class TestFallThroughKeepsConservativeHaircut:
    """Types the Art. 224 lookup cannot place keep the 40% fall-through, scaled.

    They share the ``other_physical`` lookup token with genuine other physical
    collateral but are not Art. 229/230 collateral, so a fix keyed on the token
    (or on the CRM category, which maps an issuer-less ``bond`` to
    other_physical) instead of the raw collateral type would zero them too.
    """

    @pytest.mark.parametrize("regime", ["crr", "b31"])
    @pytest.mark.parametrize(
        "collateral_type",
        ["financial_collateral", "covered_bonds", "bond", "ciu", "unrecognised_widget"],
    )
    def test_unplaced_collateral_keeps_the_fall_through(
        self, regime: str, collateral_type: str
    ) -> None:
        """A ``bond`` with no issuer_type cannot be placed in Table 1 either."""
        # Arrange / Act
        row = _haircut_row(collateral_type, regime)

        # Assert
        assert row["collateral_haircut"] == pytest.approx(FALL_THROUGH_HC, rel=1e-9)


# =============================================================================
# Tests: F-IRB LGD* through CRMProcessor
# =============================================================================


class TestFirbLgdStar:
    """LGD* reads C at the Art. 229 value under CRR and ES after HC under PS1/26."""

    @pytest.mark.parametrize("regime", ["crr", "b31"])
    def test_pledge_inside_c_star_band_is_recognised(
        self, processor: CRMProcessor, regime: str
    ) -> None:
        """C/E = 40% clears CRR C* (30%); valuing C at 60% of MV dropped it to LGDU."""
        # Arrange / Act
        result = _run(processor, regime, "other_physical", 400_000.0)

        # Assert
        assert _exposure_row(result)["lgd_post_crm"] == pytest.approx(
            FIRB_LGD[(regime, "other_physical", 400_000.0)], abs=1e-6
        )
        assert _crm022(result) == []

    @pytest.mark.parametrize("regime", ["crr", "b31"])
    def test_pledge_at_c_double_star_secures_the_whole_exposure(
        self, processor: CRMProcessor, regime: str
    ) -> None:
        """CRR: C = 140% of E meets C** exactly, so LGD* is the full 40% LGDS."""
        # Arrange / Act
        result = _run(processor, regime, "other_physical", 1_400_000.0)

        # Assert
        assert _exposure_row(result)["lgd_post_crm"] == pytest.approx(
            FIRB_LGD[(regime, "other_physical", 1_400_000.0)], abs=1e-6
        )

    @pytest.mark.parametrize("regime", ["crr", "b31"])
    def test_real_estate_twin_does_not_move(self, processor: CRMProcessor, regime: str) -> None:
        """Control: the same pledge over property was already valued correctly."""
        # Arrange / Act
        result = _run(processor, regime, "real_estate", 400_000.0)

        # Assert
        assert _exposure_row(result)["lgd_post_crm"] == pytest.approx(
            FIRB_LGD[(regime, "real_estate", 400_000.0)], abs=1e-6
        )
        assert _crm022(result) == []

    @pytest.mark.parametrize(("regime", "expected"), [("crr", 400_000.0), ("b31", 240_000.0)])
    def test_other_physical_carrier_holds_the_regime_value(
        self, processor: CRMProcessor, regime: str, expected: float
    ) -> None:
        """C 08.01 col 0200 carrier: CRR Annex II reads the Art. 229(3) market
        value; PS1/26 Annex II reads the adjusted Ci after HC."""
        # Arrange / Act
        result = _run(processor, regime, "other_physical", 400_000.0)

        # Assert
        assert _exposure_row(result)["collateral_other_physical_value"] == pytest.approx(
            expected, rel=1e-9
        )
