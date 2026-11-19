"""
Review CC-06 through the real pipeline: incomplete SA-CCR trade inputs are priced
conservatively AND reported, never silently zeroed — both regimes.

Pipeline position:
    RawDataBundle -> input gate (CCR021-CCR023) -> ccr_sa_ccr stage
    (map_trade_risk_categories / attach_orphan_trade_netting_sets) -> SA calculator

Key responsibilities:
- A credit trade with no credit_quality, a commodity trade with no
  commodity_type, a trade with an unrecognised asset_class and a trade whose
  netting set is missing each produce a non-zero, hand-calculated EAD and a
  row-named CCR error, under current UK CRR and under Basel 3.1.
- A casing variant of a recognised asset class is priced exactly like the
  canonical value and raises nothing (the input gate is case-insensitive).

Rule text (CRR / CCR (CRR) Part, unchanged by PS1/26):
- Art. 277(1): "Institutions shall map each transaction of a netting set to one
  of the following risk categories ... (f) other risks."
- Art. 278(1): the add-on of a risk category is included "where at least one
  transaction of the netting set has been mapped to that risk category".
- Art. 280f(2): "SF Other = ... 8%". Art. 280 Table: credit single-name
  non-rated 6%, commodity electricity 40%.
- Art. 274(1): "Where any of the conditions ... are not met, the institution
  shall treat each transaction as if it was its own netting set."

Defect pinned (measured pre-fix through PipelineOrchestrator, both regimes):
null credit_quality -> ead_ccr 0; null commodity_type -> 0; asset_class
'weather' -> 0; 'Interest_Rate' -> 0; orphan trade -> no row at all; and no
error of any kind for any of them.

Hand calculation (GBP 10m, start = reporting date, 5y maturity, MtM 0, so
RC = 0, PFE multiplier 1, MF = 1, alpha 1.4; SD(S, E) per Art. 279b(1)(a) with
S floored at 0.04y):
    CRR  (2026-03-31 -> 2031-03-31): SD = 4.383491243
    B31  (2027-03-31 -> 2032-03-31): SD = 4.385623410
    credit, null quality -> NON_RATED 6%:  AddOn = 0.06 × 10m × SD
        CRR 2,630,094.746 -> EAD 3,682,132.644; B31 2,631,374.046 -> EAD 3,683,923.664
    commodity, null type -> ELECTRICITY 40% (d = 100 × 100,000 = 10m):
        AddOn = 0.40 × 10m = 4,000,000 -> EAD 5,600,000 (both regimes)
    asset_class 'weather' -> other risks 8%, d = 10m × max(1, SD):
        CRR 3,506,792.994 -> EAD 4,909,510.192; B31 3,508,498.728 -> EAD 4,911,898.219
    interest rate (also 'Interest_Rate'): AddOn = 0.005 × 10m × SD
        CRR 219,174.562 -> EAD 306,844.387; B31 219,281.171 -> EAD 306,993.639
    orphan IR trade: its own netting set, same EAD as the IR line, no counterparty.

References:
    - CRR Art. 274(1), 277(1), 278(1), 279b(1)(a)/(c)/(d), 280, 280f
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.bundles import (
    CCRCollateralBundle,
    MarginAgreementBundle,
    NettingSetBundle,
    RawCCRBundle,
    RawDataBundle,
    TradeBundle,
)
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import (
    CCR_COLLATERAL_SCHEMA,
    COUNTERPARTY_SCHEMA,
    FACILITY_MAPPING_SCHEMA,
    FACILITY_SCHEMA,
    LENDING_MAPPING_SCHEMA,
    LOAN_SCHEMA,
    RATINGS_SCHEMA,
)
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.fixtures.ccr.margin_builder import create_margin_agreements
from tests.fixtures.ccr.netting_set_builder import create_netting_sets, make_netting_set
from tests.fixtures.ccr.trade_builder import create_trades, make_trade
from tests.fixtures.raw_bundle import make_raw_bundle

_NOTIONAL = 10_000_000.0

_DATES = {
    "crr": (date(2026, 3, 31), date(2031, 3, 31)),
    "b31": (date(2027, 3, 31), date(2032, 3, 31)),
}

#: (scenario, regime) -> (addon_aggregate, ead_ccr) — module docstring.
_EXPECTED = {
    ("credit_null_quality", "crr"): (2_630_094.7456, 3_682_132.6439),
    ("credit_null_quality", "b31"): (2_631_374.0460, 3_683_923.6645),
    ("commodity_null_type", "crr"): (4_000_000.0, 5_600_000.0),
    ("commodity_null_type", "b31"): (4_000_000.0, 5_600_000.0),
    ("unknown_asset_class", "crr"): (3_506_792.9942, 4_909_510.1918),
    ("unknown_asset_class", "b31"): (3_508_498.7281, 4_911_898.2193),
    ("ir_casing_variant", "crr"): (219_174.5621, 306_844.3870),
    ("ir_casing_variant", "b31"): (219_281.1705, 306_993.6387),
}

#: scenario -> (trade overrides, expected CCR error code or None)
_SCENARIOS = {
    "credit_null_quality": (
        {"asset_class": "credit", "reference_entity": "R1", "is_index": False},
        ("CCR022", "credit_quality"),
    ),
    "commodity_null_type": (
        {"asset_class": "commodity", "market_price": 100.0, "number_of_units": 100_000.0},
        ("CCR022", "commodity_type"),
    ),
    "unknown_asset_class": ({"asset_class": "weather"}, ("CCR021", "asset_class")),
    "ir_casing_variant": ({"asset_class": "Interest_Rate"}, None),
}

_CCR_CODES = {"CCR021", "CCR022", "CCR023"}


def _config(regime: str) -> CalculationConfig:
    factory = CalculationConfig.crr if regime == "crr" else CalculationConfig.basel_3_1
    return factory(reporting_date=_DATES[regime][0], permission_mode=PermissionMode.STANDARDISED)


def _bundle(regime: str, trades: list[dict]) -> RawDataBundle:
    start, maturity = _DATES[regime]
    counterparty = pl.DataFrame(
        [
            {
                "counterparty_reference": "CP-FIN",
                "counterparty_name": "Financial counterparty",
                "entity_type": "institution",
                "country_code": "GB",
                "default_status": False,
                "counterparty_type": "financial",
            }
        ],
        schema=dtypes_of(COUNTERPARTY_SCHEMA),
    )
    trade_frame = create_trades(
        [
            make_trade(
                netting_set_id=t.pop("netting_set_id", "NS1"),
                notional=_NOTIONAL,
                start_date=start,
                maturity_date=maturity,
                **t,
            )
            for t in trades
        ]
    )
    netting_sets = create_netting_sets(
        [
            make_netting_set(
                netting_set_id="NS1", counterparty_reference="CP-FIN", is_legally_enforceable=True
            )
        ]
    )
    return make_raw_bundle(
        counterparties=counterparty.lazy(),
        facilities=pl.LazyFrame(schema=dtypes_of(FACILITY_SCHEMA)),
        loans=pl.LazyFrame(schema=dtypes_of(LOAN_SCHEMA)),
        facility_mappings=pl.LazyFrame(schema=dtypes_of(FACILITY_MAPPING_SCHEMA)),
        lending_mappings=pl.LazyFrame(schema=dtypes_of(LENDING_MAPPING_SCHEMA)),
        ratings=pl.LazyFrame(schema=dtypes_of(RATINGS_SCHEMA)),
        ccr=RawCCRBundle(
            trades=TradeBundle(trades=trade_frame.lazy()),
            netting_sets=NettingSetBundle(netting_sets=netting_sets.lazy()),
            margin_agreements=MarginAgreementBundle(
                margin_agreements=create_margin_agreements([]).lazy()
            ),
            ccr_collateral=CCRCollateralBundle(
                ccr_collateral=pl.LazyFrame(schema=dtypes_of(CCR_COLLATERAL_SCHEMA))
            ),
        ),
    )


def _run(regime: str, trades: list[dict]):
    result = PipelineOrchestrator().run_with_data(_bundle(regime, trades), _config(regime))
    rows = (
        result.results.collect()
        .filter(pl.col("exposure_reference").str.starts_with("ccr__"))
        .to_dicts()
    )
    return {row["exposure_reference"]: row for row in rows}, result.errors


@pytest.mark.parametrize("regime", ["crr", "b31"])
@pytest.mark.parametrize("scenario", list(_SCENARIOS))
def test_incomplete_input_is_priced_conservatively_and_reported(scenario: str, regime: str) -> None:
    """Hand-calculated non-zero EAD, plus exactly one row-named CCR error naming the trade."""
    # Arrange
    overrides, expected_error = _SCENARIOS[scenario]
    expected_addon, expected_ead = _EXPECTED[scenario, regime]

    # Act
    rows, errors = _run(regime, [{"trade_id": "T1", **overrides}])

    # Assert — the number
    row = rows["ccr__NS1"]
    assert row["addon_aggregate"] == pytest.approx(expected_addon, rel=1e-9)
    assert row["ead_ccr"] == pytest.approx(expected_ead, rel=1e-9), (
        f"{scenario}/{regime}: ead_ccr {row['ead_ccr']:,.2f}; 0 is the pre-CC-06 silent zero"
    )
    assert row["rwa_final"] == pytest.approx(row["ead_final"] * row["risk_weight"], rel=1e-9)

    # Assert — the error (or its absence for a recognised casing variant)
    ccr_errors = [e for e in errors if e.code in _CCR_CODES]
    if expected_error is None:
        assert ccr_errors == []
        return
    code, field = expected_error
    assert [(e.code, e.field_name) for e in ccr_errors] == [(code, field)]
    assert "trade 'T1'" in ccr_errors[0].message
    assert ccr_errors[0].severity.value == "error"


@pytest.mark.parametrize("regime", ["crr", "b31"])
def test_orphan_trade_is_priced_alone_and_reported(regime: str) -> None:
    """A trade naming a missing netting set gets its own row (no counterparty) + CCR023."""
    # Arrange
    _, ir_ead = _EXPECTED["ir_casing_variant", regime]
    trades = [
        {"trade_id": "T1", "asset_class": "interest_rate"},
        {"trade_id": "T2", "asset_class": "interest_rate", "netting_set_id": "NS-MISSING"},
    ]

    # Act
    rows, errors = _run(regime, trades)

    # Assert — both trades priced; the orphan alone, with no obligor
    orphan = rows["ccr__NS-MISSING__split__T2"]
    assert rows["ccr__NS1"]["ead_ccr"] == pytest.approx(ir_ead, rel=1e-9)
    assert orphan["ead_ccr"] == pytest.approx(ir_ead, rel=1e-9)
    assert orphan["counterparty_reference"] is None
    assert orphan["alpha_applied"] == 1.4
    assert orphan["rwa_final"] == pytest.approx(orphan["ead_final"], rel=1e-9)  # 100% RW

    # Assert — reported, row-named
    ccr023 = [e for e in errors if e.code == "CCR023"]
    assert len(ccr023) == 1
    assert "trade 'T2'" in ccr023[0].message


@pytest.mark.parametrize("regime", ["crr", "b31"])
def test_null_quality_credit_equals_explicit_non_rated_leg(regime: str) -> None:
    """Relational pin: the null-quality fallback EAD equals an explicit NON_RATED trade's."""
    # Arrange
    credit = {"asset_class": "credit", "reference_entity": "R1", "is_index": False}

    # Act
    null_rows, _ = _run(regime, [{"trade_id": "T1", **credit}])
    nr_rows, nr_errors = _run(regime, [{"trade_id": "T1", **credit, "credit_quality": "NON_RATED"}])

    # Assert
    assert null_rows["ccr__NS1"]["ead_ccr"] == pytest.approx(
        nr_rows["ccr__NS1"]["ead_ccr"], rel=1e-12
    )
    assert [e for e in nr_errors if e.code in _CCR_CODES] == []
