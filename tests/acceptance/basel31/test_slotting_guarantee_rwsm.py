"""
Slotting guarantee RWSM — Art. 235(1) substitution on slotting-approach legs.

Pipeline position:
    Loader -> HierarchyResolver -> Classifier -> CRMProcessor
        -> SlottingCalculator (NEW: guarantee substitution + Art. 235(1A)
           EL zeroing) -> OutputAggregator

Key assertion (the recorded slotting-guarantee gap, fixed):
    A guaranteed slotting exposure's covered ``__G_`` leg takes the
    guarantor's SA risk weight (RWSM, Art. 235(1)); the covered leg's
    slotting EL is zeroed (Art. 235(1A) — the covered part is an exposure
    to a guarantor treated under SA, which carries no slotting EL); the
    retained ``__REM`` leg keeps the borrower slotting basis; and
    non-beneficial guarantees change nothing. Recorded decision
    (2026-07-12, operator): the treatment applies under BOTH regimes via
    the cited pack Feature ``slotting_guarantee_substitution`` (PS1/26
    Part 3 mandates RWSM; the CRR-side black-letter basis is recorded as
    unsettled — COREP Annex II para 43 + the Art. 235 analogy).

Hand-calc (10M project-finance Strong, >=2.5y so the base table applies):
    Borrower slotting RW: strong base = 0.70 (CRR and B31 tables agree)
    Borrower slotting EL rate: strong base = 0.4% -> 40,000 on 10M
    Guarantor: GB sovereign, external CQS 1 -> SA RW 0.00 (both regimes)

    Full cover (100%):
        __G_ leg:  EAD 10,000,000, RW 0.00, RWA 0, EL 0
        __REM leg: EAD 0,          RW 0.70, RWA 0, EL 0
        total RWA 0 (pre-fix bug: 7,000,000); total EL 0 (pre-fix 40,000)
        guarantee_rwa_benefit on __G_ = 10,000,000 x (0.70 - 0.00) = 7,000,000
    Partial cover (60%):
        __G_ leg:  EAD 6,000,000, RW 0.00, RWA 0, EL 0
        __REM leg: EAD 4,000,000, RW 0.70, RWA 2,800,000, EL 16,000
    Non-beneficial (unrated corporate guarantor, SA RW 1.00 > 0.70):
        no substitution; __G_ leg keeps RW 0.70; total RWA 7,000,000.

References:
    - PS1/26 Art. 235(1) (RWSM blend), Art. 235(1A) (covered-part EL)
    - CRR Art. 213-217 (unfunded protection; beneficial-only application)
    - docs/plans/phase7-declarative-reporting.md (the recorded gap + fix)
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig, IRBPermissions
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import (
    COUNTERPARTY_SCHEMA,
    FACILITY_MAPPING_SCHEMA,
    FACILITY_SCHEMA,
    GUARANTEE_SCHEMA,
    LENDING_MAPPING_SCHEMA,
    LOAN_SCHEMA,
    RATINGS_SCHEMA,
    SPECIALISED_LENDING_SCHEMA,
)
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.fixtures.raw_bundle import make_raw_bundle

_BORROWER = "CP_SL_PF"
_SOV_GUARANTOR = "SOV_GTR"
_CORP_GUARANTOR = "CORP_GTR"
_LOAN = "SL_LOAN_G"


def _run(
    config: CalculationConfig,
    *,
    percentage_covered: float = 1.0,
    guarantor: str = _SOV_GUARANTOR,
) -> pl.DataFrame:
    counterparties = pl.DataFrame(
        [
            {
                "counterparty_reference": _BORROWER,
                "counterparty_name": "PF SPV",
                "entity_type": "specialised_lending",
                "country_code": "GB",
                "default_status": False,
                "apply_fi_scalar": False,
                "is_managed_as_retail": False,
            },
            {
                "counterparty_reference": _SOV_GUARANTOR,
                "counterparty_name": "UK Sovereign",
                "entity_type": "sovereign",
                "country_code": "GB",
                "default_status": False,
                "apply_fi_scalar": False,
                "is_managed_as_retail": False,
            },
            {
                "counterparty_reference": _CORP_GUARANTOR,
                "counterparty_name": "Unrated Corp",
                "entity_type": "corporate",
                "country_code": "GB",
                "default_status": False,
                "apply_fi_scalar": False,
                "is_managed_as_retail": False,
            },
        ],
        schema=dtypes_of(COUNTERPARTY_SCHEMA),
    )
    loans = pl.DataFrame(
        [
            {
                "loan_reference": _LOAN,
                "product_type": "term_loan",
                "counterparty_reference": _BORROWER,
                "currency": "GBP",
                "value_date": date(2024, 1, 1),
                "maturity_date": date(2030, 12, 31),
                "drawn_amount": 10_000_000.0,
                "interest": 0.0,
                "seniority": "senior",
            },
        ],
        schema=dtypes_of(LOAN_SCHEMA),
    )
    sl_meta = pl.DataFrame(
        [
            {
                "counterparty_reference": _BORROWER,
                "sl_type": "project_finance",
                "slotting_category": "strong",
                "is_hvcre": False,
            },
        ],
        schema=dtypes_of(SPECIALISED_LENDING_SCHEMA),
    )
    guarantees = pl.DataFrame(
        [
            {
                "guarantee_reference": "GTE_SL",
                "guarantee_type": "guarantee",
                "guarantor": guarantor,
                "currency": "GBP",
                "maturity_date": date(2030, 12, 31),
                "amount_covered": 10_000_000.0 * percentage_covered,
                "percentage_covered": percentage_covered,
                "beneficiary_type": "loan",
                "beneficiary_reference": _LOAN,
                "protection_type": "guarantee",
                "includes_restructuring": True,
                "original_maturity_years": 6.0,
                "guarantor_seniority": "senior",
            },
        ],
        schema=dtypes_of(GUARANTEE_SCHEMA),
    )
    ratings = pl.DataFrame(
        [
            {
                "rating_reference": "RTG_SOV",
                "counterparty_reference": _SOV_GUARANTOR,
                "rating_type": "external",
                "rating_agency": "S&P",
                "rating_value": "AAA",
                "cqs": 1,
                "pd": None,
                "rating_date": date(2024, 1, 1),
                "is_solicited": True,
                "model_id": None,
            },
        ],
        schema=dtypes_of(RATINGS_SCHEMA),
    )
    bundle = make_raw_bundle(
        facilities=pl.LazyFrame(schema=dtypes_of(FACILITY_SCHEMA)),
        loans=loans,
        counterparties=counterparties,
        facility_mappings=pl.LazyFrame(schema=dtypes_of(FACILITY_MAPPING_SCHEMA)),
        lending_mappings=pl.LazyFrame(schema=dtypes_of(LENDING_MAPPING_SCHEMA)),
        guarantees=guarantees,
        ratings=ratings,
        specialised_lending=sl_meta,
    )
    result = PipelineOrchestrator().run_with_data(bundle, config)
    return result.results.filter(pl.col("exposure_reference").str.starts_with(_LOAN)).collect()


def _crr_config() -> CalculationConfig:
    return replace(
        CalculationConfig.crr(reporting_date=date(2024, 12, 31)),
        irb_permissions=IRBPermissions.full_irb(),
    )


def _b31_config() -> CalculationConfig:
    return replace(
        CalculationConfig.basel_3_1(reporting_date=date(2027, 12, 31)),
        irb_permissions=IRBPermissions.full_irb(),
    )


def _leg(df: pl.DataFrame, role: str) -> dict:
    rows = df.filter(pl.col("reporting_leg_role") == role).to_dicts()
    assert len(rows) == 1, f"expected one {role} leg, got {len(rows)}"
    return rows[0]


class TestSlottingRwsmFullCoverCRR:
    """CRR, 100% sovereign CQS1 cover: RWA 7.0M -> 0; EL 40k -> 0."""

    @pytest.fixture(scope="class")
    def results(self) -> pl.DataFrame:
        return _run(_crr_config())

    def test_covered_leg_takes_guarantor_rw(self, results: pl.DataFrame) -> None:
        guaranteed = _leg(results, "guaranteed")
        assert guaranteed["risk_weight"] == pytest.approx(0.0)
        assert guaranteed["rwa_final"] == pytest.approx(0.0)

    def test_covered_leg_el_zeroed(self, results: pl.DataFrame) -> None:
        guaranteed = _leg(results, "guaranteed")
        assert guaranteed["expected_loss"] == pytest.approx(0.0)
        assert guaranteed["el_shortfall"] == pytest.approx(0.0)

    def test_total_rwa_zero(self, results: pl.DataFrame) -> None:
        assert float(results["rwa_final"].sum()) == pytest.approx(0.0)

    def test_guarantee_rwa_benefit_on_slotting_leg(self, results: pl.DataFrame) -> None:
        """F8: the covered slotting leg now carries a REAL benefit —
        10M x (0.70 - 0.00) — instead of the pre-fix null/leak."""
        guaranteed = _leg(results, "guaranteed")
        assert guaranteed["guarantee_rwa_benefit"] == pytest.approx(7_000_000.0)

    def test_retained_leg_keeps_borrower_basis(self, results: pl.DataFrame) -> None:
        retained = _leg(results, "retained")
        assert retained["risk_weight"] == pytest.approx(0.70)
        assert retained["ead_final"] == pytest.approx(0.0)

    def test_covered_leg_pre_crm_risk_weight_is_slotting_base(self, results: pl.DataFrame) -> None:
        """The substitution snapshot (``pre_crm_risk_weight``) is taken from
        the strong-category slotting base (0.70) BEFORE the guarantor's RW
        overwrites ``risk_weight`` — the same 0.70 used transitively by
        ``guarantee_rwa_benefit`` above, asserted here directly."""
        guaranteed = _leg(results, "guaranteed")
        assert guaranteed["pre_crm_risk_weight"] == pytest.approx(0.70)


class TestSlottingRwsmPartialCoverCRR:
    """CRR, 60% cover: total RWA 7.0M -> 2.8M; EL 40k -> 16k."""

    @pytest.fixture(scope="class")
    def results(self) -> pl.DataFrame:
        return _run(_crr_config(), percentage_covered=0.6)

    def test_leg_split(self, results: pl.DataFrame) -> None:
        guaranteed = _leg(results, "guaranteed")
        retained = _leg(results, "retained")
        assert guaranteed["ead_final"] == pytest.approx(6_000_000.0)
        assert guaranteed["risk_weight"] == pytest.approx(0.0)
        assert retained["ead_final"] == pytest.approx(4_000_000.0)
        assert retained["risk_weight"] == pytest.approx(0.70)

    def test_total_rwa(self, results: pl.DataFrame) -> None:
        assert float(results["rwa_final"].sum()) == pytest.approx(2_800_000.0)

    def test_retained_el_only(self, results: pl.DataFrame) -> None:
        guaranteed = _leg(results, "guaranteed")
        retained = _leg(results, "retained")
        assert guaranteed["expected_loss"] == pytest.approx(0.0)
        assert retained["expected_loss"] == pytest.approx(16_000.0)


class TestSlottingRwsmNonBeneficialCRR:
    """CRR, unrated corporate guarantor (SA RW 1.00 > slotting 0.70):
    no substitution — the guarantee must never increase RWA."""

    @pytest.fixture(scope="class")
    def results(self) -> pl.DataFrame:
        return _run(_crr_config(), guarantor=_CORP_GUARANTOR)

    def test_no_substitution(self, results: pl.DataFrame) -> None:
        guaranteed = _leg(results, "guaranteed")
        assert guaranteed["risk_weight"] == pytest.approx(0.70)
        assert guaranteed["guarantee_rwa_benefit"] == pytest.approx(0.0)

    def test_total_rwa_unchanged(self, results: pl.DataFrame) -> None:
        assert float(results["rwa_final"].sum()) == pytest.approx(7_000_000.0)

    def test_el_not_zeroed(self, results: pl.DataFrame) -> None:
        """Non-beneficial: the covered part is NOT substituted, so its
        slotting EL stands (0.4% x 10M)."""
        assert float(results["expected_loss"].sum()) == pytest.approx(40_000.0)


class TestSlottingRwsmFullCoverB31:
    """B31, 100% sovereign CQS1 cover: the same table values apply
    (strong base 0.70; sovereign CQS1 0.00) — RWA 0, EL 0."""

    @pytest.fixture(scope="class")
    def results(self) -> pl.DataFrame:
        return _run(_b31_config())

    def test_covered_leg_takes_guarantor_rw(self, results: pl.DataFrame) -> None:
        guaranteed = _leg(results, "guaranteed")
        assert guaranteed["risk_weight"] == pytest.approx(0.0)

    def test_guarantee_rwa_benefit_slotting_basis(self, results: pl.DataFrame) -> None:
        """F8 leak fix: the benefit is computed on the SLOTTING borrower
        basis (0.70), not the unified-pass SA-default 1.0 base."""
        guaranteed = _leg(results, "guaranteed")
        assert guaranteed["guarantee_rwa_benefit"] == pytest.approx(7_000_000.0)

    def test_covered_leg_el_zeroed(self, results: pl.DataFrame) -> None:
        guaranteed = _leg(results, "guaranteed")
        assert guaranteed["expected_loss"] == pytest.approx(0.0)


class TestSlottingRwsmPartialCoverB31:
    """B31, 60% cover: total RWA 7.0M -> 2.8M; EL 40k -> 16k (same table
    values as CRR — strong base 0.70, sovereign CQS1 0.00)."""

    @pytest.fixture(scope="class")
    def results(self) -> pl.DataFrame:
        return _run(_b31_config(), percentage_covered=0.6)

    def test_leg_split(self, results: pl.DataFrame) -> None:
        guaranteed = _leg(results, "guaranteed")
        retained = _leg(results, "retained")
        assert guaranteed["ead_final"] == pytest.approx(6_000_000.0)
        assert guaranteed["risk_weight"] == pytest.approx(0.0)
        assert retained["ead_final"] == pytest.approx(4_000_000.0)
        assert retained["risk_weight"] == pytest.approx(0.70)

    def test_total_rwa(self, results: pl.DataFrame) -> None:
        assert float(results["rwa_final"].sum()) == pytest.approx(2_800_000.0)

    def test_retained_el_only(self, results: pl.DataFrame) -> None:
        guaranteed = _leg(results, "guaranteed")
        retained = _leg(results, "retained")
        assert guaranteed["expected_loss"] == pytest.approx(0.0)
        assert retained["expected_loss"] == pytest.approx(16_000.0)


class TestSlottingRwsmNonBeneficialB31:
    """B31, unrated corporate guarantor (SA RW 1.00 > slotting 0.70):
    no substitution — the guarantee must never increase RWA."""

    @pytest.fixture(scope="class")
    def results(self) -> pl.DataFrame:
        return _run(_b31_config(), guarantor=_CORP_GUARANTOR)

    def test_no_substitution(self, results: pl.DataFrame) -> None:
        guaranteed = _leg(results, "guaranteed")
        assert guaranteed["risk_weight"] == pytest.approx(0.70)
        assert guaranteed["guarantee_rwa_benefit"] == pytest.approx(0.0)

    def test_total_rwa_unchanged(self, results: pl.DataFrame) -> None:
        assert float(results["rwa_final"].sum()) == pytest.approx(7_000_000.0)

    def test_el_not_zeroed(self, results: pl.DataFrame) -> None:
        """Non-beneficial: the covered part is NOT substituted, so its
        slotting EL stands (0.4% x 10M)."""
        assert float(results["expected_loss"].sum()) == pytest.approx(40_000.0)
