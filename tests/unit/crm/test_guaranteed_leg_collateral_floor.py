"""
Unit tests enforcing RD-7: a guarantee row-split must not move the A-IRB
blended LGD input floor.

Coverage gap #1 (``docs/plans/irb-collateral-corep-reporting.md``): "No
committed portfolio pairs a guaranteed IRB leg with collateral. The whole
10,595-test estate was green through a real capital error in the first cut
of D3 for exactly this reason." An earlier revision of D3's fix split ALL
FOURTEEN collateral columns across guarantee legs, including the Art. 231
waterfall allocations (``crm_alloc_*``, ``total_collateral_for_lgd``). That
silently raised the A-IRB blended LGD floor on every guaranteed leg: the
floor (``engine/irb/formulas.py:454-461``,
``_lgd_floor_blended_expression``) divides those allocations by
``lgd_star_exposure_basis_expr()`` = ``ead_for_crm x (1 + HE)``, and
``ead_for_crm`` is NOT split -- it stays whole-exposure on every leg (RD-7's
stage-order finding). The blend is a rate, homogeneous of degree 0:
splitting only the numerator (the allocations) while the denominator
(``ead_for_crm``) stays whole raises the floor -- +2.55pp on the reviewer's
worked example (E' = 1,000,000, C = 425,000, LGDS 10%, LGDU 25%, coverage
0.4: 18.625% -> 21.175%).

This file is the enforcement RD-7's docstring reasoning alone cannot be: it
pairs a guarantee split with pledged collateral on the SAME exposure,
through the REAL CRM stage (``CRMProcessor.get_crm_unified_bundle`` -- the
real Art. 231 waterfall, the real guarantee split) and the REAL IRB
blended-floor formula (``apply_lgd_floor``), and asserts:

1. The floor is unchanged by the split -- derived from an equivalent
   UNGUARANTEED exposure, not hardcoded, so it survives a floor
   recalibration.
2. ``total_collateral_for_lgd`` and every ``crm_alloc_*`` stay whole-
   exposure on every leg, paired explicitly with the equally-whole
   ``ead_for_crm`` they are divided by -- pinning the REASON, not just the
   numbers.
3. The (up to thirteen) collateral VALUATION carriers (D3's disclosure
   half, ``COLLATERAL_VALUE_CARRIERS``) DO split and conserve across legs.
4. Both halves coexist on the SAME fixture, the SAME run -- the combination
   no committed fixture produces today.

Empirically verified before writing any assertion, per the brief: a
REAL-ESTATE pledge on this fixture's corporate/A-IRB exposure gets silently
reclassified to ``"commercial_mortgage"`` by the classifier's
``is_mortgage`` rule (``property_collateral_value > 0`` forces
``is_mortgage=True`` REGARDLESS of the borrower's entity_type --
``engine/stages/classify/attributes.py:625-639``), and
``"commercial_mortgage"`` is an SA-re-splitter-only class that NEVER reaches
an IRB row (``engine/irb/formulas.py``'s own docstring at :387-390
confirms: "residential_mortgage / commercial_mortgage ... Unreachable
today"). A "corporate + real-estate + A-IRB" fixture is therefore
UNREACHABLE in this engine via the classifier. This file pledges
OTHER_PHYSICAL collateral instead (LGDS 15% rather than real estate's 10%
-- a different branch of the SAME blended formula, equally probative for
RD-7's purpose), confirmed empirically to keep ``exposure_class ==
"corporate"`` and the blended floor reachable.

Fixture construction sets ``exposure_class`` / ``approach`` directly on a
``ClassifiedExposuresBundle``, bypassing the raw loader / classifier
entirely (mirrors the established ``tests/unit/crm/`` convention, e.g.
``test_p1_235_firb_fcm_eligibility_gate.py``). RD-7's question is about the
CRM-stage / IRB-formula interaction, not about classifier approach-routing,
so driving the full raw pipeline would add risk (and, as discovered above,
an unrelated classification trap) without adding rigour to what this file
needs to prove.

References:
    docs/plans/irb-collateral-corep-reporting.md, RD-7, coverage gap #1
    engine/irb/formulas.py:337-523 (_lgd_floor_blended_expression)
    engine/crm/guarantees.py:61-90 (_stock_split_cols / COLLATERAL_VALUE_CARRIERS)
    PRA PS1/26 Art. 161(5)(b) (corporate blended floor), Art. 230/231 (LGD*)
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest
from tests.fixtures.resolved_bundle import make_classified_bundle
from tests.unit.crm._crm_bundles import (
    empty_counterparty_lookup,
    normalise_collateral,
    with_ancestor_facilities,
)

from rwa_calc.contracts.bundles import ClassifiedExposuresBundle, CRMAdjustedBundle
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import ApproachType, ExposureClass, PermissionMode
from rwa_calc.engine.crm.expressions import COLLATERAL_VALUE_CARRIERS
from rwa_calc.engine.crm.processor import CRMProcessor
from rwa_calc.engine.irb.transforms import apply_lgd_floor

# =============================================================================
# Constants
# =============================================================================

# The Art. 231 waterfall allocation carriers -- deliberately NOT in
# _stock_split_cols() (RD-7): their sole consumer, the blended LGD floor,
# divides them by the unsplit ead_for_crm, so splitting them would move
# capital.
_ALLOCATION_CARRIERS: tuple[str, ...] = (
    "total_collateral_for_lgd",
    "crm_alloc_financial",
    "crm_alloc_covered_bond",
    "crm_alloc_receivables",
    "crm_alloc_real_estate",
    "crm_alloc_other_physical",
    "crm_alloc_life_insurance",
)

_EAD = 1_000_000.0
_COLLATERAL_VALUE = 425_000.0
_GUARANTEE_COVERED = 600_000.0
_RETAINED_SHARE = 1.0 - (_GUARANTEE_COVERED / _EAD)  # 40% retained on __REM


def _config() -> CalculationConfig:
    """Basel 3.1 -- the blended LGD floor is a Basel-3.1-only Feature."""
    return CalculationConfig.basel_3_1(
        reporting_date=date(2030, 6, 30), permission_mode=PermissionMode.IRB
    )


# =============================================================================
# Fixtures
# =============================================================================


def _exposure_row(ref: str, cp_ref: str, ead: float = _EAD, lgd: float = 0.05) -> dict:
    """One A-IRB corporate loan. exposure_class / approach are set directly
    -- bypassing the classifier (see module docstring)."""
    return {
        "exposure_reference": ref,
        "counterparty_reference": cp_ref,
        "parent_facility_reference": None,
        "exposure_class": ExposureClass.CORPORATE.value,
        "approach": ApproachType.AIRB.value,
        "drawn_amount": ead,
        "ead_gross": ead,
        "lgd": lgd,
        "pd": 0.01,
        "maturity_date": date(2029, 12, 31),
        "currency": "GBP",
        "original_currency": "GBP",
        "seniority": "senior",
        "exposure_type": "loan",
        "nominal_amount": 0.0,
        "interest": 0.0,
        "undrawn_amount": 0.0,
        "risk_type": None,
        "ccf_modelled": None,
        "is_short_term_trade_lc": False,
        "product_type": "TERM_LOAN",
        "value_date": date(2024, 1, 1),
        "book_code": "BOOK1",
        "is_sft": False,
    }


def _collateral_row(
    ref: str, beneficiary_ref: str, market_value: float = _COLLATERAL_VALUE
) -> dict:
    """One Art. 199(6) other-physical pledge. NOT real_estate -- see module
    docstring for why real estate is unreachable on a corporate A-IRB row."""
    return {
        "collateral_reference": ref,
        "collateral_type": "other_physical",
        "currency": "GBP",
        "market_value": market_value,
        "beneficiary_type": "loan",
        "beneficiary_reference": beneficiary_ref,
        "maturity_date": date(2035, 12, 31),
        "issuer_type": "",
        "issuer_cqs": 1,
        "is_main_index": False,
        "is_eligible_financial_collateral": False,
        "is_eligible_irb_collateral": True,
        "residual_maturity_years": 10.0,
        "original_maturity_years": 10.0,
        "liquidation_period_days": 10,
    }


@pytest.fixture(scope="module")
def crm_result() -> pl.DataFrame:
    """Run the real CRM stage once on the shared fixture: EXP_BASE
    (unguaranteed baseline) + EXP_GUAR (identical, 60% guaranteed by
    GUARANTOR -- splits into EXP_GUAR__G_GUARANTOR / EXP_GUAR__REM), both
    secured by an identical 425,000 other-physical pledge.
    """
    exposures = pl.DataFrame(
        [
            _exposure_row("EXP_BASE", cp_ref="CP_BASE"),
            _exposure_row("EXP_GUAR", cp_ref="CP_GUAR"),
        ]
    ).lazy()
    exposures = with_ancestor_facilities(exposures)

    collateral = normalise_collateral(
        pl.DataFrame(
            [
                _collateral_row("COLL_BASE", "EXP_BASE"),
                _collateral_row("COLL_GUAR", "EXP_GUAR"),
            ]
        ).lazy()
    )

    guarantees = pl.LazyFrame(
        {
            "beneficiary_reference": ["EXP_GUAR"],
            "amount_covered": [_GUARANTEE_COVERED],
            "guarantor": ["GUARANTOR"],
        }
    )

    bundle: ClassifiedExposuresBundle = make_classified_bundle(
        all_exposures=exposures,
        equity_exposures=None,
        collateral=collateral,
        guarantees=guarantees,
        provisions=None,
        counterparty_lookup=empty_counterparty_lookup(),
        classification_audit=None,
        classification_errors=[],
    )

    result: CRMAdjustedBundle = CRMProcessor().get_crm_unified_bundle(bundle, _config())
    return result.exposures.collect()


@pytest.fixture(scope="module")
def floored(crm_result: pl.DataFrame) -> pl.DataFrame:
    """Pipe the CRM output through the REAL blended-floor transform.

    ``is_airb`` / ``lgd_input`` are the only bridge columns
    ``apply_lgd_floor`` needs beyond what CRM already produces:
    ``is_airb`` from ``approach``, ``lgd_input`` from ``lgd_post_crm`` (the
    A-IRB own-estimate LGD, preserved unchanged by CRM for an A-IRB leg not
    on the LGD Modelling Collateral Method's FCM fallback).
    """
    bridged = crm_result.lazy().with_columns(
        (pl.col("approach") == ApproachType.AIRB.value).alias("is_airb"),
        pl.col("lgd_post_crm").alias("lgd_input"),
    )
    return bridged.pipe(apply_lgd_floor, _config()).collect()


def _row(df: pl.DataFrame, ref: str) -> pl.DataFrame:
    return df.filter(pl.col("exposure_reference") == ref)


# =============================================================================
# 1. The floor is unchanged by the split
# =============================================================================


class TestFloorUnchangedBySplit:
    """RD-7 assertion #1: the blended LGD floor on the __REM leg equals the
    unsplit exposure's floor -- derived from an equivalent unguaranteed
    exposure, not hardcoded, so this test survives a floor recalibration."""

    def test_rem_leg_floor_equals_unsplit_baseline_floor(self, floored: pl.DataFrame) -> None:
        # Arrange
        base = _row(floored, "EXP_BASE")
        rem = _row(floored, "EXP_GUAR__REM")

        # Assert -- the branch is actually reached (not a vacuous pass): a
        # null here means the blended floor deferred to the flat/single-
        # type fallback, and the comparison below would prove nothing.
        assert base["lgd_floored"][0] is not None

        # Assert -- the regression guard itself.
        assert rem["lgd_floored"][0] == pytest.approx(base["lgd_floored"][0])

    def test_guaranteed_leg_floor_also_matches(self, floored: pl.DataFrame) -> None:
        """The __G_ leg computes the identical floor too -- every input the
        formula reads (ead_for_crm, the allocations, exposure_class) is
        whole-exposure on both legs, so nothing distinguishes them."""
        # Arrange
        base = _row(floored, "EXP_BASE")
        guaranteed = _row(floored, "EXP_GUAR__G_GUARANTOR")

        # Assert
        assert guaranteed["lgd_floored"][0] == pytest.approx(base["lgd_floored"][0])


# =============================================================================
# 2. The Art. 231 allocations are NOT split -- paired with ead_for_crm
# =============================================================================


class TestAllocationsNotSplit:
    """RD-7 assertion #2: total_collateral_for_lgd and every crm_alloc_*
    stay whole-exposure on every leg -- paired explicitly with the equally
    whole ead_for_crm they are divided by, so the test pins the REASON (a
    rate whose numerator and denominator must move together), not just the
    numbers."""

    @pytest.mark.parametrize("column", _ALLOCATION_CARRIERS)
    def test_allocation_carrier_matches_unsplit_baseline(
        self, crm_result: pl.DataFrame, column: str
    ) -> None:
        # Arrange
        base = _row(crm_result, "EXP_BASE")
        rem = _row(crm_result, "EXP_GUAR__REM")
        guaranteed = _row(crm_result, "EXP_GUAR__G_GUARANTOR")

        # Assert
        assert rem[column][0] == pytest.approx(base[column][0])
        assert guaranteed[column][0] == pytest.approx(base[column][0])

    def test_ead_for_crm_is_paired_whole_exposure_too(self, crm_result: pl.DataFrame) -> None:
        """The allocations' consumer (the blended floor) divides them by
        ead_for_crm -- pin that IT is also unsplit, so the numerator/
        denominator pairing that keeps the floor unchanged actually holds
        on this fixture, not just on the allocations in isolation."""
        # Arrange
        base = _row(crm_result, "EXP_BASE")
        rem = _row(crm_result, "EXP_GUAR__REM")
        guaranteed = _row(crm_result, "EXP_GUAR__G_GUARANTOR")

        # Assert
        assert rem["ead_for_crm"][0] == pytest.approx(base["ead_for_crm"][0])
        assert guaranteed["ead_for_crm"][0] == pytest.approx(base["ead_for_crm"][0])


# =============================================================================
# 3. The collateral valuations ARE split and conserve
# =============================================================================


class TestValuationsSplitAndConserve:
    """RD-7 assertion #3: the collateral VALUATION carriers -- D3's
    disclosure half -- DO split and conserve across legs. Parametrized
    directly over ``engine.crm.expressions.COLLATERAL_VALUE_CARRIERS`` so
    this test cannot drift from the source (most are 0.0 on every leg here,
    since only other_physical collateral is pledged; the two other_physical
    carriers are the meaningful, nonzero cases)."""

    @pytest.mark.parametrize("column", COLLATERAL_VALUE_CARRIERS)
    def test_valuation_conserves_across_legs(self, crm_result: pl.DataFrame, column: str) -> None:
        # Arrange
        base = _row(crm_result, "EXP_BASE")
        rem = _row(crm_result, "EXP_GUAR__REM")
        guaranteed = _row(crm_result, "EXP_GUAR__G_GUARANTOR")

        # Act
        total = rem[column][0] + guaranteed[column][0]

        # Assert
        assert total == pytest.approx(base[column][0])

    def test_other_physical_value_is_genuinely_split_not_duplicated(
        self, crm_result: pl.DataFrame
    ) -> None:
        """Regression against the D3 double-count this file's sibling
        (test_guarantee_collateral_split.py) drives: each leg must carry
        its OWN share, strictly less than the full pre-split value -- not
        the whole value duplicated onto both legs."""
        # Arrange
        base = _row(crm_result, "EXP_BASE")
        rem = _row(crm_result, "EXP_GUAR__REM")
        guaranteed = _row(crm_result, "EXP_GUAR__G_GUARANTOR")

        # Assert
        assert (
            rem["collateral_other_physical_value"][0] < base["collateral_other_physical_value"][0]
        )
        assert (
            guaranteed["collateral_other_physical_value"][0]
            < base["collateral_other_physical_value"][0]
        )


# =============================================================================
# 4. Both halves coexist on the same leg, the same run
# =============================================================================


class TestBothHalvesCoexist:
    """RD-7 assertion #4: on the SAME leg, in the SAME run, the allocations
    stay whole while the valuations split -- the combination RD-7 records
    no committed fixture produces."""

    def test_rem_leg_carries_whole_allocation_and_split_valuation(
        self, crm_result: pl.DataFrame
    ) -> None:
        # Arrange
        base = _row(crm_result, "EXP_BASE")
        rem = _row(crm_result, "EXP_GUAR__REM")

        # Assert -- the allocation: whole-exposure, unchanged from baseline.
        assert rem["crm_alloc_other_physical"][0] == pytest.approx(
            base["crm_alloc_other_physical"][0]
        )
        # Assert -- the valuation: this leg's own pro-rata share (the 40%
        # retained by the fixture's 60%-covered guarantee), not the full
        # baseline value.
        assert rem["collateral_other_physical_value"][0] == pytest.approx(
            base["collateral_other_physical_value"][0] * _RETAINED_SHARE
        )
