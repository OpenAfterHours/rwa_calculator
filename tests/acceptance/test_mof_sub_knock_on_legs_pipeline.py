"""Acceptance: the knock-on legs of pricing a MOF sub-limit as its own item, end to end (P1.452).

A sub-limit's own ``is_short_term_trade_lc`` reaches more than its conversion
factor. Every consumer of the flag reads it off the sub row, while the row's
DATES are still the umbrella's (held for the owner's decision). So wherever the
umbrella's dates satisfy a consumer's maturity test, a trade-LC sub-line now
reaches that consumer's trade-finance treatment. This file pins each such leg
with absolute, hand-calculated values, in both regimes, with the Basel 3.1
output floor (S-TREA). It also pins the one remaining Row 4(b) reducing leg: a
sub that states ``False`` under a flagged mortgage umbrella.

Rule text (verbatim):

- PS1/26 Art. 162(3): "In addition, ... for qualifying short-term exposures which
  are not part of the institution's ongoing financing of the obligor, M shall be
  at least one day, instead of the minimum set in paragraph 2A. Qualifying short
  term exposures shall include ... (e) self-liquidating trade finance
  transactions ... with a residual maturity of less than one year". CRR Art.
  162(3)(b) reads "with a residual maturity of up to one year". **This floor reads
  RESIDUAL maturity, so it fires on a trade-LC sub in the final year of ANY
  umbrella, whatever the umbrella's original term** (the ``PC`` leg below: a
  2023 umbrella).
- PS1/26 Art. 121(4): "Exposures to institutions for which a credit assessment by
  a nominated ECAI is not available, where the original maturity of the exposure
  was six months or less and the exposure arose from the movement of goods,
  shall be assigned a risk weight in accordance with Table 5A." The rated-
  institution ECRA short-term window carries the same six-month trade extension.
- PS1/26 Art. 121(6): the sovereign floor applies where "(b) the exposure is not a
  self-liquidating, trade-related contingent item arising from the movement of
  goods with an original maturity of less than one year".
- CRR Art. 166(8)(b): "for short-term letters of credit arising from the movement
  of goods, a conversion factor of 20 % shall apply".
- PS1/26 Table A1 row (4)(b): "UK residential mortgage commitments that are not
  subject to a conversion factor of 10% or 100%" - 50%; row (5) 40%.

The portfolio (every facility committed and in GBP, nothing drawn; each umbrella
has one 4m sub-limit and a 6m residual, except ``PM``). Dates are given for the
Basel 3.1 run (reporting date 2027-06-30); the CRR run (2026-06-30) shifts every
date one year earlier, so each one keeps its distance from the reporting date:

- ``PI``: institution with a nominated-ECAI CQS 2 rating. Umbrella 2027-04-01 to
  2027-08-20 (original 141 days, residual 51 days). ``PI_TLC`` is an ``MLR``
  trade-LC sub.
- ``PG``: unrated GB institution (SCRA grade A, sovereign CQS 1, GBP local).
  Same dates and sub as ``PI``.
- ``PU``: unrated BR institution (SCRA grade A, sovereign CQS 4, BRL local, so a
  GBP exposure is a foreign-currency one). Umbrella 2026-10-01 to 2027-07-28
  (original 300 days, residual 28 days), with a trade-LC sub ``PU_TLC``.
- ``PC``: unrated UK corporate. Umbrella 2023-01-01 to 2028-03-31 (residual 275
  days; 274 under CRR), with a trade-LC sub ``PC_TLC``.
- ``PM``: the same corporate, 10m umbrella flagged as a UK residential mortgage
  commitment, 2025-01-01 to 2031-06-30. ``PM_SILENT`` (3m) states nothing;
  ``PM_NOT`` (3m) states ``False``. Residual 4m.

Pre-fix (measured on the main tree) every sub row carried the umbrella's
``is_short_term_trade_lc`` False and Row 4(b) True. The changes:

- CRR F-IRB, trade-LC subs: CCF 75% to 20%, and M from the one-year floor to the
  residual maturity.
- Basel 3.1 F-IRB, trade-LC subs: M from 1.0 to the residual maturity.
- Basel 3.1 SA: ``PI_TLC`` 30% to 20%, ``PG_TLC`` 40% to 20%, ``PU_TLC`` 100% to
  40% (Art. 121(6) exemption), ``PM_NOT`` CCF 50% to 40%. S-TREA 13,640,000 to
  12,620,000.
- CRR SA, ``PG_TLC``: RWA-INCREASING, 20% to 100%. Art. 121(4) trade finance is
  held out of the Table 5 sovereign-derived ladder, an interim owned by P1.326 /
  P7.8.

The IRB risk weights are hand-calculated below with the Art. 153(1) formula: PD
1%, F-IRB LGD 45% (CRR; Basel 3.1 financial sector entity) or 40% (Basel 3.1
corporate), the CRR 1.06 scaling factor, and no SME or FSE correlation
adjustment. The CCFs and SA weights are the rulepack's: ``sa_ccf``,
``firb_trade_lc_ccf``, ``firb_credit_line_ccf``, ``b31_scra_short_term_risk_weights``
and the institution tables.
"""

from __future__ import annotations

from datetime import date
from functools import cache
from math import exp, log, sqrt
from statistics import NormalDist
from typing import Any

import polars as pl
import pytest

from rwa_calc.contracts.bundles import AggregatedResultBundle
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import COUNTERPARTY_SCHEMA, FACILITY_SCHEMA, LOAN_SCHEMA
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.fixtures.irb_test_helpers import create_firb_only_model_permissions
from tests.fixtures.raw_bundle import make_raw_bundle

_REPORTING = {"CRR": date(2026, 6, 30), "B31": date(2027, 6, 30)}
_YEAR_SHIFT = {"CRR": -1, "B31": 0}
_PD = 0.01

#: Residual maturity in days at each regime's reporting date - what the
#: Art. 162(3) one-day floor lets M fall to (``PC`` crosses 2028-02-29 under B31).
_RESIDUAL_DAYS = {
    "PI": {"CRR": 51, "B31": 51},
    "PG": {"CRR": 51, "B31": 51},
    "PU": {"CRR": 28, "B31": 28},
    "PC": {"CRR": 274, "B31": 275},
}
#: F-IRB senior unsecured LGD: CRR Art. 161(1)(a) 45%; PS1/26 Art. 161(1)(a)
#: 45% for a financial sector entity, (aa) 40% for any other corporate.
_FIRB_LGD = {
    "CRR": {"INST": 0.45, "CORP": 0.45},
    "B31": {"INST": 0.45, "CORP": 0.40},
}
#: CRR Art. 153(1) 1.06 scaling; removed by PS1/26.
_SCALING = {"CRR": 1.06, "B31": 1.0}


def _shift(day: date, regime: str) -> date:
    return date(day.year + _YEAR_SHIFT[regime], day.month, day.day)


def _facility(
    ref: str, counterparty: str, limit: float, start: date, end: date, **overrides: Any
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "facility_reference": ref,
        "product_type": "RCF",
        "book_code": "CORP",
        "counterparty_reference": counterparty,
        "value_date": start,
        "maturity_date": end,
        "currency": "GBP",
        "limit": limit,
        "committed": True,
        "seniority": "senior",
        "risk_type": "OC",
    }
    row.update(overrides)
    return row


def _facilities(regime: str) -> list[dict[str, Any]]:
    short = (_shift(date(2027, 4, 1), regime), _shift(date(2027, 8, 20), regime))
    nine_month = (_shift(date(2026, 10, 1), regime), _shift(date(2027, 7, 28), regime))
    final_year = (date(2023, 1, 1), _shift(date(2028, 3, 31), regime))
    long = (date(2025, 1, 1), date(2031, 6, 30))
    trade_lc = {"risk_type": "MLR", "is_short_term_trade_lc": True}
    return [
        _facility("PI", "INST", 10_000_000.0, *short),
        _facility("PI_TLC", "INST", 4_000_000.0, *short, **trade_lc),
        _facility("PG", "INST_GB", 10_000_000.0, *short),
        _facility("PG_TLC", "INST_GB", 4_000_000.0, *short, **trade_lc),
        _facility("PU", "INST_BR", 10_000_000.0, *nine_month),
        _facility("PU_TLC", "INST_BR", 4_000_000.0, *nine_month, **trade_lc),
        _facility("PC", "CORP", 10_000_000.0, *final_year),
        _facility("PC_TLC", "CORP", 4_000_000.0, *final_year, **trade_lc),
        _facility("PM", "CORP", 10_000_000.0, *long, is_uk_residential_mortgage_commitment=True),
        _facility("PM_SILENT", "CORP", 3_000_000.0, *long),
        _facility(
            "PM_NOT", "CORP", 3_000_000.0, *long, is_uk_residential_mortgage_commitment=False
        ),
    ]


_MAPPINGS = [
    {"parent_facility_reference": parent, "child_reference": child, "child_type": "facility"}
    for parent, child in (
        ("PI", "PI_TLC"),
        ("PG", "PG_TLC"),
        ("PU", "PU_TLC"),
        ("PC", "PC_TLC"),
        ("PM", "PM_SILENT"),
        ("PM", "PM_NOT"),
    )
]


def _institution(ref: str, country: str, **overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "counterparty_reference": ref,
        "counterparty_name": ref,
        "entity_type": "institution",
        "country_code": country,
        "annual_revenue": 1_000_000_000.0,
        "total_assets": 50_000_000_000.0,
        "default_status": False,
        "is_financial_sector_entity": True,
        "apply_fi_scalar": False,
    }
    row.update(overrides)
    return row


_COUNTERPARTIES = [
    {
        "counterparty_reference": "CORP",
        "counterparty_name": "CORP",
        "entity_type": "corporate",
        "country_code": "GB",
        "annual_revenue": 100_000_000.0,
        "total_assets": 500_000_000.0,
        "default_status": False,
        "is_financial_sector_entity": False,
        "apply_fi_scalar": False,
    },
    _institution("INST", "GB"),
    _institution("INST_GB", "GB", sovereign_cqs=1, local_currency="GBP", scra_grade="A"),
    _institution("INST_BR", "BR", sovereign_cqs=4, local_currency="BRL", scra_grade="A"),
]


def _ratings(regime: str, *, irb: bool) -> list[dict[str, Any]]:
    reporting = _REPORTING[regime]
    ratings: list[dict[str, Any]] = [
        {
            "rating_reference": "R_INST_EXT",
            "counterparty_reference": "INST",
            "rating_type": "external",
            "rating_agency": "Moody's",
            "cqs": 2,
            "pd": None,
            "model_id": None,
            "rating_date": reporting,
        }
    ]
    if irb:
        ratings += [
            {
                "rating_reference": f"R_{ref}_INT",
                "counterparty_reference": ref,
                "rating_type": "internal",
                "rating_agency": None,
                "cqs": None,
                "pd": _PD,
                "model_id": "TEST_FULL_IRB",
                "rating_date": reporting,
            }
            for ref in ("CORP", "INST", "INST_GB", "INST_BR")
        ]
    return ratings


@cache
def _run(regime: str, *, irb: bool) -> AggregatedResultBundle:
    mode = PermissionMode.IRB if irb else PermissionMode.STANDARDISED
    irb_inputs: dict[str, Any] = (
        {"model_permissions": create_firb_only_model_permissions()} if irb else {}
    )
    bundle = make_raw_bundle(
        facilities=pl.DataFrame(_facilities(regime), schema_overrides=dtypes_of(FACILITY_SCHEMA)),
        loans=pl.DataFrame(schema=dtypes_of(LOAN_SCHEMA)),
        counterparties=pl.DataFrame(
            _COUNTERPARTIES, schema_overrides=dtypes_of(COUNTERPARTY_SCHEMA)
        ),
        facility_mappings=pl.DataFrame(
            _MAPPINGS,
            schema={
                "parent_facility_reference": pl.String,
                "child_reference": pl.String,
                "child_type": pl.String,
            },
        ),
        ratings=pl.DataFrame(_ratings(regime, irb=irb)),
        **irb_inputs,
    )
    reporting = _REPORTING[regime]
    config = (
        CalculationConfig.crr(reporting_date=reporting, permission_mode=mode)
        if regime == "CRR"
        else CalculationConfig.basel_3_1(reporting_date=reporting, permission_mode=mode)
    )
    return PipelineOrchestrator().run_with_data(bundle, config)


def _row(regime: str, reference: str, *, irb: bool) -> dict[str, Any]:
    ledger = _run(regime, irb=irb).results.collect()
    rows = ledger.filter(pl.col("exposure_reference") == reference)
    assert rows.height == 1, (
        f"{regime}: expected one {reference} row, ledger has "
        f"{sorted(ledger['exposure_reference'].to_list())}"
    )
    return rows.row(0, named=True)


def _irb_rw(pd: float, lgd: float, maturity: float, scaling: float) -> float:
    """Art. 153(1) corporate / institution risk weight - an independent hand calculation."""
    normal = NormalDist()
    weight = (1 - exp(-50 * pd)) / (1 - exp(-50))
    correlation = 0.12 * weight + 0.24 * (1 - weight)
    b = (0.11852 - 0.05478 * log(pd)) ** 2
    conditional_pd = normal.cdf(
        (normal.inv_cdf(pd) + sqrt(correlation) * normal.inv_cdf(0.999)) / sqrt(1 - correlation)
    )
    k = lgd * (conditional_pd - pd) * (1 + (maturity - 2.5) * b) / (1 - 1.5 * b)
    return k * 12.5 * scaling


def _assert_sa(row: dict[str, Any], *, ccf: float, risk_weight: float, nominal: float) -> None:
    assert row["approach_applied"] == "standardised"
    assert row["ccf"] == pytest.approx(ccf)
    assert row["risk_weight"] == pytest.approx(risk_weight)
    assert row["rwa_final"] == pytest.approx(nominal * ccf * risk_weight)


# =============================================================================
# Art. 162(3): a trade-LC sub's M falls from the one-year floor to its residual
# maturity - in the final year of ANY umbrella, both regimes
# =============================================================================


@pytest.mark.parametrize("regime", ["CRR", "B31"])
@pytest.mark.parametrize(
    ("umbrella", "obligor"), [("PC", "CORP"), ("PI", "INST"), ("PG", "INST"), ("PU", "INST")]
)
def test_trade_lc_sub_takes_the_one_day_maturity_floor(
    regime: str, umbrella: str, obligor: str
) -> None:
    # Arrange - pre-fix every one of these rows had M = 1.0 (the floor).
    maturity = _RESIDUAL_DAYS[umbrella][regime] / 365.0
    expected_rw = _irb_rw(_PD, _FIRB_LGD[regime][obligor], maturity, _SCALING[regime])

    # Act
    row = _row(regime, f"{umbrella}_UNDRAWN_{umbrella}_TLC", irb=True)

    # Assert - 4m x 20% (CRR Art. 166(8)(b); Basel 3.1 Table A1 row (6)(a)).
    assert row["approach_applied"] == "foundation_irb", "fixture adequacy: F-IRB route"
    assert row["ccf"] == pytest.approx(0.20)
    assert row["irb_maturity_m"] == pytest.approx(maturity)
    assert row["risk_weight"] == pytest.approx(expected_rw, rel=1e-6)
    assert row["rwa_final"] == pytest.approx(800_000.0 * expected_rw, rel=1e-6)


@pytest.mark.parametrize("regime", ["CRR", "B31"])
def test_umbrella_residual_keeps_the_one_year_floor(regime: str) -> None:
    # Control: the same umbrella's residual is not a trade LC - M stays 1.0.
    row = _row(regime, "PC_UNDRAWN_RESIDUAL", irb=True)

    assert row["irb_maturity_m"] == pytest.approx(1.0)
    assert row["risk_weight"] == pytest.approx(
        _irb_rw(_PD, _FIRB_LGD[regime]["CORP"], 1.0, _SCALING[regime]), rel=1e-6
    )


# =============================================================================
# Basel 3.1 SA: the six-month trade window and the Art. 121(6) exemption
# =============================================================================


class TestB31StandardisedTradeWindows:
    """Each sub row against its umbrella's residual, which is not a trade LC."""

    def test_rated_institution_trade_lc_takes_the_short_term_weight(self) -> None:
        # ECRA CQS 2: short-term 20% on an original maturity of 141 days, up to
        # six months for a trade LC (30% pre-fix, the long-term weight).
        _assert_sa(
            _row("B31", "PI_UNDRAWN_PI_TLC", irb=False),
            ccf=0.20,
            risk_weight=0.20,
            nominal=4_000_000.0,
        )
        _assert_sa(
            _row("B31", "PI_UNDRAWN_RESIDUAL", irb=False),
            ccf=0.40,
            risk_weight=0.30,
            nominal=6_000_000.0,
        )

    def test_unrated_institution_trade_lc_takes_table_5a(self) -> None:
        # Art. 121(4) Table 5A grade A 20% (40% pre-fix, the Table 5 grade A weight).
        _assert_sa(
            _row("B31", "PG_UNDRAWN_PG_TLC", irb=False),
            ccf=0.20,
            risk_weight=0.20,
            nominal=4_000_000.0,
        )
        _assert_sa(
            _row("B31", "PG_UNDRAWN_RESIDUAL", irb=False),
            ccf=0.40,
            risk_weight=0.40,
            nominal=6_000_000.0,
        )

    def test_foreign_currency_trade_lc_is_exempt_from_the_sovereign_floor(self) -> None:
        # Art. 121(6)(b): an original maturity of 300 days (over the six-month
        # Table 5A window) - grade A 40%, not the sovereign's 100% (pre-fix).
        _assert_sa(
            _row("B31", "PU_UNDRAWN_PU_TLC", irb=False),
            ccf=0.20,
            risk_weight=0.40,
            nominal=4_000_000.0,
        )
        _assert_sa(
            _row("B31", "PU_UNDRAWN_RESIDUAL", irb=False),
            ccf=0.40,
            risk_weight=1.00,
            nominal=6_000_000.0,
        )

    def test_corporate_trade_lc_weight_is_unmoved(self) -> None:
        # Control: no trade window reaches an unrated corporate.
        _assert_sa(
            _row("B31", "PC_UNDRAWN_PC_TLC", irb=False),
            ccf=0.20,
            risk_weight=1.00,
            nominal=4_000_000.0,
        )


class TestB31ResidentialMortgageSubs:
    """Row (4)(b) under a flagged umbrella: the sub's own statement, else the umbrella's True."""

    @pytest.mark.parametrize("irb", [False, True])
    def test_silent_sub_stays_on_row_4b(self, irb: bool) -> None:
        # Guard: 3,000,000 x 50%, as before the fix.
        row = _row("B31", "PM_UNDRAWN_PM_SILENT", irb=irb)
        assert row["ccf"] == pytest.approx(0.50)
        assert row["ead_final"] == pytest.approx(1_500_000.0)

    @pytest.mark.parametrize("irb", [False, True])
    def test_sub_stating_false_takes_row_5(self, irb: bool) -> None:
        # RWA-REDUCING: 3,000,000 x 40% (50% pre-fix, the umbrella's flag).
        row = _row("B31", "PM_UNDRAWN_PM_NOT", irb=irb)
        assert row["ccf"] == pytest.approx(0.40)
        assert row["ead_final"] == pytest.approx(1_200_000.0)


class TestB31OutputFloor:
    """S-TREA is the SA-equivalent of the F-IRB rows: it follows every SA leg above."""

    # sa_rwa per row - EAD (CCF x nominal) x SA weight:
    #   PI: 0.8m x 20% + 2.4m x 30%      =   160,000 +   720,000
    #   PG: 0.8m x 20% + 2.4m x 40%      =   160,000 +   960,000
    #   PU: 0.8m x 40% + 2.4m x 100%     =   320,000 + 2,400,000
    #   PC: 0.8m x 100% + 2.4m x 100%    =   800,000 + 2,400,000
    #   PM: 1.5m + 1.2m + 2.0m (x 100%)  = 4,700,000
    # 12,620,000 (13,640,000 pre-fix: PI_TLC +80,000, PG_TLC +160,000,
    # PU_TLC +480,000, PM_NOT +300,000).
    _S_TREA = 12_620_000.0

    def test_s_trea(self) -> None:
        summary = _run("B31", irb=True).output_floor_summary
        assert summary is not None
        assert summary.s_trea == pytest.approx(self._S_TREA)

    def test_s_trea_equals_the_standardised_run(self) -> None:
        # Every row's SA-equivalent is its SA-run RWA (no 166A(5) row here).
        sa_total = _run("B31", irb=False).results.collect()["rwa_final"].sum()
        assert sa_total == pytest.approx(self._S_TREA)

    def test_floor_threshold_and_post_floor_total(self) -> None:
        summary = _run("B31", irb=True).output_floor_summary
        assert summary is not None
        assert summary.floor_threshold == pytest.approx(
            summary.floor_pct * self._S_TREA + summary.of_adj
        )
        assert summary.portfolio_floor_binding is False
        assert summary.total_rwa_post_floor == pytest.approx(summary.u_trea)


# =============================================================================
# CRR SA: no six-month trade window; Art. 121(4) holds trade finance out of Table 5
# =============================================================================


class TestCrrStandardisedTradeLegs:
    def test_rated_institution_trade_lc_weight_is_unmoved(self) -> None:
        # Table 3 CQS 2 50% - CRR has no trade extension of the short-term window.
        _assert_sa(
            _row("CRR", "PI_UNDRAWN_PI_TLC", irb=False),
            ccf=0.20,
            risk_weight=0.50,
            nominal=4_000_000.0,
        )

    def test_unrated_institution_trade_lc_leaves_the_sovereign_ladder(self) -> None:
        # RWA-INCREASING: the Art. 121(4) interim 100% residual (P1.326 / P7.8),
        # not Table 5 sovereign CQS 1 20% (pre-fix) - which the residual keeps.
        _assert_sa(
            _row("CRR", "PG_UNDRAWN_PG_TLC", irb=False),
            ccf=0.20,
            risk_weight=1.00,
            nominal=4_000_000.0,
        )
        _assert_sa(
            _row("CRR", "PG_UNDRAWN_RESIDUAL", irb=False),
            ccf=0.20,
            risk_weight=0.20,
            nominal=6_000_000.0,
        )

    def test_residential_flag_is_inert(self) -> None:
        # Table A1 Row 4(b) has no CRR equivalent: every PM row is OC 50%.
        for reference, nominal in (("PM_UNDRAWN_PM_SILENT", 3e6), ("PM_UNDRAWN_PM_NOT", 3e6)):
            _assert_sa(
                _row("CRR", reference, irb=False), ccf=0.50, risk_weight=1.00, nominal=nominal
            )
