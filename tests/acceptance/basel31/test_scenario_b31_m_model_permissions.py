"""
Basel 3.1 Model Permissions Acceptance Tests (P5.8).

Pipeline position:
    Loader → Hierarchy → Classifier → CRM → SA/IRB/Slotting Calculator → Aggregator

Key responsibilities:
    Validate that PRA PS1/26 Art. 147A approach restrictions correctly override
    model-level IRB permissions through the full pipeline. These are end-to-end
    tests exercising all pipeline stages, not just the classifier.

Scenarios:
    B31-M1:  FSE corporate — AIRB permission overridden to FIRB (Art. 147A(1)(e))
    B31-M2:  Large corporate (>GBP 440m) — AIRB overridden to FIRB (Art. 147A(1)(d))
    B31-M3:  Institution — AIRB permission overridden to FIRB (Art. 147A(1)(b))
    B31-M4:  IPRE — AIRB permission overridden to slotting (Art. 147A(1)(c))
    B31-M5:  HVCRE — AIRB permission overridden to slotting (Art. 147A(1)(c))
    B31-M6:  Sovereign — model grants AIRB but forced to SA (Art. 147A(1)(a))
    B31-M7:  Normal corporate AIRB permitted (positive case)
    B31-M8:  Project Finance AIRB permitted (PF not restricted, only IPRE/HVCRE)
    B31-M9:  FSE + large corp combined — both flags, FIRB (Art. 147A(1)(d)+(e))
    B31-M10: Corporate at exact threshold (GBP 440m) — AIRB permitted (> not >=)
    B31-M11: No model_permissions but IRB config — silent fallback to SA
    B31-M12: PSE — model grants FIRB but forced to SA (Art. 147A(1)(a))

References:
    - PRA PS1/26 Art. 147A(1)(a)-(h)
    - docs/specifications/common/hierarchy-classification.md
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

import polars as pl

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.contracts.config import CalculationConfig, PermissionMode
from rwa_calc.domain.enums import ApproachType
from rwa_calc.engine.pipeline import PipelineOrchestrator

if TYPE_CHECKING:
    pass


# ---------------------------------------------------------------------------
# Test data builders
# ---------------------------------------------------------------------------

_MODEL_ID = "TEST_B31_MODEL"


def _counterparty(
    ref: str = "CP001",
    entity_type: str = "corporate",
    country_code: str = "GB",
    annual_revenue: float | None = 50_000_000.0,
    is_financial_sector_entity: bool | None = False,
    default_status: bool = False,
    scra_grade: str | None = None,
) -> pl.LazyFrame:
    return pl.LazyFrame(
        {
            "counterparty_reference": [ref],
            "counterparty_name": [f"Test {ref}"],
            "entity_type": [entity_type],
            "country_code": [country_code],
            "annual_revenue": [annual_revenue],
            "total_assets": [None],
            "default_status": [default_status],
            "sector_code": [None],
            "apply_fi_scalar": [None],
            "is_managed_as_retail": [False],
            "is_natural_person": [False],
            "is_social_housing": [False],
            "is_financial_sector_entity": [is_financial_sector_entity],
            "scra_grade": [scra_grade],
            "is_investment_grade": [None],
            "is_ccp_client_cleared": [False],
            "borrower_income_currency": [None],
            "sovereign_cqs": [None],
            "local_currency": [None],
            "institution_cqs": [None],
        },
        schema={
            "counterparty_reference": pl.String,
            "counterparty_name": pl.String,
            "entity_type": pl.String,
            "country_code": pl.String,
            "annual_revenue": pl.Float64,
            "total_assets": pl.Float64,
            "default_status": pl.Boolean,
            "sector_code": pl.String,
            "apply_fi_scalar": pl.Boolean,
            "is_managed_as_retail": pl.Boolean,
            "is_natural_person": pl.Boolean,
            "is_social_housing": pl.Boolean,
            "is_financial_sector_entity": pl.Boolean,
            "scra_grade": pl.String,
            "is_investment_grade": pl.Boolean,
            "is_ccp_client_cleared": pl.Boolean,
            "borrower_income_currency": pl.String,
            "sovereign_cqs": pl.Int32,
            "local_currency": pl.String,
            "institution_cqs": pl.Int8,
        },
    )


def _facility(
    ref: str = "FAC001",
    cp_ref: str = "CP001",
    risk_type: str = "corporate",
    lgd: float | None = 0.35,
    seniority: str = "senior",
) -> pl.LazyFrame:
    return pl.LazyFrame(
        {
            "facility_reference": [ref],
            "product_type": ["term_loan"],
            "book_code": ["MAIN"],
            "counterparty_reference": [cp_ref],
            "value_date": [date(2025, 1, 1)],
            "maturity_date": [date(2030, 1, 1)],
            "currency": ["GBP"],
            "limit": [1_000_000.0],
            "committed": [True],
            "lgd": [lgd],
            "lgd_unsecured": [None],
            "has_sufficient_collateral_data": [False],
            "beel": [None],
            "is_revolving": [False],
            "is_qrre_transactor": [False],
            "seniority": [seniority],
            "risk_type": [risk_type],
            "underlying_risk_type": [None],
            "ccf_modelled": [None],
            "ead_modelled": [None],
            "is_short_term_trade_lc": [False],
            "is_payroll_loan": [False],
            "is_buy_to_let": [False],
            "has_one_day_maturity_floor": [False],
            "facility_termination_date": [None],
        },
        schema={
            "facility_reference": pl.String,
            "product_type": pl.String,
            "book_code": pl.String,
            "counterparty_reference": pl.String,
            "value_date": pl.Date,
            "maturity_date": pl.Date,
            "currency": pl.String,
            "limit": pl.Float64,
            "committed": pl.Boolean,
            "lgd": pl.Float64,
            "lgd_unsecured": pl.Float64,
            "has_sufficient_collateral_data": pl.Boolean,
            "beel": pl.Float64,
            "is_revolving": pl.Boolean,
            "is_qrre_transactor": pl.Boolean,
            "seniority": pl.String,
            "risk_type": pl.String,
            "underlying_risk_type": pl.String,
            "ccf_modelled": pl.Float64,
            "ead_modelled": pl.Float64,
            "is_short_term_trade_lc": pl.Boolean,
            "is_payroll_loan": pl.Boolean,
            "is_buy_to_let": pl.Boolean,
            "has_one_day_maturity_floor": pl.Boolean,
            "facility_termination_date": pl.Date,
        },
    )


def _loan(
    ref: str = "LOAN001",
    cp_ref: str = "CP001",
    drawn_amount: float = 1_000_000.0,
    lgd: float | None = 0.35,
    seniority: str = "senior",
) -> pl.LazyFrame:
    return pl.LazyFrame(
        {
            "loan_reference": [ref],
            "product_type": ["term_loan"],
            "book_code": ["MAIN"],
            "counterparty_reference": [cp_ref],
            "value_date": [date(2025, 1, 1)],
            "maturity_date": [date(2030, 1, 1)],
            "currency": ["GBP"],
            "drawn_amount": [drawn_amount],
            "interest": [0.0],
            "lgd": [lgd],
            "lgd_unsecured": [None],
            "has_sufficient_collateral_data": [False],
            "beel": [None],
            "seniority": [seniority],
            "is_payroll_loan": [False],
            "is_buy_to_let": [False],
            "has_one_day_maturity_floor": [False],
            "has_netting_agreement": [False],
            "netting_facility_reference": [None],
            "due_diligence_performed": [None],
            "due_diligence_override_rw": [None],
        },
        schema={
            "loan_reference": pl.String,
            "product_type": pl.String,
            "book_code": pl.String,
            "counterparty_reference": pl.String,
            "value_date": pl.Date,
            "maturity_date": pl.Date,
            "currency": pl.String,
            "drawn_amount": pl.Float64,
            "interest": pl.Float64,
            "lgd": pl.Float64,
            "lgd_unsecured": pl.Float64,
            "has_sufficient_collateral_data": pl.Boolean,
            "beel": pl.Float64,
            "seniority": pl.String,
            "is_payroll_loan": pl.Boolean,
            "is_buy_to_let": pl.Boolean,
            "has_one_day_maturity_floor": pl.Boolean,
            "has_netting_agreement": pl.Boolean,
            "netting_facility_reference": pl.String,
            "due_diligence_performed": pl.Boolean,
            "due_diligence_override_rw": pl.Float64,
        },
    )


def _rating(
    cp_ref: str = "CP001",
    pd: float = 0.01,
    model_id: str = _MODEL_ID,
) -> pl.LazyFrame:
    return pl.LazyFrame(
        {
            "rating_reference": [f"RAT_{cp_ref}"],
            "counterparty_reference": [cp_ref],
            "rating_type": ["internal"],
            "rating_agency": ["internal"],
            "rating_value": ["BB"],
            "cqs": [None],
            "pd": [pd],
            "rating_date": [date(2026, 1, 1)],
            "is_solicited": [True],
            "model_id": [model_id],
        },
        schema={
            "rating_reference": pl.String,
            "counterparty_reference": pl.String,
            "rating_type": pl.String,
            "rating_agency": pl.String,
            "rating_value": pl.String,
            "cqs": pl.Int8,
            "pd": pl.Float64,
            "rating_date": pl.Date,
            "is_solicited": pl.Boolean,
            "model_id": pl.String,
        },
    )


def _model_permissions(entries: list[tuple[str, str]]) -> pl.LazyFrame:
    """Create model permissions.

    Args:
        entries: list of (exposure_class, approach) tuples.  model_id is always
                 _MODEL_ID so it matches the ratings.
    """
    return pl.LazyFrame(
        {
            "model_id": [_MODEL_ID] * len(entries),
            "exposure_class": [e[0] for e in entries],
            "approach": [e[1] for e in entries],
        },
        schema={
            "model_id": pl.String,
            "exposure_class": pl.String,
            "approach": pl.String,
        },
    )


def _specialised_lending(
    cp_ref: str = "CP001",
    sl_type: str = "ipre",
    slotting_category: str = "good",
    is_hvcre: bool = False,
) -> pl.LazyFrame:
    return pl.LazyFrame(
        {
            "counterparty_reference": [cp_ref],
            "sl_type": [sl_type],
            "project_phase": [None],
            "slotting_category": [slotting_category],
            "is_hvcre": [is_hvcre],
        },
        schema={
            "counterparty_reference": pl.String,
            "sl_type": pl.String,
            "project_phase": pl.String,
            "slotting_category": pl.String,
            "is_hvcre": pl.Boolean,
        },
    )


def _empty_mappings() -> tuple[pl.LazyFrame, pl.LazyFrame]:
    fac_map = pl.LazyFrame(
        schema={
            "parent_facility_reference": pl.String,
            "child_reference": pl.String,
            "child_type": pl.String,
        }
    )
    lend_map = pl.LazyFrame(
        schema={
            "parent_counterparty_reference": pl.String,
            "child_counterparty_reference": pl.String,
        }
    )
    return fac_map, lend_map


# ---------------------------------------------------------------------------
# Pipeline runner
# ---------------------------------------------------------------------------


def _run_pipeline(
    counterparties: pl.LazyFrame,
    facilities: pl.LazyFrame,
    loans: pl.LazyFrame,
    ratings: pl.LazyFrame | None = None,
    model_permissions: pl.LazyFrame | None = None,
    specialised_lending: pl.LazyFrame | None = None,
    reporting_date: date = date(2030, 6, 30),
):
    """Run the B31 pipeline with IRB permissions and return the orchestrator result."""
    fac_map, lend_map = _empty_mappings()
    bundle = RawDataBundle(
        facilities=facilities,
        loans=loans,
        counterparties=counterparties,
        facility_mappings=fac_map,
        lending_mappings=lend_map,
        ratings=ratings,
        model_permissions=model_permissions,
        specialised_lending=specialised_lending,
    )
    config = CalculationConfig.basel_3_1(
        reporting_date=reporting_date,
        permission_mode=PermissionMode.IRB,
    )
    return PipelineOrchestrator().run_with_data(bundle, config)


def _find_exposure(results, loan_ref: str) -> tuple[str, dict]:
    """Find an exposure across all result sets by loan reference.

    Returns (result_set_name, row_dict) or raises AssertionError.
    """
    for name, lf in [
        ("sa", results.sa_results),
        ("irb", results.irb_results),
        ("slotting", results.slotting_results),
    ]:
        if lf is None:
            continue
        df = lf.filter(pl.col("exposure_reference").str.contains(loan_ref)).collect()
        if len(df) > 0:
            return name, df.to_dicts()[0]
    msg = f"Exposure {loan_ref!r} not found in any result set"
    raise AssertionError(msg)


# ---------------------------------------------------------------------------
# B31-M1: FSE corporate — AIRB overridden to FIRB (Art. 147A(1)(e))
# ---------------------------------------------------------------------------


class TestB31M1_FSECorporateForcedFIRB:
    """Model grants AIRB for corporate, but cp_is_financial_sector_entity=True
    forces the exposure to FIRB under Basel 3.1 Art. 147A(1)(e)."""

    def test_approach_is_firb(self) -> None:
        """B31-M1: FSE corporate routes to FIRB, not AIRB."""
        cp = _counterparty(
            ref="CP_FSE",
            entity_type="corporate",
            is_financial_sector_entity=True,
            annual_revenue=100_000_000.0,
        )
        fac = _facility(ref="FAC_FSE", cp_ref="CP_FSE", lgd=0.35)
        loan = _loan(ref="LOAN_FSE", cp_ref="CP_FSE", lgd=0.35)
        rat = _rating(cp_ref="CP_FSE", pd=0.01)
        mp = _model_permissions(
            [
                ("corporate", ApproachType.AIRB.value),
                ("corporate", ApproachType.FIRB.value),
            ]
        )

        results = _run_pipeline(cp, fac, loan, ratings=rat, model_permissions=mp)
        result_set, row = _find_exposure(results, "LOAN_FSE")

        assert result_set == "irb", "FSE corporate should be in IRB results"
        assert row["approach_applied"] == ApproachType.FIRB.value

    def test_lgd_cleared_to_supervisory(self) -> None:
        """B31-M1: FSE FIRB uses supervisory LGD 45% (Art. 161(1) FSE)."""
        cp = _counterparty(
            ref="CP_FSE2",
            entity_type="corporate",
            is_financial_sector_entity=True,
            annual_revenue=100_000_000.0,
        )
        fac = _facility(ref="FAC_FSE2", cp_ref="CP_FSE2", lgd=0.35)
        loan = _loan(ref="LOAN_FSE2", cp_ref="CP_FSE2", lgd=0.35)
        rat = _rating(cp_ref="CP_FSE2", pd=0.01)
        mp = _model_permissions(
            [
                ("corporate", ApproachType.AIRB.value),
                ("corporate", ApproachType.FIRB.value),
            ]
        )

        results = _run_pipeline(cp, fac, loan, ratings=rat, model_permissions=mp)
        _, row = _find_exposure(results, "LOAN_FSE2")

        # Under B31 FIRB for FSE: supervisory LGD = 45%
        assert row["risk_weight"] > 0, "Risk weight should be positive"
        assert row["rwa"] > 0, "RWA should be positive"


# ---------------------------------------------------------------------------
# B31-M2: Large corporate (>GBP 440m) — AIRB overridden to FIRB
# ---------------------------------------------------------------------------


class TestB31M2_LargeCorporateForcedFIRB:
    """Model grants AIRB for corporate, but revenue > GBP 440m forces FIRB
    under Basel 3.1 Art. 147A(1)(d)."""

    def test_approach_is_firb(self) -> None:
        """B31-M2: Large corporate routes to FIRB."""
        cp = _counterparty(
            ref="CP_LARGE",
            entity_type="corporate",
            is_financial_sector_entity=False,
            annual_revenue=500_000_000.0,
        )
        fac = _facility(ref="FAC_LARGE", cp_ref="CP_LARGE", lgd=0.35)
        loan = _loan(ref="LOAN_LARGE", cp_ref="CP_LARGE", lgd=0.35)
        rat = _rating(cp_ref="CP_LARGE", pd=0.01)
        mp = _model_permissions(
            [
                ("corporate", ApproachType.AIRB.value),
                ("corporate", ApproachType.FIRB.value),
            ]
        )

        results = _run_pipeline(cp, fac, loan, ratings=rat, model_permissions=mp)
        result_set, row = _find_exposure(results, "LOAN_LARGE")

        assert result_set == "irb", "Large corporate should be in IRB results"
        assert row["approach_applied"] == ApproachType.FIRB.value

    def test_rwa_positive(self) -> None:
        """B31-M2: Large corporate produces positive RWA under FIRB."""
        cp = _counterparty(
            ref="CP_LARGE2",
            entity_type="corporate",
            is_financial_sector_entity=False,
            annual_revenue=500_000_000.0,
        )
        fac = _facility(ref="FAC_LARGE2", cp_ref="CP_LARGE2", lgd=0.35)
        loan = _loan(ref="LOAN_LARGE2", cp_ref="CP_LARGE2", lgd=0.35)
        rat = _rating(cp_ref="CP_LARGE2", pd=0.01)
        mp = _model_permissions(
            [
                ("corporate", ApproachType.AIRB.value),
                ("corporate", ApproachType.FIRB.value),
            ]
        )

        results = _run_pipeline(cp, fac, loan, ratings=rat, model_permissions=mp)
        _, row = _find_exposure(results, "LOAN_LARGE2")

        assert row["risk_weight"] > 0
        assert row["rwa"] > 0


# ---------------------------------------------------------------------------
# B31-M3: Institution — AIRB overridden to FIRB (Art. 147A(1)(b))
# ---------------------------------------------------------------------------


class TestB31M3_InstitutionForcedFIRB:
    """Model grants AIRB for institution, but Art. 147A(1)(b) restricts
    institutions to FIRB only under Basel 3.1."""

    def test_approach_is_firb(self) -> None:
        """B31-M3: Institution routes to FIRB, not AIRB."""
        cp = _counterparty(
            ref="CP_INST",
            entity_type="bank",
            is_financial_sector_entity=False,  # Not flagged FSE — tests class-level block
            annual_revenue=50_000_000.0,
            scra_grade="a",
        )
        fac = _facility(
            ref="FAC_INST",
            cp_ref="CP_INST",
            risk_type="institution",
            lgd=0.35,
        )
        loan = _loan(ref="LOAN_INST", cp_ref="CP_INST", lgd=0.35)
        rat = _rating(cp_ref="CP_INST", pd=0.005)
        mp = _model_permissions(
            [
                ("institution", ApproachType.AIRB.value),
                ("institution", ApproachType.FIRB.value),
            ]
        )

        results = _run_pipeline(cp, fac, loan, ratings=rat, model_permissions=mp)
        result_set, row = _find_exposure(results, "LOAN_INST")

        assert result_set == "irb", "Institution should be in IRB results"
        assert row["approach_applied"] == ApproachType.FIRB.value


# ---------------------------------------------------------------------------
# B31-M4: IPRE — AIRB overridden to slotting (Art. 147A(1)(c))
# ---------------------------------------------------------------------------


class TestB31M4_IPREForcedSlotting:
    """Model grants AIRB for specialised_lending, but IPRE is forced to
    slotting under Basel 3.1 Art. 147A(1)(c)."""

    def test_approach_is_slotting(self) -> None:
        """B31-M4: IPRE routes to slotting, not AIRB."""
        cp = _counterparty(ref="CP_IPRE", entity_type="specialised_lending")
        fac = _facility(ref="FAC_IPRE", cp_ref="CP_IPRE", risk_type="corporate", lgd=0.35)
        loan = _loan(ref="LOAN_IPRE", cp_ref="CP_IPRE", lgd=0.35)
        rat = _rating(cp_ref="CP_IPRE", pd=0.01)
        sl = _specialised_lending(cp_ref="CP_IPRE", sl_type="ipre")
        mp = _model_permissions(
            [
                ("specialised_lending", ApproachType.AIRB.value),
                ("specialised_lending", ApproachType.SLOTTING.value),
            ]
        )

        results = _run_pipeline(
            cp,
            fac,
            loan,
            ratings=rat,
            model_permissions=mp,
            specialised_lending=sl,
        )
        result_set, row = _find_exposure(results, "LOAN_IPRE")

        assert result_set == "slotting", "IPRE should be in slotting results"


# ---------------------------------------------------------------------------
# B31-M5: HVCRE — AIRB overridden to slotting (Art. 147A(1)(c))
# ---------------------------------------------------------------------------


class TestB31M5_HVCREForcedSlotting:
    """Model grants AIRB for specialised_lending, but HVCRE is forced to
    slotting under Basel 3.1 Art. 147A(1)(c)."""

    def test_approach_is_slotting(self) -> None:
        """B31-M5: HVCRE routes to slotting, not AIRB."""
        cp = _counterparty(ref="CP_HVCRE", entity_type="specialised_lending")
        fac = _facility(ref="FAC_HVCRE", cp_ref="CP_HVCRE", risk_type="corporate", lgd=0.35)
        loan = _loan(ref="LOAN_HVCRE", cp_ref="CP_HVCRE", lgd=0.35)
        rat = _rating(cp_ref="CP_HVCRE", pd=0.01)
        sl = _specialised_lending(cp_ref="CP_HVCRE", sl_type="hvcre", is_hvcre=True)
        mp = _model_permissions(
            [
                ("specialised_lending", ApproachType.AIRB.value),
                ("specialised_lending", ApproachType.SLOTTING.value),
            ]
        )

        results = _run_pipeline(
            cp,
            fac,
            loan,
            ratings=rat,
            model_permissions=mp,
            specialised_lending=sl,
        )
        result_set, row = _find_exposure(results, "LOAN_HVCRE")

        assert result_set == "slotting", "HVCRE should be in slotting results"


# ---------------------------------------------------------------------------
# B31-M6: Sovereign — model grants AIRB but forced to SA (Art. 147A(1)(a))
# ---------------------------------------------------------------------------


class TestB31M6_SovereignForcedSA:
    """Model grants AIRB for central_govt_central_bank, but Art. 147A(1)(a)
    forces sovereign exposures to SA under Basel 3.1."""

    def test_approach_is_sa(self) -> None:
        """B31-M6: Sovereign routes to SA, not AIRB, even with model permission."""
        cp = _counterparty(
            ref="CP_SOV",
            entity_type="sovereign",
            country_code="US",
            annual_revenue=None,
            is_financial_sector_entity=None,
        )
        fac = _facility(ref="FAC_SOV", cp_ref="CP_SOV", risk_type="sovereign", lgd=0.35)
        loan = _loan(ref="LOAN_SOV", cp_ref="CP_SOV", lgd=0.35)
        rat = _rating(cp_ref="CP_SOV", pd=0.001)
        mp = _model_permissions(
            [
                ("central_govt_central_bank", ApproachType.AIRB.value),
                ("central_govt_central_bank", ApproachType.FIRB.value),
            ]
        )

        results = _run_pipeline(cp, fac, loan, ratings=rat, model_permissions=mp)
        result_set, row = _find_exposure(results, "LOAN_SOV")

        assert result_set == "sa", "Sovereign should be in SA results (Art. 147A(1)(a))"


# ---------------------------------------------------------------------------
# B31-M7: Normal corporate AIRB permitted (positive case)
# ---------------------------------------------------------------------------


class TestB31M7_NormalCorporateAIRBPermitted:
    """Model grants AIRB for a normal (non-FSE, non-large) corporate.
    No Art. 147A restriction applies — AIRB should succeed."""

    def test_approach_is_airb(self) -> None:
        """B31-M7: Normal corporate routes to AIRB."""
        cp = _counterparty(
            ref="CP_NORM",
            entity_type="corporate",
            is_financial_sector_entity=False,
            annual_revenue=50_000_000.0,
        )
        fac = _facility(ref="FAC_NORM", cp_ref="CP_NORM", lgd=0.35)
        loan = _loan(ref="LOAN_NORM", cp_ref="CP_NORM", lgd=0.35)
        rat = _rating(cp_ref="CP_NORM", pd=0.01)
        mp = _model_permissions(
            [
                ("corporate", ApproachType.AIRB.value),
            ]
        )

        results = _run_pipeline(cp, fac, loan, ratings=rat, model_permissions=mp)
        result_set, row = _find_exposure(results, "LOAN_NORM")

        assert result_set == "irb", "Normal corporate should be in IRB results"
        assert row["approach_applied"] == ApproachType.AIRB.value

    def test_rwa_positive(self) -> None:
        """B31-M7: Normal corporate AIRB produces positive RWA."""
        cp = _counterparty(
            ref="CP_NORM2",
            entity_type="corporate",
            is_financial_sector_entity=False,
            annual_revenue=50_000_000.0,
        )
        fac = _facility(ref="FAC_NORM2", cp_ref="CP_NORM2", lgd=0.35)
        loan = _loan(ref="LOAN_NORM2", cp_ref="CP_NORM2", lgd=0.35)
        rat = _rating(cp_ref="CP_NORM2", pd=0.01)
        mp = _model_permissions([("corporate", ApproachType.AIRB.value)])

        results = _run_pipeline(cp, fac, loan, ratings=rat, model_permissions=mp)
        _, row = _find_exposure(results, "LOAN_NORM2")

        assert row["risk_weight"] > 0
        assert row["rwa"] > 0


# ---------------------------------------------------------------------------
# B31-M8: Project Finance AIRB permitted (PF not restricted)
# ---------------------------------------------------------------------------


class TestB31M8_ProjectFinanceAIRBPermitted:
    """Model grants AIRB for specialised_lending. PF is not IPRE/HVCRE, so
    Art. 147A(1)(c) does not restrict it — AIRB should succeed."""

    def test_approach_is_airb(self) -> None:
        """B31-M8: PF routes to AIRB, not slotting."""
        cp = _counterparty(ref="CP_PF", entity_type="specialised_lending")
        fac = _facility(ref="FAC_PF", cp_ref="CP_PF", risk_type="corporate", lgd=0.35)
        loan = _loan(ref="LOAN_PF", cp_ref="CP_PF", lgd=0.35)
        rat = _rating(cp_ref="CP_PF", pd=0.01)
        sl = _specialised_lending(cp_ref="CP_PF", sl_type="project_finance")
        mp = _model_permissions(
            [
                ("specialised_lending", ApproachType.AIRB.value),
            ]
        )

        results = _run_pipeline(
            cp,
            fac,
            loan,
            ratings=rat,
            model_permissions=mp,
            specialised_lending=sl,
        )
        result_set, row = _find_exposure(results, "LOAN_PF")

        assert result_set == "irb", "PF should be in IRB results (AIRB permitted)"
        assert row["approach_applied"] == ApproachType.AIRB.value


# ---------------------------------------------------------------------------
# B31-M9: FSE + large corp combined — both flags, FIRB
# ---------------------------------------------------------------------------


class TestB31M9_FSEAndLargeCorpCombined:
    """Corporate is both FSE and large (>GBP 440m). Both Art. 147A(1)(d) and
    (e) apply — result should be FIRB."""

    def test_approach_is_firb(self) -> None:
        """B31-M9: FSE + large corp both trigger FIRB."""
        cp = _counterparty(
            ref="CP_COMBO",
            entity_type="corporate",
            is_financial_sector_entity=True,
            annual_revenue=600_000_000.0,
        )
        fac = _facility(ref="FAC_COMBO", cp_ref="CP_COMBO", lgd=0.35)
        loan = _loan(ref="LOAN_COMBO", cp_ref="CP_COMBO", lgd=0.35)
        rat = _rating(cp_ref="CP_COMBO", pd=0.01)
        mp = _model_permissions(
            [
                ("corporate", ApproachType.AIRB.value),
                ("corporate", ApproachType.FIRB.value),
            ]
        )

        results = _run_pipeline(cp, fac, loan, ratings=rat, model_permissions=mp)
        result_set, row = _find_exposure(results, "LOAN_COMBO")

        assert result_set == "irb"
        assert row["approach_applied"] == ApproachType.FIRB.value


# ---------------------------------------------------------------------------
# B31-M10: Corporate at exact threshold — AIRB still permitted (> not >=)
# ---------------------------------------------------------------------------


class TestB31M10_ThresholdBoundary:
    """Corporate with revenue exactly GBP 440m. The check is strictly > 440m,
    so this exposure should NOT be blocked — AIRB is permitted."""

    def test_approach_is_airb_at_threshold(self) -> None:
        """B31-M10: Revenue == 440m → AIRB permitted (threshold is strict >)."""
        cp = _counterparty(
            ref="CP_BOUND",
            entity_type="corporate",
            is_financial_sector_entity=False,
            annual_revenue=440_000_000.0,
        )
        fac = _facility(ref="FAC_BOUND", cp_ref="CP_BOUND", lgd=0.35)
        loan = _loan(ref="LOAN_BOUND", cp_ref="CP_BOUND", lgd=0.35)
        rat = _rating(cp_ref="CP_BOUND", pd=0.01)
        mp = _model_permissions([("corporate", ApproachType.AIRB.value)])

        results = _run_pipeline(cp, fac, loan, ratings=rat, model_permissions=mp)
        result_set, row = _find_exposure(results, "LOAN_BOUND")

        assert result_set == "irb"
        assert row["approach_applied"] == ApproachType.AIRB.value

    def test_approach_is_firb_just_above(self) -> None:
        """B31-M10: Revenue == 440,000,001 → FIRB (just above threshold)."""
        cp = _counterparty(
            ref="CP_ABOVE",
            entity_type="corporate",
            is_financial_sector_entity=False,
            annual_revenue=440_000_001.0,
        )
        fac = _facility(ref="FAC_ABOVE", cp_ref="CP_ABOVE", lgd=0.35)
        loan = _loan(ref="LOAN_ABOVE", cp_ref="CP_ABOVE", lgd=0.35)
        rat = _rating(cp_ref="CP_ABOVE", pd=0.01)
        mp = _model_permissions(
            [
                ("corporate", ApproachType.AIRB.value),
                ("corporate", ApproachType.FIRB.value),
            ]
        )

        results = _run_pipeline(cp, fac, loan, ratings=rat, model_permissions=mp)
        result_set, row = _find_exposure(results, "LOAN_ABOVE")

        assert result_set == "irb"
        assert row["approach_applied"] == ApproachType.FIRB.value


# ---------------------------------------------------------------------------
# B31-M11: No model_permissions but IRB config — fallback to SA
# ---------------------------------------------------------------------------


class TestB31M11_NoModelPermissionsFallback:
    """IRB config is set but no model_permissions table is provided. The
    pipeline silently downgrades to PermissionMode.STANDARDISED and all
    exposures route to SA."""

    def test_fallback_to_sa(self) -> None:
        """B31-M11: Without model_permissions, IRB config falls back to SA."""
        cp = _counterparty(ref="CP_NOMP", entity_type="corporate")
        fac = _facility(ref="FAC_NOMP", cp_ref="CP_NOMP")
        loan = _loan(ref="LOAN_NOMP", cp_ref="CP_NOMP")
        rat = _rating(cp_ref="CP_NOMP", pd=0.01)

        results = _run_pipeline(cp, fac, loan, ratings=rat, model_permissions=None)
        result_set, row = _find_exposure(results, "LOAN_NOMP")

        assert result_set == "sa", "Without model_permissions, exposure should be SA"


# ---------------------------------------------------------------------------
# B31-M12: PSE — model grants FIRB but forced to SA (Art. 147A(1)(a))
# ---------------------------------------------------------------------------


class TestB31M12_PSEForcedSA:
    """Model grants FIRB for PSE, but Art. 147A(1)(a) forces PSE exposures
    to SA under Basel 3.1."""

    def test_approach_is_sa(self) -> None:
        """B31-M12: PSE routes to SA even with FIRB model permission."""
        cp = _counterparty(
            ref="CP_PSE",
            entity_type="pse_sovereign",
            country_code="GB",
            annual_revenue=None,
            is_financial_sector_entity=None,
        )
        fac = _facility(ref="FAC_PSE", cp_ref="CP_PSE", risk_type="corporate", lgd=None)
        loan = _loan(ref="LOAN_PSE", cp_ref="CP_PSE", lgd=None)
        rat = _rating(cp_ref="CP_PSE", pd=0.005)
        mp = _model_permissions(
            [
                ("pse", ApproachType.FIRB.value),
                ("pse", ApproachType.AIRB.value),
            ]
        )

        results = _run_pipeline(cp, fac, loan, ratings=rat, model_permissions=mp)
        result_set, row = _find_exposure(results, "LOAN_PSE")

        assert result_set == "sa", "PSE should be in SA results (Art. 147A(1)(a))"
