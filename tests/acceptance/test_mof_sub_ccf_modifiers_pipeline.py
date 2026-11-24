"""Acceptance: a Multiple Option Facility's sub-limits priced as their own items, end to end (P1.452).

The unit sibling (``tests/unit/test_mof_sub_ccf_modifiers.py``) pins what each
waterfall row carries; this file pins the money once the real pipeline prices
it, in both regimes, on the Standardised and the Foundation IRB approach.

Rule text (verbatim):

- PS1/26 Art. 111(1)(b): an off-balance-sheet item's exposure value is "the
  product of: (i) its nominal value ... and (ii) the applicable conversion factor
  (the percentage specified in the corresponding row of Column B)"; (c) "a
  commitment to issue an off-balance sheet item ... using the lower of" the
  factor of the item to be issued and that of the commitment.
- PS1/26 Table A1 row (4)(b) "UK residential mortgage commitments that are not
  subject to a conversion factor of 10% or 100%" 50%; row (5) "Any other
  commitment ..." 40%; row (6)(a) documentary credits 20%.
- CRR Art. 166(8)(b): "for short-term letters of credit arising from the
  movement of goods, a conversion factor of 20 % shall apply"; (8)(d) "for other
  credit lines ... a conversion factor of 75 % shall apply".

The portfolio - one unrated, non-SME UK corporate (SA RW 100% in both regimes,
so SA RWA = EAD), nothing drawn, every facility committed with a 2025-01-01 to
2031-06-30 term (original maturity above one year):

- ``P`` (20m, ``OC``) over ``SUB_LC`` (4m, ``OC``, underlying ``MLR``),
  ``SUB_RESI`` (4m, ``OC``, Row 4(b) flag), ``SUB_TLC`` (4m, ``MLR``, trade LC)
  and ``SUB_DC`` (4m, no risk type, ``obs_product`` ``DOCUMENTARY_CREDIT``).
  The subs total 16m, so no slice is rationed and the residual is 4m.
- ``P2`` (10m, ``OC``, underlying ``MLR``) over ``SUB_CASH`` (4m, plain ``OC``):
  residual 6m.

CCFs are the rulepack's (``sa_ccf``, ``firb_*_ccf``, ``resolve(regime, date)``).
Every figure below is a hand calculation.

Pre-fix (measured on the main tree): B31 SA EAD 9,200,000 (SUB_LC 40%,
SUB_RESI 40%, SUB_CASH 20%, no SUB_DC row - its 4m sat in the residual at 40%);
CRR F-IRB SUB_TLC 75% (EAD 3,000,000) and total EAD 22,500,000.

**RWA-reducing legs, signed off (P1.452 brief):** the B31 commitment to issue an
LC (40% -> 20%), the B31 documentary-credit sub that now gets its own row (in
the residual at 40% -> 20%), the CRR F-IRB trade LC (75% -> 20%). They lower
the Basel 3.1 S-TREA with the modelled figure, because the SA-equivalent of an
IRB row IS the Table A1 factor (PS1/26 Art. 166C(1)); the floor is pinned below.
Every umbrella here runs to 2031, so no maturity-conditioned leg can fire. The
trade-LC flag's knock-on legs (the SA six-month trade windows, the Art. 121(6)
exemption, and the Art. 162(3) one-day M floor, which reads RESIDUAL maturity
and so fires in the final year of any umbrella) and the Row 4(b) sub that states
``False`` under a flagged umbrella are pinned, with S-TREA, in
``test_mof_sub_knock_on_legs_pipeline.py``.
"""

from __future__ import annotations

from datetime import date
from functools import cache
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

_VALUE = date(2025, 1, 1)
_MATURITY = date(2031, 6, 30)
_REGIMES = ("CRR", "B31")

#: OF-ADJ (PS1/26 Art. 92(2A)) on this portfolio: no provisions, so the IRB EL
#: shortfall is a CET1 deduction - -12.5 x (PD 1% x F-IRB LGD 40% x EAD 8.8m).
_B31_OF_ADJ = -12.5 * 0.01 * 0.40 * 8_800_000.0


def _facility(ref: str, limit: float, **overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "facility_reference": ref,
        "product_type": "RCF",
        "book_code": "CORP",
        "counterparty_reference": "CORP_A",
        "value_date": _VALUE,
        "maturity_date": _MATURITY,
        "currency": "GBP",
        "limit": limit,
        "committed": True,
        "seniority": "senior",
        "risk_type": "OC",
    }
    row.update(overrides)
    return row


_FACILITIES = [
    _facility("P", 20_000_000.0),
    _facility("SUB_LC", 4_000_000.0, underlying_risk_type="MLR"),
    _facility("SUB_RESI", 4_000_000.0, is_uk_residential_mortgage_commitment=True),
    _facility("SUB_TLC", 4_000_000.0, risk_type="MLR", is_short_term_trade_lc=True),
    _facility("SUB_DC", 4_000_000.0, risk_type=None, obs_product="DOCUMENTARY_CREDIT"),
    _facility("P2", 10_000_000.0, underlying_risk_type="MLR"),
    _facility("SUB_CASH", 4_000_000.0),
]
_MAPPINGS = [
    {"parent_facility_reference": parent, "child_reference": child, "child_type": "facility"}
    for parent, child in (
        ("P", "SUB_LC"),
        ("P", "SUB_RESI"),
        ("P", "SUB_TLC"),
        ("P", "SUB_DC"),
        ("P2", "SUB_CASH"),
    )
]
_COUNTERPARTY = {
    "counterparty_reference": "CORP_A",
    "counterparty_name": "Corp A",
    "entity_type": "corporate",
    "country_code": "GB",
    "annual_revenue": 100_000_000.0,
    "total_assets": 500_000_000.0,
    "default_status": False,
    "is_financial_sector_entity": False,
    "apply_fi_scalar": False,
}
_RATING = {
    "rating_reference": "RTG_CORP_A",
    "counterparty_reference": "CORP_A",
    "rating_type": "internal",
    "pd": 0.01,
    "model_id": "TEST_FULL_IRB",
    "rating_date": _VALUE,
}


def _config(regime: str, *, irb: bool) -> CalculationConfig:
    mode = PermissionMode.IRB if irb else PermissionMode.STANDARDISED
    if regime == "CRR":
        return CalculationConfig.crr(reporting_date=date(2026, 6, 30), permission_mode=mode)
    return CalculationConfig.basel_3_1(reporting_date=date(2027, 6, 30), permission_mode=mode)


@cache
def _run(regime: str, *, irb: bool) -> AggregatedResultBundle:
    irb_inputs: dict[str, Any] = (
        {
            "ratings": pl.DataFrame([_RATING]),
            "model_permissions": create_firb_only_model_permissions(),
        }
        if irb
        else {}
    )
    bundle = make_raw_bundle(
        facilities=pl.DataFrame(_FACILITIES, schema_overrides=dtypes_of(FACILITY_SCHEMA)),
        loans=pl.DataFrame(schema=dtypes_of(LOAN_SCHEMA)),
        counterparties=pl.DataFrame(
            [_COUNTERPARTY], schema_overrides=dtypes_of(COUNTERPARTY_SCHEMA)
        ),
        facility_mappings=pl.DataFrame(
            _MAPPINGS,
            schema={
                "parent_facility_reference": pl.String,
                "child_reference": pl.String,
                "child_type": pl.String,
            },
        ),
        **irb_inputs,
    )
    return PipelineOrchestrator().run_with_data(bundle, _config(regime, irb=irb))


def _ledger(regime: str, *, irb: bool) -> pl.DataFrame:
    return _run(regime, irb=irb).results.collect()


def _row(regime: str, reference: str, *, irb: bool = False) -> dict[str, Any]:
    ledger = _ledger(regime, irb=irb)
    rows = ledger.filter(pl.col("exposure_reference") == reference)
    assert rows.height == 1, (
        f"{regime}: expected one {reference} row, ledger has "
        f"{sorted(ledger['exposure_reference'].to_list())}"
    )
    return rows.row(0, named=True)


def _assert_sa_money(row: dict[str, Any], ccf: float, nominal: float) -> None:
    assert row["risk_weight"] == pytest.approx(1.0), "fixture adequacy: unrated corporate is 100%"
    assert row["ccf"] == pytest.approx(ccf)
    assert row["ead_final"] == pytest.approx(nominal * ccf)
    assert row["rwa_final"] == pytest.approx(nominal * ccf)


# =============================================================================
# Standardised Approach
# =============================================================================


class TestB31StandardisedSubLimits:
    """Basel 3.1 SA: each sub-limit on its own Table A1 row."""

    def test_commitment_to_issue_an_lc_takes_the_lower_of(self) -> None:
        # Art. 111(1)(c): 4,000,000 x min(40%, 20%) = 800,000.
        _assert_sa_money(_row("B31", "P_UNDRAWN_SUB_LC"), 0.20, 4_000_000.0)

    def test_residential_mortgage_commitment_takes_row_4b(self) -> None:
        # Row (4)(b): 4,000,000 x 50% = 2,000,000.
        _assert_sa_money(_row("B31", "P_UNDRAWN_SUB_RESI"), 0.50, 4_000_000.0)

    def test_cash_sub_under_an_lc_tagged_umbrella_takes_row_5(self) -> None:
        # Row (5): 4,000,000 x 40% = 1,600,000 - not the umbrella's 20% cap.
        _assert_sa_money(_row("B31", "P2_UNDRAWN_SUB_CASH"), 0.40, 4_000_000.0)

    def test_documentary_credit_sub_gets_its_own_row(self) -> None:
        # Row (6)(a): 4,000,000 x 20% = 800,000, out of the umbrella's residual.
        row = _row("B31", "P_UNDRAWN_SUB_DC")
        assert row["risk_type"] == "MLR"
        _assert_sa_money(row, 0.20, 4_000_000.0)

    def test_umbrella_residuals_keep_the_umbrellas_terms(self) -> None:
        # P: 4,000,000 x row 5 40%; P2: 6,000,000 x min(40%, 20%) - its own cap.
        _assert_sa_money(_row("B31", "P_UNDRAWN_RESIDUAL"), 0.40, 4_000_000.0)
        _assert_sa_money(_row("B31", "P2_UNDRAWN_RESIDUAL"), 0.20, 6_000_000.0)

    def test_portfolio_ead(self) -> None:
        # 0.8 + 2.0 + 0.8 (SUB_TLC, row 6) + 0.8 + 1.6 + 1.6 + 1.2 = 8.8m (9.2m pre-fix).
        assert _ledger("B31", irb=False)["ead_final"].sum() == pytest.approx(8_800_000.0)


class TestCrrStandardisedSubLimits:
    """CRR SA: Annex I has no lower-of and no Row 4(b), so only the DC sub moves rows."""

    def test_documentary_credit_sub_gets_its_own_row(self) -> None:
        # CRR obs_product map: plain documentary credit = Annex I 2(a) medium risk, 50%.
        row = _row("CRR", "P_UNDRAWN_SUB_DC")
        assert row["risk_type"] == "MR_ISSUED"
        _assert_sa_money(row, 0.50, 4_000_000.0)

    def test_umbrella_residual_no_longer_carries_the_dc_sub(self) -> None:
        _assert_sa_money(_row("CRR", "P_UNDRAWN_RESIDUAL"), 0.50, 4_000_000.0)

    def test_lower_of_and_row_4b_stay_inert(self) -> None:
        # P1.265: the commitment-to-issue cap and Table A1 Row 4(b) are Basel 3.1 only.
        _assert_sa_money(_row("CRR", "P_UNDRAWN_SUB_LC"), 0.50, 4_000_000.0)
        _assert_sa_money(_row("CRR", "P_UNDRAWN_SUB_RESI"), 0.50, 4_000_000.0)
        _assert_sa_money(_row("CRR", "P2_UNDRAWN_SUB_CASH"), 0.50, 4_000_000.0)

    def test_trade_lc_flag_leaves_the_corporate_sa_weight_alone(self) -> None:
        # The flag now reaches the row; for a corporate obligor it moves no weight.
        _assert_sa_money(_row("CRR", "P_UNDRAWN_SUB_TLC"), 0.20, 4_000_000.0)

    def test_portfolio_ead(self) -> None:
        # 2.0 x 4 (LC, RESI, DC, P residual) + 0.8 + 2.0 + 3.0 = 13.8m, as pre-fix:
        # the DC sub's 50% equals the OC residual's it left.
        assert _ledger("CRR", irb=False)["ead_final"].sum() == pytest.approx(13_800_000.0)


# =============================================================================
# Foundation IRB
# =============================================================================


@pytest.mark.parametrize("regime", _REGIMES)
def test_firb_trade_lc_sub_keeps_the_umbrellas_maturity_and_weight(regime: str) -> None:
    """Long-umbrella control: here the trade-LC flag moves the CCF only.

    The sub row carries the umbrella's dates (held for the owner), and this
    umbrella runs to 2031: its residual maturity is over a year, so the Art.
    162(3) one-day floor - which reads the trade-LC flag and RESIDUAL maturity -
    cannot fire, and M and RW match the umbrella residual. In the final year of
    ANY umbrella it does fire; that leg is pinned in
    ``test_mof_sub_knock_on_legs_pipeline.py``.
    """
    sub = _row(regime, "P_UNDRAWN_SUB_TLC", irb=True)
    residual = _row(regime, "P_UNDRAWN_RESIDUAL", irb=True)

    assert sub["approach_applied"] == "foundation_irb", "fixture adequacy: F-IRB route"
    assert sub["irb_maturity_m"] == pytest.approx(residual["irb_maturity_m"])
    assert sub["risk_weight"] == pytest.approx(residual["risk_weight"])


class TestCrrFoundationIrbSubLimits:
    def test_short_term_trade_lc_sub_takes_166_8_b(self) -> None:
        # Art. 166(8)(b): 4,000,000 x 20% = 800,000 (the 166(8)(d) 75% pre-fix).
        row = _row("CRR", "P_UNDRAWN_SUB_TLC", irb=True)
        assert row["ccf"] == pytest.approx(0.20)
        assert row["ead_final"] == pytest.approx(800_000.0)

    def test_portfolio_ead(self) -> None:
        # Art. 166(8)(d) 75% on the 26m of credit lines (LC, RESI, DC, CASH 4m each,
        # residuals 4m + 6m) = 19.5m, plus the trade LC's 4m x 20% = 0.8m:
        # 20.3m (22.5m pre-fix, with the trade LC at 75%).
        assert _ledger("CRR", irb=True)["ead_final"].sum() == pytest.approx(20_300_000.0)


class TestB31FoundationIrbOutputFloor:
    """Basel 3.1 F-IRB: Art. 166C(1) prices the row at its Table A1 factor, and the
    output floor's SA-equivalent is that same factor - so the floor follows it."""

    def test_commitment_to_issue_an_lc_takes_the_lower_of(self) -> None:
        row = _row("B31", "P_UNDRAWN_SUB_LC", irb=True)
        assert row["ccf"] == pytest.approx(0.20)
        assert row["ead_final"] == pytest.approx(800_000.0)

    def test_s_trea_is_the_table_a1_sa_equivalent(self) -> None:
        # Every row is 100% SA-weighted: S-TREA = the SA EAD of 8.8m (9.2m pre-fix).
        summary = _run("B31", irb=True).output_floor_summary
        assert summary is not None
        assert summary.s_trea == pytest.approx(8_800_000.0)
        # x * S-TREA + OF-ADJ (the threshold is not 55% of S-TREA: 55% is only
        # 60% less this portfolio's EL shortfall, OF-ADJ = -5% of its EAD).
        assert summary.of_adj == pytest.approx(_B31_OF_ADJ)
        assert summary.floor_threshold == pytest.approx(
            summary.floor_pct * 8_800_000.0 + _B31_OF_ADJ
        )

    def test_floor_does_not_bind_and_post_floor_total_is_the_modelled_one(self) -> None:
        summary = _run("B31", irb=True).output_floor_summary
        assert summary is not None
        assert summary.portfolio_floor_binding is False
        assert summary.total_rwa_post_floor == pytest.approx(summary.u_trea)
        assert summary.u_trea == pytest.approx(_ledger("B31", irb=True)["rwa_final"].sum())
