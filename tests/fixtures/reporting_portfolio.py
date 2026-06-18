"""
Rich multi-class portfolio for the reporting golden gate (migration Phase 7 S0).

Pipeline position:
    build_reporting_bundle() -> RawDataBundle -> PipelineOrchestrator
        -> AggregatedResultBundle -> COREPGenerator / Pillar3Generator

Key responsibilities:
- Hand-author a single compact portfolio that, when run under BOTH
  ``CalculationConfig.crr`` and ``CalculationConfig.basel_3_1`` (IRB permission
  mode), populates the full COREP + Pillar 3 template surface: at least one
  exposure in every loan-based reporting bucket.
- Serve as the *oracle portfolio* for ``tests/test_reporting_golden.py``: the
  declarative-reporting strangler (Phase 7 S4..N) diffs each migrated template
  against frozen goldens captured from this portfolio, so it must exercise every
  template that will be migrated.

Coverage (one exposure each unless noted):
    SA          sovereign, institution, corporate (rated + unrated), corporate-SME,
                retail, residential real estate (RRE), commercial real estate (CRE),
                defaulted, other items
    IRB         F-IRB corporate, A-IRB corporate, A-IRB retail
    Slotting    specialised lending (project finance, strong)
    Equity      one listed equity holding (Art. 133 SA / Art. 155 IRB simple)

Equity (added Phase 7 S1): equity flows through the separate
``get_equity_result_bundle`` path, but the aggregator already concatenates the
prepared equity frame into ``combined_unmultiplied`` BEFORE the
``AGGREGATOR_EXIT`` seal (``aggregator.py``), so an equity row DOES reach
``result.results`` with ``approach_applied='equity'`` / ``exposure_class='equity'``.
The earlier "equity does not reach results" belief was stale — verified against
the wiring this slice. The equity exposure here surfaces equity in the reporting
templates that filter on the equity class/approach.

Templates reconciled in Phase 7 S1 (Option B — reporting reads the sealed
canonical names): C 08.02 / C 08.03 / C 08.05 and Pillar 3 CR6 / CR9 now POPULATE
from real sealed output. The generators previously probed the fictional
``irb_pd_floored`` / ``irb_pd_original`` (and LGD equivalents); the sealed
``aggregator_exit`` provides ``pd_floored`` / ``pd`` / ``lgd_floored`` /
``lgd_input``, which the generators now read directly. CR9.1 remains EMPTY — it
is gated on ``ecai_pd_mapping`` / ``external_rating_equivalent`` (an ECAI PD-
mapping disclosure the engine does not produce), an accept-empty decision out of
S1 scope.

Routing is driven entirely by input columns (no config branching):
- SA vs IRB:  an exposure routes IRB only when its inherited rating carries an
  internal PD *and* a matching ``model_permissions`` row exists *and* the config
  permits IRB. SA exposures carry external/no rating (no internal PD).
- F-IRB vs A-IRB:  A-IRB requires a firm LGD estimate
  (``lgd`` set + ``has_sufficient_collateral_data=True``, CRR Art. 169A/169B);
  F-IRB otherwise.
- Slotting:  a ``specialised_lending`` row + slotting permission, and *no*
  internal PD (so F-IRB/A-IRB are unavailable and the SL exposure falls to
  slotting, CRR Art. 153(5)).
- Defaulted:  ``is_defaulted`` / counterparty ``default_status`` forces SA.

All internal ratings carry ``model_id = "TEST_FULL_IRB"`` to match
``create_full_irb_model_permissions`` (FIRB + AIRB + slotting for every class).

References:
- tests/fixtures/acceptance_pipeline.py: the run_parquet_pipeline pattern this mirrors in-code
- tests/fixtures/irb_test_helpers.py: create_full_irb_model_permissions
- src/rwa_calc/data/schemas.py: COUNTERPARTY/LOAN/RATINGS/SPECIALISED_LENDING schemas
- .claude/state/phase7-plan.md: S0 locked harness design
"""

from __future__ import annotations

from datetime import date

import polars as pl

from rwa_calc.contracts.bundles import RawDataBundle
from tests.fixtures.irb_test_helpers import create_full_irb_model_permissions
from tests.fixtures.raw_bundle import make_raw_bundle

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MODEL_ID = "TEST_FULL_IRB"  # must match create_full_irb_model_permissions
_MATURITY = date(2031, 12, 31)  # > both reporting dates (CRR 2025, B31 2027)

# Counterparty references
CP_SOV = "RP-CP-SOV"
CP_INST = "RP-CP-INST"
CP_CORP_RATED = "RP-CP-CORP-RATED"
CP_CORP_UNRATED = "RP-CP-CORP-UNRATED"
CP_SME = "RP-CP-SME"
CP_RETAIL = "RP-CP-RETAIL"
CP_RRE = "RP-CP-RRE"
CP_CRE = "RP-CP-CRE"
CP_DEFAULT = "RP-CP-DEFAULT"
CP_OTHER = "RP-CP-OTHER"
CP_FIRB = "RP-CP-FIRB"
CP_AIRB = "RP-CP-AIRB"
CP_AIRB_RET = "RP-CP-AIRB-RET"
CP_SL = "RP-CP-SL"
CP_EQUITY = "RP-CP-EQUITY"

# Equity exposure reference (separate equity input table, not a loan)
EQ_LISTED = "RP-EQ-LISTED"

# Loan references
LN_SOV = "RP-LN-SOV"
LN_INST = "RP-LN-INST"
LN_CORP_RATED = "RP-LN-CORP-RATED"
LN_CORP_UNRATED = "RP-LN-CORP-UNRATED"
LN_SME = "RP-LN-SME"
LN_RETAIL = "RP-LN-RETAIL"
LN_RRE = "RP-LN-RRE"
LN_CRE = "RP-LN-CRE"
LN_DEFAULT = "RP-LN-DEFAULT"
LN_OTHER = "RP-LN-OTHER"
LN_FIRB = "RP-LN-FIRB"
LN_AIRB = "RP-LN-AIRB"
LN_AIRB_RET = "RP-LN-AIRB-RET"
LN_SL = "RP-LN-SL"

# Every loan reference, for smoke assertions
ALL_LOAN_REFERENCES = (
    LN_SOV,
    LN_INST,
    LN_CORP_RATED,
    LN_CORP_UNRATED,
    LN_SME,
    LN_RETAIL,
    LN_RRE,
    LN_CRE,
    LN_DEFAULT,
    LN_OTHER,
    LN_FIRB,
    LN_AIRB,
    LN_AIRB_RET,
    LN_SL,
)


# ---------------------------------------------------------------------------
# Main public entry point
# ---------------------------------------------------------------------------


def build_reporting_bundle() -> RawDataBundle:
    """Assemble the rich reporting portfolio as a sealed ``RawDataBundle``.

    The bundle is sealed against the loader edge contracts by ``make_raw_bundle``,
    so it is shape-identical to a parquet-loaded production bundle. Run it through
    ``PipelineOrchestrator().run_with_data`` under a CRR or Basel 3.1 config.
    """
    return make_raw_bundle(
        counterparties=_counterparties(),
        loans=_loans(),
        ratings=_ratings(),
        model_permissions=create_full_irb_model_permissions(),
        specialised_lending=_specialised_lending(),
        collateral=_collateral(),
        equity_exposures=_equity_exposures(),
    )


# ---------------------------------------------------------------------------
# Table builders (private)
# ---------------------------------------------------------------------------


def _counterparties() -> pl.DataFrame:
    """Counterparties — one per exposure-class/approach bucket."""
    rows: list[dict] = [
        {"counterparty_reference": CP_SOV, "entity_type": "sovereign", "country_code": "GB"},
        {"counterparty_reference": CP_INST, "entity_type": "institution", "country_code": "GB"},
        {
            "counterparty_reference": CP_CORP_RATED,
            "entity_type": "corporate",
            "country_code": "GB",
            "annual_revenue": 100_000_000.0,
        },
        {
            "counterparty_reference": CP_CORP_UNRATED,
            "entity_type": "corporate",
            "country_code": "GB",
            "annual_revenue": 60_000_000.0,
        },
        {
            "counterparty_reference": CP_SME,
            "entity_type": "corporate",
            "country_code": "GB",
            "annual_revenue": 30_000_000.0,
        },
        {
            "counterparty_reference": CP_RETAIL,
            "entity_type": "individual",
            "country_code": "GB",
            "is_natural_person": True,
            "is_managed_as_retail": True,
        },
        {
            "counterparty_reference": CP_RRE,
            "entity_type": "individual",
            "country_code": "GB",
            "is_natural_person": True,
            "is_managed_as_retail": True,
        },
        {
            "counterparty_reference": CP_CRE,
            "entity_type": "corporate",
            "country_code": "GB",
            "annual_revenue": 200_000_000.0,
        },
        {
            "counterparty_reference": CP_DEFAULT,
            "entity_type": "corporate",
            "country_code": "GB",
            "annual_revenue": 50_000_000.0,
            "default_status": True,
        },
        {
            "counterparty_reference": CP_OTHER,
            "entity_type": "other_items_in_collection",
            "country_code": "GB",
        },
        {
            "counterparty_reference": CP_FIRB,
            "entity_type": "corporate",
            "country_code": "GB",
            "annual_revenue": 100_000_000.0,
        },
        {
            "counterparty_reference": CP_AIRB,
            "entity_type": "corporate",
            "country_code": "GB",
            "annual_revenue": 30_000_000.0,
        },
        {
            "counterparty_reference": CP_AIRB_RET,
            "entity_type": "individual",
            "country_code": "GB",
            "is_natural_person": True,
            "is_managed_as_retail": True,
        },
        {
            "counterparty_reference": CP_SL,
            "entity_type": "corporate",
            "country_code": "GB",
            "annual_revenue": 200_000_000.0,
        },
        {
            "counterparty_reference": CP_EQUITY,
            "entity_type": "corporate",
            "country_code": "GB",
            "annual_revenue": 200_000_000.0,
        },
    ]
    return pl.DataFrame(rows)


def _equity_exposures() -> pl.DataFrame:
    """One listed equity holding — exercises the separate equity calculator path.

    Equity routes via the ``equity_exposures`` input table (not loans). The
    aggregator concatenates the prepared equity frame into ``result.results``
    before the seal, so this row appears with ``approach_applied='equity'`` /
    ``exposure_class='equity'`` and surfaces equity in the reporting templates.
    """
    return pl.DataFrame(
        [
            {
                "exposure_reference": EQ_LISTED,
                "counterparty_reference": CP_EQUITY,
                "equity_type": "listed",
                "currency": "GBP",
                "carrying_value": 1_000_000.0,
                "fair_value": 1_000_000.0,
            }
        ]
    )


def _loans() -> pl.DataFrame:
    """Loans — one drawn exposure per bucket. EAD = drawn_amount (+interest)."""
    rows: list[dict] = [
        _loan(LN_SOV, CP_SOV, 1_000_000.0),
        _loan(LN_INST, CP_INST, 2_000_000.0),
        _loan(LN_CORP_RATED, CP_CORP_RATED, 5_000_000.0),
        _loan(LN_CORP_UNRATED, CP_CORP_UNRATED, 3_000_000.0),
        _loan(LN_SME, CP_SME, 500_000.0),
        _loan(LN_RETAIL, CP_RETAIL, 250_000.0),
        # Residential real estate: property on the loan row drives the RE branch.
        _loan(
            LN_RRE,
            CP_RRE,
            400_000.0,
            property_type="residential",
            ltv=0.60,
        ),
        # Commercial real estate with income cover (preferential 50% CRE RW gate).
        _loan(
            LN_CRE,
            CP_CRE,
            10_000_000.0,
            property_type="commercial",
            ltv=0.50,
            has_income_cover=True,
        ),
        # Defaulted -> forced SA regardless of permissions.
        _loan(LN_DEFAULT, CP_DEFAULT, 1_000_000.0, is_defaulted=True),
        _loan(LN_OTHER, CP_OTHER, 100_000.0),
        # F-IRB corporate: internal PD, NO firm LGD -> foundation.
        _loan(LN_FIRB, CP_FIRB, 50_000_000.0),
        # A-IRB corporate: firm LGD estimate -> advanced.
        _loan(
            LN_AIRB,
            CP_AIRB,
            20_000_000.0,
            lgd=0.30,
            has_sufficient_collateral_data=True,
        ),
        # A-IRB retail: firm LGD estimate, retail obligor -> advanced.
        _loan(
            LN_AIRB_RET,
            CP_AIRB_RET,
            100_000.0,
            lgd=0.20,
            has_sufficient_collateral_data=True,
        ),
        # Slotting: SL row + slotting permission + no internal PD.
        _loan(LN_SL, CP_SL, 75_000_000.0),
    ]
    return pl.DataFrame(rows)


def _ratings() -> pl.DataFrame:
    """Ratings — external CQS for SA, internal PD (+ model_id) for IRB.

    Slotting (CP_SL) intentionally has NO rating: with no internal PD the
    F-IRB/A-IRB branches are unavailable, so the SL exposure falls to slotting.
    """
    rows: list[dict] = [
        # External ECAI ratings (CQS) -> SA risk-weight lookup, no internal PD.
        _external(CP_SOV, cqs=1),
        _external(CP_INST, cqs=2),
        _external(CP_CORP_RATED, cqs=3),
        _external(CP_CRE, cqs=3),
        # Internal PD ratings -> IRB routing (model_id matches the permissions).
        _internal(CP_FIRB, pd=0.0075),
        _internal(CP_AIRB, pd=0.0100),
        _internal(CP_AIRB_RET, pd=0.0050),
        # Slotting: model_id (for the permission match) but NO PD, so the
        # F-IRB/A-IRB SL branches are unavailable and the exposure falls to
        # slotting (CRR Art. 153(5)).
        _internal_no_pd(CP_SL),
    ]
    return pl.DataFrame(rows)


def _specialised_lending() -> pl.DataFrame:
    """One project-finance slotting exposure (strong category)."""
    return pl.DataFrame(
        [
            {
                "counterparty_reference": CP_SL,
                "sl_type": "project_finance",
                "slotting_category": "strong",
                "is_hvcre": False,
            }
        ]
    )


def _collateral() -> pl.DataFrame:
    """Real-estate collateral that drives the SA RE loan-split.

    The RE branch fires only when a property ``collateral`` row is linked to the
    loan (``beneficiary_type='loan'``) so the HierarchyResolver populates the
    residential/commercial collateral-value columns the splitter reads — the
    loan-level ``property_type``/``ltv`` alone are not sufficient.
    """
    return pl.DataFrame(
        [
            # Residential mortgage: 400k loan / 666,667 value -> 60% LTV
            # (<= 80% secured band -> preferential residential RW).
            {
                "collateral_reference": "RP-COLL-RRE",
                "collateral_type": "real_estate",
                "property_type": "residential",
                "market_value": 666_667.0,
                "property_ltv": 0.60,
                "beneficiary_type": "loan",
                "beneficiary_reference": LN_RRE,
            },
            # Commercial RE: 10m loan / 20m value -> 50% LTV, income-producing
            # with rental cover >= 1.5x (CRR Art. 126(2) preferential 50% gate).
            {
                "collateral_reference": "RP-COLL-CRE",
                "collateral_type": "real_estate",
                "property_type": "commercial",
                "market_value": 20_000_000.0,
                "property_ltv": 0.50,
                "is_income_producing": True,
                "rental_to_interest_ratio": 1.8,
                "beneficiary_type": "loan",
                "beneficiary_reference": LN_CRE,
            },
        ]
    )


# ---------------------------------------------------------------------------
# Row helpers (private)
# ---------------------------------------------------------------------------


def _loan(
    loan_reference: str,
    counterparty_reference: str,
    drawn_amount: float,
    *,
    lgd: float | None = None,
    has_sufficient_collateral_data: bool = False,
    is_defaulted: bool = False,
    property_type: str | None = None,
    ltv: float | None = None,
    has_income_cover: bool = False,
) -> dict:
    """Build one loan row dict (unset optional columns seal to schema defaults)."""
    row: dict = {
        "loan_reference": loan_reference,
        "counterparty_reference": counterparty_reference,
        "drawn_amount": drawn_amount,
        "currency": "GBP",
        "maturity_date": _MATURITY,
        "seniority": "senior",
        "has_sufficient_collateral_data": has_sufficient_collateral_data,
        "is_defaulted": is_defaulted,
        "has_income_cover": has_income_cover,
    }
    if lgd is not None:
        row["lgd"] = lgd
    if property_type is not None:
        row["property_type"] = property_type
    if ltv is not None:
        row["ltv"] = ltv
    return row


def _external(counterparty_reference: str, *, cqs: int) -> dict:
    """External ECAI rating row (CQS, no internal PD)."""
    return {
        "rating_reference": f"RT-EXT-{counterparty_reference}",
        "counterparty_reference": counterparty_reference,
        "rating_type": "external",
        "rating_agency": "TEST_AGENCY",
        "cqs": cqs,
    }


def _internal(counterparty_reference: str, *, pd: float) -> dict:
    """Internal model rating row (PD + model_id for IRB routing)."""
    return {
        "rating_reference": f"RT-INT-{counterparty_reference}",
        "counterparty_reference": counterparty_reference,
        "rating_type": "internal",
        "pd": pd,
        "model_id": _MODEL_ID,
    }


def _internal_no_pd(counterparty_reference: str) -> dict:
    """Internal rating carrying only ``model_id`` (no PD) — for slotting routing."""
    return {
        "rating_reference": f"RT-INT-{counterparty_reference}",
        "counterparty_reference": counterparty_reference,
        "rating_type": "internal",
        "model_id": _MODEL_ID,
    }


# ---------------------------------------------------------------------------
# Smoke verification (run directly: python -m tests.fixtures.reporting_portfolio)
# ---------------------------------------------------------------------------


def _smoke() -> None:
    """Run the portfolio through both regimes and print routing coverage."""
    from rwa_calc.contracts.config import CalculationConfig
    from rwa_calc.domain.enums import PermissionMode
    from rwa_calc.engine.pipeline import PipelineOrchestrator

    for label, config in (
        (
            "CRR",
            CalculationConfig.crr(
                reporting_date=date(2025, 12, 31), permission_mode=PermissionMode.IRB
            ),
        ),
        (
            "BASEL_3_1",
            CalculationConfig.basel_3_1(
                reporting_date=date(2027, 6, 1),
                permission_mode=PermissionMode.IRB,
                enforce_retail_granularity=False,
            ),
        ),
    ):
        bundle = build_reporting_bundle()
        result = PipelineOrchestrator().run_with_data(bundle, config)
        df = result.results.collect()
        ref_col = "loan_reference" if "loan_reference" in df.columns else "exposure_reference"
        cols = [
            c
            for c in (ref_col, "exposure_class", "approach_applied", "rwa_final")
            if c in df.columns
        ]
        rep = df.select(cols).sort(ref_col)
        print(f"\n===== {label} =====")
        print(rep)
        print(
            "exposure_class counts:",
            df["exposure_class"].value_counts().sort("exposure_class").to_dicts(),
        )
        if "approach_applied" in df.columns:
            print(
                "approach counts:",
                df["approach_applied"].value_counts().sort("approach_applied").to_dicts(),
            )


if __name__ == "__main__":
    _smoke()
