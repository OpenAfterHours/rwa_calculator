"""
Integration tests: extensive carriers are CONSERVED across real-estate split legs.

The RE loan-splitter (``engine/stages/re_split/splitter.py``) emits two or three
physical rows per flagged parent. It runs AFTER ``crm_processor``
(``engine/registry.py``), so every per-exposure money carrier the CRM stage
wrote is already on the parent row when the split happens. Any extensive
(money) carrier the splitter does not explicitly allocate is therefore
inherited WHOLE by every leg and double-counts in every downstream sum.

That reaches regulatory returns: COREP C 07.00 col 0010 ("original exposure
pre conversion factors") and Pillar 3 CR4 cols a/b are built from
``reporting_gross_on_bs`` / ``reporting_gross_off_bs``, which the aggregator
derives (``engine/aggregator/aggregator.py::_add_reporting_projection``) from
``drawn_amount`` / ``interest`` / ``nominal_amount`` / ``undrawn_amount`` — all
inherited. A firm would file a gross exposure of 2x its actual book.

Every assertion here is anchored to a SOURCE constant declared in this module
(the amounts fed into the bundle), never to current engine output.

Two-leg design (LESSONS B5): the portfolio carries BOTH an exposure that
splits (whose cells MOVE when the defect is fixed) and one that cannot split
(whose cells must SURVIVE unchanged). A test with only the moving leg cannot
distinguish "the fix worked" from "the fix zeroed the cell".

References:
- CRR Art. 125 / Art. 124(1): RRE 35% up to 80% LTV; residual at counterparty RW.
- PRA PS1/26 Art. 124F: B3.1 RRE loan-splitting (cap 55% of property value).
- PS1/26 Art. 124L: counterparty-type residual RW.
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from rwa_calc.reporting.corep.generator import COREPGenerator
from rwa_calc.reporting.pillar3.generator import Pillar3Generator
from tests.fixtures.raw_bundle import make_raw_bundle

_REPORTING_DATE = date(2026, 12, 31)
_VALUE_DATE = date(2024, 1, 1)
_MATURITY_DATE = date(2029, 12, 31)

# --------------------------------------------------------------------------
# SOURCE constants — the amounts fed into the bundle. Every assertion below
# is anchored to these, so the test cannot drift with engine output.
# --------------------------------------------------------------------------

#: Splitting exposure: corporate term loan secured on a residential property.
SPLIT_LOAN_DRAWN = 1_000_000.0
SPLIT_LOAN_INTEREST = 25_000.0
SPLIT_PLEDGE_VALUE = 1_000_000.0

#: Control exposure: no property collateral, so the splitter cannot touch it.
CONTROL_LOAN_DRAWN = 400_000.0
CONTROL_LOAN_INTEREST = 0.0

#: Total on-balance-sheet gross exposure the portfolio actually carries.
TOTAL_ON_BS_GROSS = (
    SPLIT_LOAN_DRAWN + SPLIT_LOAN_INTEREST + CONTROL_LOAN_DRAWN + CONTROL_LOAN_INTEREST
)

#: Total pledged real-estate market value the portfolio actually carries.
TOTAL_RE_PLEDGE_VALUE = SPLIT_PLEDGE_VALUE

#: The value a defect-free engine must NOT report: the splitting loan counted
#: twice. Pinned so a regression that reintroduces the duplication is named.
DUPLICATED_ON_BS_GROSS = TOTAL_ON_BS_GROSS + SPLIT_LOAN_DRAWN + SPLIT_LOAN_INTEREST

#: Extensive carriers that must sum, over a parent's legs, to the parent's
#: pre-split value. Anchored to SPLIT_LOAN_* above.
_CONSERVED_ON_BS: dict[str, float] = {
    "drawn_amount": SPLIT_LOAN_DRAWN,
    "interest": SPLIT_LOAN_INTEREST,
    "reporting_gross_drawn": SPLIT_LOAN_DRAWN,
    "reporting_gross_interest": SPLIT_LOAN_INTEREST,
    "reporting_gross_on_bs": SPLIT_LOAN_DRAWN + SPLIT_LOAN_INTEREST,
    "ead_final": SPLIT_LOAN_DRAWN + SPLIT_LOAN_INTEREST,
}

#: Real-estate collateral carriers: the property secures the SECURED portion
#: only (CRR Art. 124(1) para 3 puts the residual at the counterparty RW
#: precisely because it is the uncollateralised remainder), so these must sum
#: to exactly one pledge across the legs.
_CONSERVED_RE_COLLATERAL: tuple[str, ...] = (
    "collateral_re_market_value",
    "residential_collateral_value",
)


def _counterparties() -> pl.LazyFrame:
    """Two unrated corporates, both far above any SME threshold.

    Revenue 200m keeps both out of the Art. 501 SME supporting-factor
    population, so the supporting factor is 1.0 on every leg and cannot
    confound the carrier assertions.
    """
    return pl.LazyFrame(
        {
            "counterparty_reference": ["CP_SPLIT", "CP_CTRL"],
            "counterparty_name": ["Split Corp", "Control Corp"],
            "entity_type": ["corporate", "corporate"],
            "country_code": ["GB", "GB"],
            "annual_revenue": [200_000_000.0, 200_000_000.0],
            "total_assets": [None, None],
            "default_status": [False, False],
            "sector_code": [None, None],
            "apply_fi_scalar": [None, None],
            "is_managed_as_retail": [False, False],
            "is_natural_person": [False, False],
            "is_social_housing": [False, False],
            "is_financial_sector_entity": [False, False],
            "scra_grade": [None, None],
            "is_investment_grade": [None, None],
            "is_ccp_client_cleared": [False, False],
            "borrower_income_currency": [None, None],
            "sovereign_cqs": [None, None],
            "local_currency": [None, None],
            "institution_cqs": [None, None],
        }
    )


def _loans() -> pl.LazyFrame:
    """The splitting loan plus the never-splitting control loan."""
    return pl.LazyFrame(
        {
            "loan_reference": ["LOAN_SPLIT", "LOAN_CTRL"],
            "product_type": ["term_loan", "term_loan"],
            "book_code": ["BANK", "BANK"],
            "counterparty_reference": ["CP_SPLIT", "CP_CTRL"],
            "value_date": [_VALUE_DATE, _VALUE_DATE],
            "maturity_date": [_MATURITY_DATE, _MATURITY_DATE],
            "currency": ["GBP", "GBP"],
            "drawn_amount": [SPLIT_LOAN_DRAWN, CONTROL_LOAN_DRAWN],
            "interest": [SPLIT_LOAN_INTEREST, CONTROL_LOAN_INTEREST],
            "lgd": [0.45, 0.45],
            "lgd_unsecured": [0.45, 0.45],
            "has_sufficient_collateral_data": [True, True],
            "beel": [None, None],
            "seniority": ["senior", "senior"],
            "is_payroll_loan": [False, False],
            "is_buy_to_let": [False, False],
            "has_one_day_maturity_floor": [False, False],
            "netting_agreement_reference": [None, None],
            "due_diligence_performed": [None, None],
            "due_diligence_override_rw": [None, None],
        }
    )


def _collateral() -> pl.LazyFrame:
    """One residential pledge, attached to the splitting loan only."""
    return pl.LazyFrame(
        {
            "collateral_reference": ["RRE_PLEDGE"],
            "collateral_type": ["real_estate"],
            "currency": ["GBP"],
            "maturity_date": [None],
            "market_value": [SPLIT_PLEDGE_VALUE],
            "nominal_value": [SPLIT_PLEDGE_VALUE],
            "pledge_percentage": [None],
            "beneficiary_type": ["loan"],
            "beneficiary_reference": ["LOAN_SPLIT"],
            "issuer_cqs": [None],
            "issuer_type": [None],
            "residual_maturity_years": [None],
            "original_maturity_years": [None],
            "is_eligible_financial_collateral": [False],
            "is_eligible_irb_collateral": [True],
            "is_main_index": [None],
            "valuation_date": [_REPORTING_DATE],
            "valuation_type": ["market"],
            "property_type": ["residential"],
            "property_ltv": [1.0],
            "is_income_producing": [False],
            "is_adc": [False],
            "is_presold": [False],
            "is_qualifying_re": [True],
            "prior_charge_ltv": [0.0],
            "liquidation_period_days": [None],
            "qualifies_for_zero_haircut": [False],
            "insurer_risk_weight": [None],
            "credit_event_reduction": [0.0],
            "rental_to_interest_ratio": [None],
        }
    )


def _build_bundle() -> RawDataBundle:
    """Portfolio: one RE-collateralised loan that splits + one that cannot."""
    return make_raw_bundle(
        counterparties=_counterparties(),
        loans=_loans(),
        collateral=_collateral(),
        facilities=pl.LazyFrame(
            schema={
                "facility_reference": pl.String,
                "product_type": pl.String,
                "book_code": pl.String,
                "counterparty_reference": pl.String,
                "currency": pl.String,
                "limit": pl.Float64,
                "committed": pl.Boolean,
            }
        ),
        facility_mappings=pl.LazyFrame(
            schema={
                "parent_facility_reference": pl.String,
                "child_reference": pl.String,
                "child_type": pl.String,
            }
        ),
        lending_mappings=pl.LazyFrame(
            schema={
                "parent_counterparty_reference": pl.String,
                "child_counterparty_reference": pl.String,
            }
        ),
    )


def _config(regime: str) -> CalculationConfig:
    kwargs = {
        "reporting_date": _REPORTING_DATE,
        "permission_mode": PermissionMode.STANDARDISED,
    }
    return (
        CalculationConfig.crr(**kwargs)
        if regime == "CRR"
        else CalculationConfig.basel_3_1(**kwargs)
    )


def _sum(frame: pl.DataFrame, column: str) -> float:
    """Non-null sum of a ledger column as a float."""
    value = frame.select(pl.col(column).cast(pl.Float64).sum()).item()
    return 0.0 if value is None else float(value)


def _total_row(cr4: pl.DataFrame) -> dict[str, object]:
    """The CR4 TOTAL row (row_ref 17)."""
    total = cr4.filter(pl.col("row_ref") == "17")
    assert total.height == 1, "CR4 must emit exactly one TOTAL row"
    return total.to_dicts()[0]


class _Run:
    """One pipeline run plus its COREP / Pillar 3 output."""

    def __init__(self, regime: str) -> None:
        result = PipelineOrchestrator().run_with_data(_build_bundle(), _config(regime))
        assert result.results is not None
        self.ledger = result.results.collect()
        framework = "CRR" if regime == "CRR" else "BASEL_3_1"
        self.pillar3 = Pillar3Generator().generate_from_lazyframe(
            result.results, framework=framework
        )
        self.corep = COREPGenerator().generate_from_lazyframe(result.results, framework=framework)

    def legs_of(self, parent: str) -> pl.DataFrame:
        return self.ledger.filter(pl.col("exposure_reference").str.starts_with(parent))


@pytest.fixture(scope="module")
def crr() -> _Run:
    return _Run("CRR")


@pytest.fixture(scope="module")
def b31() -> _Run:
    return _Run("BASEL_3_1")


# ---------------------------------------------------------------------------
# The split actually happens — without this the rest is vacuous (LESSONS C2).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("regime", ["crr", "b31"])
def test_splitting_loan_really_splits(regime: str, request: pytest.FixtureRequest) -> None:
    """LOAN_SPLIT emits >1 leg and LOAN_CTRL stays a single row."""
    run: _Run = request.getfixturevalue(regime)

    split_legs = run.legs_of("LOAN_SPLIT")
    assert split_legs.height > 1, "fixture no longer exercises the splitter"
    assert set(split_legs["re_split_role"].to_list()) == {"secured", "residual"}

    control = run.legs_of("LOAN_CTRL")
    assert control.height == 1
    assert control["re_split_role"][0] is None


# ---------------------------------------------------------------------------
# Ledger-level conservation: per parent, sum over legs == parent input.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("regime", ["crr", "b31"])
@pytest.mark.parametrize(("column", "expected"), sorted(_CONSERVED_ON_BS.items()))
def test_extensive_carrier_conserved_across_legs(
    regime: str, column: str, expected: float, request: pytest.FixtureRequest
) -> None:
    """Every extensive carrier sums, over the legs, to the parent's input amount."""
    run: _Run = request.getfixturevalue(regime)
    legs = run.legs_of("LOAN_SPLIT")
    assert _sum(legs, column) == pytest.approx(expected, rel=1e-9)


@pytest.mark.parametrize("regime", ["crr", "b31"])
@pytest.mark.parametrize("column", _CONSERVED_RE_COLLATERAL)
def test_re_collateral_carrier_equals_one_pledge(
    regime: str, column: str, request: pytest.FixtureRequest
) -> None:
    """The RE collateral carriers total exactly one pledge, not one per leg."""
    run: _Run = request.getfixturevalue(regime)
    assert _sum(run.ledger, column) == pytest.approx(TOTAL_RE_PLEDGE_VALUE, rel=1e-9)


@pytest.mark.parametrize("regime", ["crr", "b31"])
def test_control_loan_carriers_untouched(regime: str, request: pytest.FixtureRequest) -> None:
    """The non-splitting control keeps its full input amounts (survives the fix)."""
    run: _Run = request.getfixturevalue(regime)
    control = run.legs_of("LOAN_CTRL")
    assert _sum(control, "drawn_amount") == pytest.approx(CONTROL_LOAN_DRAWN)
    assert _sum(control, "reporting_gross_on_bs") == pytest.approx(CONTROL_LOAN_DRAWN)
    assert _sum(control, "collateral_re_market_value") == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Template-level: the numbers a firm would actually file.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("regime", ["crr", "b31"])
def test_cr4_total_on_bs_gross_equals_portfolio_input(
    regime: str, request: pytest.FixtureRequest
) -> None:
    """Pillar 3 CR4 TOTAL col a == the portfolio's actual on-BS gross exposure."""
    run: _Run = request.getfixturevalue(regime)
    assert run.pillar3.cr4 is not None
    total = _total_row(run.pillar3.cr4)
    assert float(total["a"]) == pytest.approx(TOTAL_ON_BS_GROSS, rel=1e-9)
    assert float(total["a"]) != pytest.approx(DUPLICATED_ON_BS_GROSS, rel=1e-9)


@pytest.mark.parametrize("regime", ["crr", "b31"])
def test_cr4_gross_never_below_post_crm_ead(regime: str, request: pytest.FixtureRequest) -> None:
    """CR4 TOTAL: gross (a + b) >= post-CRM EAD (c + d).

    The duplication inverted this identity — 2,450,000 of gross against
    1,425,000 of EAD for a 1,425,000 book. Anchored to the source total.
    """
    run: _Run = request.getfixturevalue(regime)
    assert run.pillar3.cr4 is not None
    total = _total_row(run.pillar3.cr4)
    gross = float(total["a"]) + float(total["b"] or 0.0)
    post_crm = float(total["c"]) + float(total["d"] or 0.0)
    assert gross == pytest.approx(TOTAL_ON_BS_GROSS, rel=1e-9)
    assert post_crm == pytest.approx(TOTAL_ON_BS_GROSS, rel=1e-9)
    assert gross == pytest.approx(post_crm, rel=1e-9)


@pytest.mark.parametrize("regime", ["crr", "b31"])
def test_c07_original_exposure_equals_portfolio_input(
    regime: str, request: pytest.FixtureRequest
) -> None:
    """COREP C 07.00 col 0010 summed over every sheet == the portfolio input.

    The splitter reclassifies the secured leg to ``residential_mortgage``, so
    the duplication shows up as the SAME amount on two different sheets.
    """
    run: _Run = request.getfixturevalue(regime)
    total = 0.0
    for frame in run.corep.c07_00.values():
        if "0010" not in frame.columns or not frame.height:
            continue
        rows = frame.filter(pl.col("row_ref") == "0010")
        total += _sum(rows, "0010")
    assert total == pytest.approx(TOTAL_ON_BS_GROSS, rel=1e-9)
    assert total != pytest.approx(DUPLICATED_ON_BS_GROSS, rel=1e-9)


# ---------------------------------------------------------------------------
# Capital must NOT move — the fix is a carrier fix, not a risk-weight change.
# ---------------------------------------------------------------------------


def test_crr_capital_unchanged(crr: _Run) -> None:
    """CRR hand-calc: secured 820,000 @ 35% + residual 205,000 @ 100% + control.

    EAD = 1,025,000. Art. 125 caps the secured part at 80% x 1,000,000 =
    800,000, so secured = 800,000 @ 35% = 280,000 and residual = 225,000 @
    100%. Control = 400,000 @ 100%.
    """
    legs = crr.legs_of("LOAN_SPLIT")
    rows = {r["re_split_role"]: r for r in legs.to_dicts()}
    assert rows["secured"]["ead_final"] == pytest.approx(800_000.0, rel=1e-9)
    assert rows["secured"]["risk_weight"] == pytest.approx(0.35, rel=1e-9)
    assert rows["residual"]["ead_final"] == pytest.approx(225_000.0, rel=1e-9)
    assert rows["residual"]["risk_weight"] == pytest.approx(1.0, rel=1e-9)
    assert _sum(crr.ledger, "rwa_final") == pytest.approx(280_000.0 + 225_000.0 + 400_000.0)


def test_b31_capital_unchanged(b31: _Run) -> None:
    """B3.1 hand-calc: Art. 124F caps the secured part at 55% x 1,000,000.

    EAD = 1,025,000 -> secured 550,000 @ 20% = 110,000; residual 475,000 @
    100%. Control = 400,000 @ 100%.
    """
    legs = b31.legs_of("LOAN_SPLIT")
    rows = {r["re_split_role"]: r for r in legs.to_dicts()}
    assert rows["secured"]["ead_final"] == pytest.approx(550_000.0, rel=1e-9)
    assert rows["secured"]["risk_weight"] == pytest.approx(0.20, rel=1e-9)
    assert rows["residual"]["ead_final"] == pytest.approx(475_000.0, rel=1e-9)
    assert rows["residual"]["risk_weight"] == pytest.approx(1.0, rel=1e-9)
    assert _sum(b31.ledger, "rwa_final") == pytest.approx(110_000.0 + 475_000.0 + 400_000.0)
