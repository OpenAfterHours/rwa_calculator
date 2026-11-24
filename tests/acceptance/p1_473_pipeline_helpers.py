"""
Pipeline helpers for the P1.473 acceptance tests: the Art. 124E(1)(a) primary residence.

Pipeline position:
    in-memory frames -> make_raw_bundle (loader-edge seal)
        -> PipelineOrchestrator.run_with_data -> SA results

Key responsibilities:
- Build one small real-estate portfolio: natural-person landlords over the
  Art. 124E(2) three-property limit, each loan secured on a 500,000 home or
  buy-to-let property, flagged ``is_primary_residence`` True / False / null on
  the collateral row (the limb-(a) attestation) — regulatory residential RE
  (Art. 124F / 124G), non-qualifying "other" residential RE (Art. 124J), one
  commercial-typed property flagged as the home (Art. 124E(6), never limb (a)),
  a defaulted borrower's home (Art. 127(1) / (3)) and a sole trader's home (a
  natural person booked ``corporate``, which reaches the real-estate splitter).
- Run it under either regime and return one row per input loan, summed over any
  split legs on ``source_exposure_reference`` so a leg count can never hide RWA.
- Optionally run the same loans on A-IRB (retail-mortgage model permission,
  internal PD, own LGD) so the Basel 3.1 output floor's SA-equivalent basis
  (``sa_rwa``, the S-TREA input of Art. 92(2A)) can be read per loan.

Every loan has its own counterparty, so the retail aggregation and the
three-property count of one loan never leak into another's, except the
landlord group (``LN_LL_*``): a home loan and two buy-to-let loans booked to ONE
counterparty, the most common shape of a landlord's book. An implementation that
tested "the obligor has exactly one real-estate collateral row" at counterparty
scope would deny that home loan limb (a); the per-exposure test must not.

References:
- PS1/26 Art. 124E(1)(a)/(b), (2), (4): material dependence and the two limbs
- PS1/26 Art. 124F, 124G, 124L(1)(a): the weights either side of the flag
- PS1/26 Art. 92(2A): the output floor's S-TREA, read from ``sa_rwa``
- IMPLEMENTATION_PLAN.md: P1.473 (review RE-18)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, Any

import polars as pl

from rwa_calc.contracts.config import CalculationConfig, PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.fixtures.raw_bundle import make_raw_bundle

if TYPE_CHECKING:
    from rwa_calc.contracts.bundles import OutputFloorSummary

REPORTING_DATE = date(2027, 1, 2)
PROPERTY_VALUE = 500_000.0
FIRST_CHARGE_LOAN = 300_000.0  # LTV 0.60 on the 500,000 property
JUNIOR_LOAN = 50_000.0  # behind a 250,000 third-party prior charge
JUNIOR_PRIOR_CHARGE_LTV = 0.5

#: Over the Art. 124E(2) limit: four qualifying (non-primary-residence) properties.
OVER_LIMIT_COUNT = 4
#: Within the limit (limb (b) met): the control borrower for the junior leg.
WITHIN_LIMIT_COUNT = 3

# Loan references, one counterparty each (``CP_<loan>``).
LN_HOME = "LN_P1473_HOME"  # first charge on the landlord's home, attested
LN_BTL = "LN_P1473_BTL"  # first charge on a buy-to-let, attested not the home
LN_UNKNOWN = "LN_P1473_UNKNOWN"  # first charge, attestation not supplied (null)
LN_TWO_PROPS = "LN_P1473_TWO_PROPS"  # home + buy-to-let pledged to one loan
LN_TWO_HOMES = "LN_P1473_TWO_HOMES"  # two properties, both flagged primary
LN_INCOME = "LN_P1473_INCOME"  # flagged home, but explicitly income-producing
LN_JUNIOR = "LN_P1473_JUNIOR"  # junior charge on the landlord's home, attested
LN_JUNIOR_CTRL = "LN_P1473_JUNIOR_CTRL"  # same junior charge, within the limit
LN_OTHER_RRE = "LN_P1473_OTHER_RRE"  # first charge on the home, not regulatory RE (124J)
LN_OTHER_RRE_BTL = "LN_P1473_OTHER_RRE_BTL"  # the same on a buy-to-let (124J(1) adequacy)
LN_COMMERCIAL = "LN_P1473_COMMERCIAL"  # commercial-typed property flagged as the home
LN_DEFAULTED = "LN_P1473_DEFAULTED"  # first charge on the home, borrower in default
LN_SOLE_TRADER = "LN_P1473_SOLE_TRADER"  # the home, borrower booked corporate (sole trader)
# The landlord group: one counterparty, three loans, each on its own property.
LANDLORD_COUNTERPARTY = "CP_LN_P1473_LANDLORD"
LN_LL_HOME = "LN_P1473_LL_HOME"  # the landlord's home, attested
LN_LL_BTL1 = "LN_P1473_LL_BTL1"  # a buy-to-let of the same landlord
LN_LL_BTL2 = "LN_P1473_LL_BTL2"  # a second buy-to-let of the same landlord

#: The A-IRB retail-mortgage inputs of the IRB run (any positive values serve:
#: the floor test reads only the SA-equivalent, which does not depend on them).
_IRB_MODEL_ID = "M_P1473_RM"
_IRB_PD = 0.01
_IRB_LGD = 0.10


@dataclass(frozen=True)
class LoanResult:
    """One input loan's outcome, summed over any split legs.

    ``legs`` is the number of result rows the loan came back as (2 where the
    real-estate splitter emitted ``_sec`` / ``_res`` legs). ``sa_rwa`` is the
    SA-equivalent RWA the Basel 3.1 output floor sums into S-TREA (None where the
    run carries no such column, as under CRR).
    """

    loan_reference: str
    ead: float
    rwa: float
    has_income_cover: bool | None
    legs: int = 1
    approach: str | None = None
    sa_rwa: float | None = None

    @property
    def risk_weight(self) -> float:
        """EAD-weighted risk weight of the loan (RWA / EAD)."""
        return self.rwa / self.ead


@dataclass(frozen=True)
class _Pledge:
    """One real-estate collateral row."""

    suffix: str
    is_primary_residence: bool | None
    market_value: float = PROPERTY_VALUE
    property_ltv: float = FIRST_CHARGE_LOAN / PROPERTY_VALUE
    prior_charge_ltv: float = 0.0
    is_income_producing: bool | None = None
    property_type: str = "residential"
    is_qualifying_re: bool = True


@dataclass(frozen=True)
class _LoanSpec:
    """One loan, its borrower's qualifying-property count and its pledges.

    ``counterparty`` names a shared obligor (default: ``CP_<reference>``, one per
    loan); loans sharing one must agree on every borrower field.
    ``entity_type`` "corporate" with ``is_natural_person`` True is the sole trader
    ``docs/data-model/input-schemas.md`` documents.
    """

    reference: str
    drawn: float
    property_count: int
    pledges: tuple[_Pledge, ...]
    counterparty: str | None = None
    entity_type: str = "individual"
    defaulted: bool = False
    product_type: str = "mortgage"

    @property
    def counterparty_reference(self) -> str:
        """The obligor's reference."""
        return self.counterparty or f"CP_{self.reference}"


#: The scenario, one row per loan. Pledged values are chosen so that every
#: loan has an LTV of 0.60 (the junior legs include the prior charge, Art. 124C(3)).
LOANS: tuple[_LoanSpec, ...] = (
    _LoanSpec(LN_HOME, FIRST_CHARGE_LOAN, OVER_LIMIT_COUNT, (_Pledge("H", True),)),
    _LoanSpec(LN_BTL, FIRST_CHARGE_LOAN, OVER_LIMIT_COUNT, (_Pledge("B", False),)),
    _LoanSpec(LN_UNKNOWN, FIRST_CHARGE_LOAN, OVER_LIMIT_COUNT, (_Pledge("U", None),)),
    _LoanSpec(
        LN_TWO_PROPS,
        FIRST_CHARGE_LOAN,
        OVER_LIMIT_COUNT,
        (
            _Pledge("H", True, market_value=PROPERTY_VALUE / 2),
            _Pledge("B", False, market_value=PROPERTY_VALUE / 2),
        ),
    ),
    _LoanSpec(
        LN_TWO_HOMES,
        FIRST_CHARGE_LOAN,
        OVER_LIMIT_COUNT,
        (
            _Pledge("H1", True, market_value=PROPERTY_VALUE / 2),
            _Pledge("H2", True, market_value=PROPERTY_VALUE / 2),
        ),
    ),
    _LoanSpec(
        LN_INCOME,
        FIRST_CHARGE_LOAN,
        OVER_LIMIT_COUNT,
        (_Pledge("I", True, is_income_producing=True),),
    ),
    _LoanSpec(
        LN_JUNIOR,
        JUNIOR_LOAN,
        OVER_LIMIT_COUNT,
        (_Pledge("J", True, prior_charge_ltv=JUNIOR_PRIOR_CHARGE_LTV),),
    ),
    _LoanSpec(
        LN_JUNIOR_CTRL,
        JUNIOR_LOAN,
        WITHIN_LIMIT_COUNT,
        (_Pledge("J", True, prior_charge_ltv=JUNIOR_PRIOR_CHARGE_LTV),),
    ),
    _LoanSpec(
        LN_OTHER_RRE,
        FIRST_CHARGE_LOAN,
        OVER_LIMIT_COUNT,
        (_Pledge("O", True, is_qualifying_re=False),),
    ),
    _LoanSpec(
        LN_OTHER_RRE_BTL,
        FIRST_CHARGE_LOAN,
        OVER_LIMIT_COUNT,
        (_Pledge("OB", False, is_qualifying_re=False),),
    ),
    _LoanSpec(
        LN_COMMERCIAL,
        FIRST_CHARGE_LOAN,
        OVER_LIMIT_COUNT,
        (_Pledge("C", True, property_type="commercial"),),
    ),
    _LoanSpec(
        LN_DEFAULTED, FIRST_CHARGE_LOAN, OVER_LIMIT_COUNT, (_Pledge("D", True),), defaulted=True
    ),
    _LoanSpec(
        LN_SOLE_TRADER,
        FIRST_CHARGE_LOAN,
        OVER_LIMIT_COUNT,
        (_Pledge("S", True),),
        entity_type="corporate",
        product_type="term_loan",
    ),
    _LoanSpec(
        LN_LL_HOME,
        FIRST_CHARGE_LOAN,
        OVER_LIMIT_COUNT,
        (_Pledge("H", True),),
        counterparty=LANDLORD_COUNTERPARTY,
    ),
    _LoanSpec(
        LN_LL_BTL1,
        FIRST_CHARGE_LOAN,
        OVER_LIMIT_COUNT,
        (_Pledge("B1", False),),
        counterparty=LANDLORD_COUNTERPARTY,
    ),
    _LoanSpec(
        LN_LL_BTL2,
        FIRST_CHARGE_LOAN,
        OVER_LIMIT_COUNT,
        (_Pledge("B2", False),),
        counterparty=LANDLORD_COUNTERPARTY,
    ),
)

#: The loans of the A-IRB run: every loan booked to an individual. The sole
#: trader is booked ``corporate``, which the run's retail-mortgage model
#: permission does not cover, so it would fall back to SA and stop being an
#: output-floor input; it is measured on the SA run only.
IRB_LOANS: tuple[_LoanSpec, ...] = tuple(s for s in LOANS if s.entity_type == "individual")


def run_portfolio(regime: str) -> dict[str, LoanResult]:
    """Run the P1.473 portfolio SA-only under ``regime`` ("crr" | "b31").

    Returns:
        loan_reference -> its summed SA outcome. Asserts every loan came back.
    """
    config = (
        CalculationConfig.basel_3_1(
            reporting_date=REPORTING_DATE, permission_mode=PermissionMode.STANDARDISED
        )
        if regime == "b31"
        else CalculationConfig.crr(
            reporting_date=REPORTING_DATE, permission_mode=PermissionMode.STANDARDISED
        )
    )
    result = PipelineOrchestrator().run_with_data(_bundle(LOANS), config)
    assert result.sa_results is not None, "SA-only run must produce SA results"
    return _per_loan(result.sa_results.collect(), LOANS)


def run_irb_portfolio() -> tuple[dict[str, LoanResult], OutputFloorSummary]:
    """Run the P1.473 portfolio's ``IRB_LOANS`` on A-IRB retail mortgages under Basel 3.1.

    Returns:
        (loan_reference -> its summed outcome, with ``approach`` and the output
        floor's SA-equivalent ``sa_rwa``; the run's ``OutputFloorSummary``).
    """
    config = CalculationConfig.basel_3_1(
        reporting_date=REPORTING_DATE, permission_mode=PermissionMode.IRB
    )
    result = PipelineOrchestrator().run_with_data(_bundle(IRB_LOANS, irb=True), config)
    assert result.output_floor_summary is not None, "a Basel 3.1 IRB run has a floor summary"
    return _per_loan(result.results.collect(), IRB_LOANS), result.output_floor_summary


# =========================================================================
# Private helpers
# =========================================================================


def _per_loan(rows: pl.DataFrame, specs: tuple[_LoanSpec, ...]) -> dict[str, LoanResult]:
    """One ``LoanResult`` per input loan, summed over split legs; asserts none is lost."""
    optional: list[pl.Expr] = []
    if "approach_applied" in rows.columns:
        optional.append(pl.col("approach_applied").first().alias("approach"))
    if "sa_rwa" in rows.columns:  # absent under CRR: no output floor
        optional.append(pl.col("sa_rwa").sum())
    summed = rows.group_by("source_exposure_reference").agg(
        pl.col("ead_final").sum().alias("ead"),
        pl.col("rwa_final").sum().alias("rwa"),
        pl.col("has_income_cover").first().alias("has_income_cover"),
        pl.len().alias("legs"),
        *optional,
    )
    out = {
        r["source_exposure_reference"]: LoanResult(
            loan_reference=r["source_exposure_reference"],
            ead=r["ead"],
            rwa=r["rwa"],
            has_income_cover=r["has_income_cover"],
            legs=r["legs"],
            approach=r.get("approach"),
            sa_rwa=r.get("sa_rwa"),
        )
        for r in summed.iter_rows(named=True)
    }
    missing = {spec.reference for spec in specs} - set(out)
    assert not missing, f"loans missing from the results: {sorted(missing)}"
    return out


def _irb_frames(specs: tuple[_LoanSpec, ...]) -> dict[str, pl.DataFrame]:
    """A retail-mortgage A-IRB permission and one internal PD per counterparty."""
    obligors = list(dict.fromkeys(spec.counterparty_reference for spec in specs))
    ratings = pl.DataFrame(
        {
            "rating_reference": [f"RTG_{cp}" for cp in obligors],
            "counterparty_reference": obligors,
            "rating_type": ["internal"] * len(obligors),
            "pd": [_IRB_PD] * len(obligors),
            "model_id": [_IRB_MODEL_ID] * len(obligors),
            "rating_date": [date(2026, 6, 30)] * len(obligors),
        }
    )
    model_permissions = pl.DataFrame(
        {
            "model_id": [_IRB_MODEL_ID],
            "exposure_class": ["retail_mortgage"],
            "approach": ["advanced_irb"],
            "country_codes": [None],
            "excluded_book_codes": [None],
        },
        schema_overrides={"country_codes": pl.String, "excluded_book_codes": pl.String},
    )
    return {"ratings": ratings, "model_permissions": model_permissions}


def _bundle(specs: tuple[_LoanSpec, ...], *, irb: bool = False) -> Any:
    """The raw bundle for ``specs``: one counterparty row per distinct obligor."""
    obligors: dict[str, dict[str, Any]] = {}
    for spec in specs:
        row = {
            "counterparty_reference": spec.counterparty_reference,
            "counterparty_name": spec.counterparty_reference,
            "entity_type": spec.entity_type,
            "country_code": "GB",
            "default_status": spec.defaulted,
            "is_natural_person": True,
            "is_social_housing": False,
            "qualifying_property_count": spec.property_count,
        }
        assert obligors.setdefault(spec.counterparty_reference, row) == row, (
            f"loans of {spec.counterparty_reference} disagree on a borrower field"
        )
    counterparties = list(obligors.values())
    loans = [
        {
            "loan_reference": spec.reference,
            "product_type": spec.product_type,
            "book_code": "B",
            "counterparty_reference": spec.counterparty_reference,
            "value_date": date(2024, 1, 1),
            "maturity_date": date(2052, 1, 2),
            "currency": "GBP",
            "drawn_amount": spec.drawn,
            "interest": 0.0,
            "seniority": "senior",
            **({"lgd": _IRB_LGD} if irb else {}),
        }
        for spec in specs
    ]
    collateral = [
        {
            "collateral_reference": f"COL_{spec.reference}_{pledge.suffix}",
            "collateral_type": "real_estate",
            "currency": "GBP",
            "market_value": pledge.market_value,
            "beneficiary_type": "loan",
            "beneficiary_reference": spec.reference,
            "property_type": pledge.property_type,
            "property_ltv": pledge.property_ltv,
            "prior_charge_ltv": pledge.prior_charge_ltv,
            "is_qualifying_re": pledge.is_qualifying_re,
            "is_income_producing": pledge.is_income_producing,
            "is_primary_residence": pledge.is_primary_residence,
        }
        for spec in specs
        for pledge in spec.pledges
    ]
    return make_raw_bundle(
        counterparties=_frame(counterparties),
        loans=_frame(loans),
        collateral=_frame(collateral),
        facility_mappings=pl.DataFrame(
            schema={
                "parent_facility_reference": pl.String,
                "child_reference": pl.String,
                "child_type": pl.String,
            }
        ),
        **(_irb_frames(specs) if irb else {}),
    )


def _frame(rows: list[dict[str, Any]]) -> pl.DataFrame:
    """A frame from row dicts; an all-None column is typed by the loader seal."""
    keys: list[str] = []
    for row in rows:
        keys.extend(k for k in row if k not in keys)
    return pl.DataFrame({k: [row.get(k) for row in rows] for k in keys}, strict=False)
