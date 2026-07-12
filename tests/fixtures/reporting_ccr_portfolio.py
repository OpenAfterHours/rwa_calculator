"""
CCR reporting portfolio — the oracle for SA-CCR derivatives in the templates.

Pipeline position:
    build_reporting_ccr_bundle() -> RawDataBundle -> PipelineOrchestrator
        -> AggregatedResultBundle -> COREPGenerator / Pillar3Generator

Why a SECOND portfolio (rather than extending ``reporting_portfolio.py``):
the rich portfolio has no derivatives, and adding them there would move all 95
existing goldens at once — mixing the CCR question into every unrelated template
diff. This portfolio is small and CCR-shaped, so the C 07.00 / C 34 diffs stay
readable and the existing golden gate keeps its meaning.

Composition (deliberately minimal — every row earns its place):
    corporate loan      one plain SA exposure, so C 07.00 has an ordinary sheet
                        to contrast against, and C 02.00 has both loan RWA and
                        derivative RWA (the pair that exposes the footing defect)
    bilateral swap      one 10y GBP IR swap vs an institution (CQS 2 -> 50% RW),
                        unmargined -> the C 07.00 row-0110 population
    QCCP-cleared swap   the same swap faced to a QCCP, so the "of which:
                        centrally cleared through a QCCP" rows (0100/0120) have
                        something to report

**These goldens capture CURRENT behaviour, which is defective** — C 07.00 row
0110 is empty in both regimes, and under Basel 3.1 the derivatives are dropped
from C 07.00 entirely. That is deliberate: the goldens are a *snapshot*, not a
blessing. The fix's diff against them is the proof it works. See
``docs/plans/c07-ccr-derivatives.md`` (steps 3-6) — do not "correct" these
goldens by hand.

References:
- COREP Annex II, C 07.00 rows 0090-0130 (exposures subject to CCR; row 0110 =
  derivatives and long settlement transactions netting sets)
- CRR Art. 274(2) (SA-CCR EAD = alpha x (RC + PFE)); Art. 120(1) (institution RW)
- docs/plans/c07-ccr-derivatives.md
- docs/plans/phase7-declarative-reporting.md S8-pre (the missing CCR goldens)
"""

from __future__ import annotations

from datetime import date

import polars as pl

from rwa_calc.contracts.bundles import (
    CCRCollateralBundle,
    MarginAgreementBundle,
    NettingSetBundle,
    RawCCRBundle,
    RawDataBundle,
    TradeBundle,
)
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import (
    CCR_COLLATERAL_SCHEMA,
    COUNTERPARTY_SCHEMA,
    LOAN_SCHEMA,
    RATINGS_SCHEMA,
)
from tests.fixtures.ccr.margin_builder import create_margin_agreements
from tests.fixtures.ccr.netting_set_builder import create_netting_sets, make_netting_set
from tests.fixtures.ccr.trade_builder import create_trades, make_trade
from tests.fixtures.raw_bundle import make_raw_bundle

# ---------------------------------------------------------------------------
# Scenario constants — the single source of truth for test assertions.
# ---------------------------------------------------------------------------

CP_INST: str = "CP_CCR_INST"  # institution, CQS 2 -> 50% RW (Art. 120(1))
CP_QCCP: str = "CP_CCR_QCCP"  # qualifying CCP
CP_CORP: str = "CP_CCR_CORP"  # corporate, rated -> the plain SA loan

LN_CORP: str = "LN_CCR_CORP"
NS_BILATERAL: str = "NS_CCR_BILAT"  # faced to the institution
NS_CLEARED: str = "NS_CCR_QCCP"  # faced to the QCCP

_REPORTING_DATE: date = date(2025, 12, 31)


def build_reporting_ccr_bundle() -> RawDataBundle:
    """Assemble the CCR reporting portfolio as a sealed ``RawDataBundle``.

    Run through ``PipelineOrchestrator().run_with_data`` under either regime;
    the derivative rows surface as synthetic ``ccr__<netting_set_id>`` exposures
    carrying ``risk_type == "CCR_DERIVATIVE"``.
    """
    return make_raw_bundle(
        counterparties=_counterparties(),
        loans=_loans(),
        ratings=_ratings(),
        ccr=_ccr_bundle(),
    )


# ---------------------------------------------------------------------------
# Table builders (private)
# ---------------------------------------------------------------------------


def _counterparties() -> pl.DataFrame:
    """One institution (bilateral), one QCCP, one corporate (the plain loan)."""
    rows: list[dict] = [
        {"counterparty_reference": CP_INST, "entity_type": "institution", "country_code": "GB"},
        {"counterparty_reference": CP_QCCP, "entity_type": "ccp", "country_code": "GB"},
        {
            "counterparty_reference": CP_CORP,
            "entity_type": "corporate",
            "country_code": "GB",
            "annual_revenue": 100_000_000.0,
        },
    ]
    frame = pl.DataFrame(rows, schema_overrides=dtypes_of(COUNTERPARTY_SCHEMA))
    # ``is_qccp`` is not in the base counterparty schema — it rides as an
    # optional column (the p839 CCP fixture's convention). Only the CCP row is
    # a QCCP; null elsewhere means "not a CCP", never "non-qualifying".
    return frame.with_columns(
        pl.when(pl.col("counterparty_reference") == CP_QCCP)
        .then(pl.lit(value=True))
        .otherwise(pl.lit(None, dtype=pl.Boolean))
        .alias("is_qccp")
    )


def _loans() -> pl.DataFrame:
    """One drawn corporate loan — the ordinary SA exposure."""
    rows: list[dict] = [
        {
            "loan_reference": LN_CORP,
            "counterparty_reference": CP_CORP,
            "product_type": "term_loan",
            "drawn_amount": 5_000_000.0,
            "currency": "GBP",
            "value_date": date(2020, 1, 1),
            "maturity_date": date(2030, 12, 31),
        },
    ]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(LOAN_SCHEMA))


def _ratings() -> pl.DataFrame:
    """External ratings: institution CQS 2 (50% RW), corporate CQS 2 (50% RW)."""
    rows: list[dict] = [
        {
            "rating_reference": "RTG_CCR_INST",
            "counterparty_reference": CP_INST,
            "rating_type": "external",
            "rating_agency": "S&P",
            "rating_value": "A",
            "cqs": 2,
            "rating_date": _REPORTING_DATE,
        },
        {
            "rating_reference": "RTG_CCR_CORP",
            "counterparty_reference": CP_CORP,
            "rating_type": "external",
            "rating_agency": "S&P",
            "rating_value": "A",
            "cqs": 2,
            "rating_date": _REPORTING_DATE,
        },
    ]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(RATINGS_SCHEMA))


def _ccr_bundle() -> RawCCRBundle:
    """Two unmargined netting sets, one 10y GBP vanilla IR swap each.

    Identical trades faced to different counterparties, so the only difference
    in the templates is the QCCP treatment — which is exactly what rows
    0100/0120 ("of which: centrally cleared through a QCCP") disclose.
    """
    trades = create_trades(
        [
            make_trade(trade_id="T_CCR_BILAT", netting_set_id=NS_BILATERAL),
            make_trade(trade_id="T_CCR_QCCP", netting_set_id=NS_CLEARED),
        ]
    )
    netting_sets = create_netting_sets(
        [
            make_netting_set(netting_set_id=NS_BILATERAL, counterparty_reference=CP_INST),
            make_netting_set(netting_set_id=NS_CLEARED, counterparty_reference=CP_QCCP),
        ]
    )
    return RawCCRBundle(
        trades=TradeBundle(trades=trades.lazy()),
        netting_sets=NettingSetBundle(netting_sets=netting_sets.lazy()),
        margin_agreements=MarginAgreementBundle(
            margin_agreements=create_margin_agreements([]).lazy()
        ),
        ccr_collateral=CCRCollateralBundle(
            ccr_collateral=pl.DataFrame(schema=dtypes_of(CCR_COLLATERAL_SCHEMA)).lazy()
        ),
    )
