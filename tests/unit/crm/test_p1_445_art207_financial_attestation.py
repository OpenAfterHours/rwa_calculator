"""
P1.445 (review CL-06) — Art. 207: F-IRB recognises only attested financial collateral.

CRR Art. 207(1): "Under all approaches and methods, financial collateral and gold
shall qualify as eligible collateral where all the requirements laid down in
paragraphs 2 to 4 are met." PS1/26 Art. 207(1) names the Foundation Collateral
Method next to the other three: "An institution using the Financial Collateral
Simple Method, the Financial Collateral Comprehensive Method, the Foundation
Collateral Method or the SFT VaR Method may use financial collateral and gold as
eligible collateral where all the requirements laid down in paragraphs 2 to 4 are
met." Paragraphs 2-4 are correlation, legal certainty and the operational
requirements; paragraph 5 (residual maturity) binds the Simple Method only.

``is_eligible_financial_collateral`` is the firm's attestation of those
requirements. The Standardised Approach already honours it (an unattested pledge
reduces no exposure value); before this item the F-IRB Art. 231 waterfall read the
collateral CATEGORY only, so an unattested cash or debt-security pledge still
drove LGD* to the secured value — and reported in C 08.01/02 col 0180 and fed the
Basel 3.1 A-IRB Art. 161(5) LGD input floor through ``crm_alloc_financial``.

The loader seals the column to False when it is absent or null, so "unset" and
"marked as failing" are one population: both are unattested.

Hand calculation (F-IRB corporate, senior, non-FSE; E = 10,000,000; one direct
6,000,000 pledge; LGDU 45% CRR / 40% Basel 3.1; LGDS 0% for financial collateral):
    cash, attested:          C = 6,000,000
        CRR  LGD* = 0.45 x 4,000,000 / 10,000,000 = 0.18
        B31  LGD* = 0.40 x 4,000,000 / 10,000,000 = 0.16
    CQS 1 sovereign bond, 10y residual, 10-day period, attested: H_c = 4% (both
    regimes), C = 6,000,000 x 0.96 = 5,760,000
        CRR  LGD* = 0.45 x 4,240,000 / 10,000,000 = 0.1908
        B31  LGD* = 0.40 x 4,240,000 / 10,000,000 = 0.1696
    either type, unattested (False or null): C = 0 -> LGD* = LGDU = 0.45 / 0.40
    (pre-fix: the attested values above, whatever the flag).

The end-to-end legs use the pipeline harness (loan 100,000, 60,000 cash):
attested CRR 0.18 / B31 0.16; unattested 0.45 / 0.40.

Pipeline position:
    tests/unit — direct CRMProcessor.get_crm_unified_bundle drive, a direct
    CRMProcessor.apply_collateral drive (no flag column), and the full
    PipelineOrchestrator through ``_pipeline_harness``.

References:
    - CRR Art. 197(1), 207(1)-(4); PS1/26 Art. 197(1), 207(1)-(4).
    - PS1/26 Art. 161(5)(b): the A-IRB LGD input floor, "using the Foundation
      Collateral Method".
    - CRR Annex II / PS1/26 Annex II C 08.01 col 0180 (eligible financial collateral).
    - IMPLEMENTATION_PLAN.md: P1.445 (product review CL-06).
"""

from __future__ import annotations

from datetime import date
from typing import Any

import polars as pl
import pytest
from tests.fixtures.raw_bundle import make_raw_bundle
from tests.fixtures.resolved_bundle import make_classified_bundle
from tests.unit.crm import _pipeline_harness as harness
from tests.unit.crm._crm_bundles import normalise_collateral, with_ancestor_facilities

from rwa_calc.contracts.bundles import (
    ClassifiedExposuresBundle,
    CRMAdjustedBundle,
    create_empty_counterparty_lookup,
)
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import ApproachType, ExposureClass, PermissionMode
from rwa_calc.engine.crm.processor import CRMProcessor
from rwa_calc.engine.pipeline import PipelineOrchestrator

#: The rolled-up warning naming financial collateral not attested under Art. 207.
CRM031 = "CRM031"

#: Unsecured supervisory LGD, senior non-FSE corporate (CRR Art. 161(1)(a) /
#: PS1/26 Art. 161(1)(aa)).
LGDU = {"crr": 0.45, "b31": 0.40}

#: Attested LGD* per (regime, collateral type) — see the module docstring.
ATTESTED_LGD = {
    ("crr", "cash"): 0.18,
    ("b31", "cash"): 0.16,
    ("crr", "government_bond"): 0.1908,
    ("b31", "government_bond"): 0.1696,
}

#: Recognised collateral C per collateral type (post-haircut, LGDS 0%).
ATTESTED_C = {"cash": 6_000_000.0, "government_bond": 5_760_000.0}

#: The per-type carrier each collateral type reports through (C 08.01 col 0180
#: sums the two).
TYPE_CARRIER = {"cash": "collateral_cash_value", "government_bond": "collateral_financial_value"}

_ABSENT = object()


def _config(regime: str) -> CalculationConfig:
    if regime == "crr":
        return CalculationConfig.crr(
            reporting_date=date(2026, 6, 30), permission_mode=PermissionMode.IRB
        )
    return CalculationConfig.basel_3_1(
        reporting_date=date(2027, 6, 30), permission_mode=PermissionMode.IRB
    )


def _exposures() -> pl.LazyFrame:
    exposures = pl.DataFrame(
        {
            "exposure_reference": ["EXP1"],
            "counterparty_reference": ["CP1"],
            "parent_facility_reference": [None],
            "exposure_class": [ExposureClass.CORPORATE.value],
            "approach": [ApproachType.FIRB.value],
            "drawn_amount": [10_000_000.0],
            "ead_gross": [10_000_000.0],
            "lgd": [None],
            "pd": [0.02],
            "maturity_date": [date(2029, 12, 31)],
            "currency": ["GBP"],
            "seniority": ["senior"],
            "exposure_type": ["loan"],
            "nominal_amount": [0.0],
            "interest": [0.0],
            "undrawn_amount": [0.0],
            "risk_type": [None],
            "ccf_modelled": [None],
            "is_short_term_trade_lc": [False],
            "product_type": ["TERM_LOAN"],
            "value_date": [date(2024, 1, 1)],
            "book_code": ["BOOK1"],
            "is_sft": [False],
        }
    ).lazy()
    exposures = exposures.with_columns(pl.col("parent_facility_reference").cast(pl.String))
    return with_ancestor_facilities(exposures)


def _collateral(collateral_type: str, flag: Any) -> pl.LazyFrame:
    """One direct 6,000,000 pledge; ``flag`` is True / False / None or ``_ABSENT``.

    ``is_eligible_irb_collateral`` is True so the Art. 199 attestation (which
    governs non-financial collateral) cannot be what recognises the pledge.
    """
    data: dict[str, list[Any]] = {
        "collateral_reference": ["DEP1"],
        "collateral_type": [collateral_type],
        "currency": ["GBP"],
        "market_value": [6_000_000.0],
        "beneficiary_type": ["loan"],
        "beneficiary_reference": ["EXP1"],
        "issuer_type": ["sovereign"],
        "issuer_cqs": [1],
        "is_main_index": [False],
        "is_eligible_irb_collateral": [True],
        "residual_maturity_years": [10.0],
        "liquidation_period_days": [10],
    }
    if flag is not _ABSENT:
        data["is_eligible_financial_collateral"] = [flag]
    return normalise_collateral(
        pl.DataFrame(data, schema_overrides={"is_eligible_financial_collateral": pl.Boolean}).lazy()
    )


def _bundle(collateral_type: str, flag: Any) -> ClassifiedExposuresBundle:
    return make_classified_bundle(
        all_exposures=_exposures(),
        equity_exposures=None,
        collateral=_collateral(collateral_type, flag),
        guarantees=None,
        provisions=None,
        counterparty_lookup=create_empty_counterparty_lookup(),
        classification_audit=None,
        classification_errors=[],
    )


def _run(regime: str, collateral_type: str, flag: Any) -> CRMAdjustedBundle:
    return CRMProcessor().get_crm_unified_bundle(_bundle(collateral_type, flag), _config(regime))


def _row(result: CRMAdjustedBundle) -> dict[str, Any]:
    return (
        result.exposures.collect().filter(pl.col("exposure_reference") == "EXP1").row(0, named=True)
    )


def _crm031(result: CRMAdjustedBundle) -> list:
    return [e for e in result.crm_errors if e.code == CRM031]


_REGIMES = pytest.mark.parametrize("regime", ["crr", "b31"])
_TYPES = pytest.mark.parametrize("collateral_type", ["cash", "government_bond"])
_UNATTESTED = pytest.mark.parametrize("flag", [False, None], ids=["false", "null"])


class TestUnattestedFinancialCollateralUnderFirb:
    """False / null attestation: no LGD* relief, no carrier, one CRM031."""

    @_REGIMES
    @_TYPES
    @_UNATTESTED
    def test_lgd_is_the_unsecured_supervisory_value(
        self, regime: str, collateral_type: str, flag: bool | None
    ) -> None:
        # Act
        row = _row(_run(regime, collateral_type, flag))

        # Assert: pre-fix 0.18 / 0.16 (cash) and 0.1908 / 0.1696 (bond).
        assert row["lgd_post_crm"] == pytest.approx(LGDU[regime], rel=1e-12)

    @_REGIMES
    @_TYPES
    @_UNATTESTED
    def test_no_lgd_collateral_carrier_is_populated(
        self, regime: str, collateral_type: str, flag: bool | None
    ) -> None:
        # Act
        row = _row(_run(regime, collateral_type, flag))

        # Assert: the waterfall feed, the Art. 161(5) floor feed (crm_alloc_financial)
        # and both col 0180 carriers are all zero (pre-fix C on every one).
        assert row["total_collateral_for_lgd"] == pytest.approx(0.0, abs=1e-9)
        assert row["crm_alloc_financial"] == pytest.approx(0.0, abs=1e-9)
        assert row["collateral_financial_value"] == pytest.approx(0.0, abs=1e-9)
        assert row["collateral_cash_value"] == pytest.approx(0.0, abs=1e-9)

    @_REGIMES
    @_TYPES
    @_UNATTESTED
    def test_one_rolled_up_crm031_names_the_pledge(
        self, regime: str, collateral_type: str, flag: bool | None
    ) -> None:
        # Act
        warnings = _crm031(_run(regime, collateral_type, flag))

        # Assert
        assert len(warnings) == 1
        assert "DEP1" in warnings[0].message


class TestAttestedFinancialCollateralUnderFirb:
    """Control: an attested pledge keeps its LGDS 0% recognition, and no CRM031."""

    @_REGIMES
    @_TYPES
    def test_lgd_is_the_secured_blend(self, regime: str, collateral_type: str) -> None:
        # Act
        row = _row(_run(regime, collateral_type, True))

        # Assert
        assert row["lgd_post_crm"] == pytest.approx(
            ATTESTED_LGD[(regime, collateral_type)], rel=1e-12
        )

    @_REGIMES
    @_TYPES
    def test_carriers_hold_the_recognised_value(self, regime: str, collateral_type: str) -> None:
        # Act
        result = _run(regime, collateral_type, True)
        row = _row(result)

        # Assert
        assert row[TYPE_CARRIER[collateral_type]] == pytest.approx(ATTESTED_C[collateral_type])
        assert row["crm_alloc_financial"] == pytest.approx(ATTESTED_C[collateral_type])
        assert _crm031(result) == []


class TestDirectCallerWithoutTheFlagColumn:
    """A hand-built frame with NO flag column keeps the type-only reading.

    ``CRMProcessor.apply_collateral`` takes the collateral frame as given (the
    netting rows are not concatenated in, so the column stays genuinely absent —
    LESSONS B1). Production frames always carry the column: the loader seals it.
    """

    @_REGIMES
    def test_absent_flag_is_recognised_by_type(self, regime: str) -> None:
        # Arrange
        config = _config(regime)
        exposures = _exposures().with_columns(pl.lit(LGDU[regime]).alias("lgd_pre_crm"))
        collateral = _collateral("cash", _ABSENT)
        assert "is_eligible_financial_collateral" not in collateral.collect_schema().names()

        # Act
        out = CRMProcessor().apply_collateral(exposures, collateral, config).collect()

        # Assert: the whole 6,000,000 reaches the waterfall and the col 0180 carrier.
        assert out["total_collateral_for_lgd"][0] == pytest.approx(ATTESTED_C["cash"])
        assert out["collateral_cash_value"][0] == pytest.approx(ATTESTED_C["cash"])


def _pipeline_run(regime: str, *, firb: bool, flag: Any) -> tuple[dict[str, Any], set[str]]:
    pledge: dict[str, Any] = {
        "collateral_reference": "C1",
        "collateral_type": "cash",
        "market_value": 60_000.0,
        "beneficiary_type": "loan",
        "beneficiary_reference": "L1",
    }
    if flag is not _ABSENT:
        pledge["is_eligible_financial_collateral"] = flag
    results, errors = harness.run(
        regime,
        firb=firb,
        loans=harness.loans(
            [{"loan_reference": "L1", "counterparty_reference": "CP1", "drawn_amount": 100_000.0}]
        ),
        collateral=harness.collateral([pledge]),
    )
    return harness.row(results, "L1"), harness.codes(errors)


class TestEndToEndThroughTheLoaderSeal:
    """The production path: a collateral file WITHOUT the column is sealed to False."""

    @_REGIMES
    def test_absent_column_gives_the_unsecured_lgd(self, regime: str) -> None:
        # Act
        row, codes = _pipeline_run(regime, firb=True, flag=_ABSENT)

        # Assert: pre-fix 0.18 / 0.16 and col 0180 carrying 60,000.
        assert row["approach_applied"] == "foundation_irb"
        assert row["lgd_post_crm"] == pytest.approx(LGDU[regime], rel=1e-12)
        assert row["reporting_crm_lgd_financial"] == pytest.approx(0.0, abs=1e-9)
        assert CRM031 in codes

    @_REGIMES
    def test_attested_cash_reduces_lgd(self, regime: str) -> None:
        # Act
        row, codes = _pipeline_run(regime, firb=True, flag=True)

        # Assert
        assert row["lgd_post_crm"] == pytest.approx(ATTESTED_LGD[(regime, "cash")], rel=1e-12)
        assert row["reporting_crm_lgd_financial"] == pytest.approx(60_000.0)
        assert CRM031 not in codes

    @_REGIMES
    def test_sa_exposure_value_is_unchanged_and_named(self, regime: str) -> None:
        # Act
        row, codes = _pipeline_run(regime, firb=False, flag=_ABSENT)

        # Assert: the SA already ignored the unattested pledge (EAD 100,000 before
        # and after this item); CRM031 now says why.
        assert row["ead_final"] == pytest.approx(100_000.0)
        assert CRM031 in codes


def _airb_b31_run(flag: bool) -> dict[str, Any]:
    """Basel 3.1 A-IRB SME corporate, modelled LGD 5%, 60,000 cash on a 100,000 loan."""
    frames = {
        "counterparties": harness.counterparties("CP1").with_columns(
            pl.lit(20_000_000.0).alias("annual_revenue"),
            pl.lit(20_000_000.0).alias("turnover_eur"),
        ),
        "loans": harness.loans(
            [
                {
                    "loan_reference": "L1",
                    "counterparty_reference": "CP1",
                    "drawn_amount": 100_000.0,
                    "lgd": 0.05,
                }
            ]
        ),
        "collateral": harness.collateral(
            [
                {
                    "collateral_reference": "C1",
                    "collateral_type": "cash",
                    "market_value": 60_000.0,
                    "beneficiary_type": "loan",
                    "beneficiary_reference": "L1",
                    "is_eligible_financial_collateral": flag,
                }
            ]
        ),
        "ratings": pl.DataFrame(
            [
                {
                    "rating_reference": "R1",
                    "counterparty_reference": "CP1",
                    "pd": 0.01,
                    "rating_type": "internal",
                    "rating_date": date(2025, 12, 31),
                    "model_id": "M1",
                }
            ]
        ),
        "model_permissions": pl.DataFrame(
            [
                {"model_id": "M1", "exposure_class": exposure_class, "approach": "advanced_irb"}
                for exposure_class in ("corporate", "corporate_sme")
            ]
        ),
    }
    config = CalculationConfig.basel_3_1(
        reporting_date=harness.REPORTING_DATES["b31"], permission_mode=PermissionMode.IRB
    )
    result = PipelineOrchestrator().run_with_data(make_raw_bundle(**frames), config)
    return harness.row(result.results.collect(), "L1")


class TestBasel31AirbLgdInputFloor:
    """PS1/26 Art. 161(5)(b): the A-IRB LGD input floor blends "using the Foundation
    Collateral Method", so only Art. 207-attested cash takes the 0% LGDS floor.

    Floor = 25% x EU / E + 0% x ES / E: attested 0.25 x 40,000 / 100,000 = 0.10;
    unattested 0.25 (pre-fix 0.10 either way). CRR has no A-IRB LGD input floor
    for corporates (pack Feature ``airb_lgd_floor`` is off), so this leg is Basel
    3.1 only by rule — the CRR half of the item is the F-IRB LGD* legs above.
    """

    @pytest.mark.parametrize(("flag", "expected_floor"), [(True, 0.10), (False, 0.25)])
    def test_floor_counts_only_attested_cash(self, flag: bool, expected_floor: float) -> None:
        # Act
        row = _airb_b31_run(flag)

        # Assert
        assert row["approach_applied"] == "advanced_irb"
        assert row["lgd_input"] == pytest.approx(0.05)
        assert row["lgd_floored"] == pytest.approx(expected_floor, rel=1e-12)
