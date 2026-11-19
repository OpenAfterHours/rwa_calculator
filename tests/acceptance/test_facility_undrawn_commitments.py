"""Acceptance: facility undrawn commitments priced end to end, both regimes.

Review findings closed here (product review 2026-11-18, "undrawn" cluster):

- **CM-01** - ``committed=False`` silently deleted an accepted unconditionally
  cancellable (UCC) commitment. PS1/26 Glossary "commitment": "means any
  off-balance sheet contractual arrangement that has been offered by the
  institution and accepted by the obligor ... This includes but is not limited
  to any such arrangement that may be: (1) unconditionally cancelled by the
  institution at any time without prior notice to the obligor". PS1/26 Art. 111
  Table A1 row (7): "Undrawn commitments which may be cancelled unconditionally
  at any time without notice ..." - 10%. CRR Annex I 4(a) puts the same line in
  "Low risk" (0%), so the CRR row appears at EAD 0 and CRR RWA does not move.
- **SF-02** - committed sub-facilities under an uncommitted umbrella inherited
  the umbrella's flag and were dropped. A committed sub-line is a commitment:
  exposure value = nominal value x CF (CRR Art. 111(1); PS1/26 Art. 111(1)(b)).
- **CM-02 / SF-01** - headroom netted drawings in other currencies before FX
  conversion. CRR Art. 4(1)(56) / PS1/26 Glossary "conversion factor": "... the
  currently undrawn amount of the commitment from that facility, the extent of
  the commitment being determined by the advised limit" - a subtraction that is
  only meaningful in one currency.
- **CM-11 / SF-12** - a facility with a null limit emitted nothing and said
  nothing. Now HIE006; no number moves (the engine cannot invent the limit).

Every expectation is a hand calculation, not a captured output. The obligor is
an unrated, non-SME UK corporate, so SA RW = 100% in both regimes and RWA = EAD.
CCFs (``sa_ccf``, ``resolve(regime, date)``): CRR ``OC`` 50% for an original
maturity above one year, ``LR`` 0%; Basel 3.1 ``OC`` 40%, ``LR`` 10%.
"""

from __future__ import annotations

from datetime import date
from functools import cache
from typing import Any

import polars as pl
import pytest

from rwa_calc.contracts.bundles import AggregatedResultBundle
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.contracts.errors import (
    ERROR_FACILITY_HEADROOM_FX_RATE_MISSING,
    ERROR_FACILITY_LIMIT_MISSING,
    ERROR_UNCOMMITTED_FACILITY_RISK_TYPE,
)
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import (
    COUNTERPARTY_SCHEMA,
    FACILITY_SCHEMA,
    FX_RATES_SCHEMA,
    LOAN_SCHEMA,
)
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.fixtures.raw_bundle import make_raw_bundle

_VALUE = date(2025, 1, 1)
_MATURITY = date(2031, 6, 30)
_REGIMES = ("CRR", "B31")

#: Basel 3.1 / CRR CCFs used in the hand calculations, by risk type.
_CCF = {"CRR": {"OC": 0.50, "LR": 0.0}, "B31": {"OC": 0.40, "LR": 0.10}}


def _config(regime: str) -> CalculationConfig:
    if regime == "CRR":
        return CalculationConfig.crr(reporting_date=date(2026, 6, 30))
    return CalculationConfig.basel_3_1(reporting_date=date(2027, 6, 30))


def _facility(ref: str, limit: float | None, **overrides: Any) -> dict[str, Any]:
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
        "is_revolving": True,
    }
    row.update(overrides)
    return row


def _loan(ref: str, drawn: float, currency: str = "GBP") -> dict[str, Any]:
    return {
        "loan_reference": ref,
        "product_type": "RCF_DRAWING",
        "book_code": "CORP",
        "counterparty_reference": "CORP_A",
        "value_date": _VALUE,
        "maturity_date": _MATURITY,
        "currency": currency,
        "drawn_amount": drawn,
        "interest": 0.0,
        "seniority": "senior",
    }


def _map(parent: str, child: str, child_type: str = "loan") -> dict[str, str]:
    return {"parent_facility_reference": parent, "child_reference": child, "child_type": child_type}


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

#: Each case is (facilities, loans, mappings, fx rates to GBP).
_CASES: dict[str, tuple[list, list, list, list[tuple[str, float]] | None]] = {
    "ucc_lr": ([_facility("F_UCC", 10_000_000.0, committed=False, risk_type="LR")], [], [], None),
    "ucc_mr": ([_facility("F_UCC", 10_000_000.0, committed=False, risk_type="MR")], [], [], None),
    "umbrella": (
        [
            _facility("P", 30_000_000.0, committed=False, risk_type="LR"),
            _facility("S1", 10_000_000.0),
            _facility("S2", 10_000_000.0),
        ],
        [_loan("L1", 2_000_000.0), _loan("L2", 2_000_000.0)],
        [
            _map("P", "S1", "facility"),
            _map("P", "S2", "facility"),
            _map("S1", "L1"),
            _map("S2", "L2"),
        ],
        None,
    ),
    "eur": (
        [_facility("F_GBP", 10_000_000.0)],
        [_loan("L_EUR", 5_000_000.0, "EUR")],
        [_map("F_GBP", "L_EUR")],
        [("EUR", 0.85)],
    ),
    "jpy": (
        [_facility("F_GBP", 10_000_000.0)],
        [_loan("L_JPY", 1_000_000_000.0, "JPY")],
        [_map("F_GBP", "L_JPY")],
        [("JPY", 0.005)],
    ),
    "usd_no_rate": (
        [_facility("F_GBP", 10_000_000.0)],
        [_loan("L_USD", 6_500_000.0, "USD")],
        [_map("F_GBP", "L_USD")],
        [("EUR", 0.85)],
    ),
    "null_limit": (
        [_facility("F_NOLIMIT", None)],
        [_loan("L1", 2_000_000.0)],
        [_map("F_NOLIMIT", "L1")],
        None,
    ),
}


@cache
def _run(case: str, regime: str) -> AggregatedResultBundle:
    facilities, loans, mappings, fx = _CASES[case]
    kwargs: dict[str, Any] = {}
    if fx is not None:
        kwargs["fx_rates"] = pl.DataFrame(
            {
                "currency_from": [c for c, _ in fx],
                "currency_to": ["GBP"] * len(fx),
                "rate": [r for _, r in fx],
            },
            schema=dtypes_of(FX_RATES_SCHEMA),
        )
    bundle = make_raw_bundle(
        facilities=pl.DataFrame(facilities, schema_overrides=dtypes_of(FACILITY_SCHEMA)),
        loans=(
            pl.DataFrame(loans, schema_overrides=dtypes_of(LOAN_SCHEMA))
            if loans
            else pl.DataFrame(schema=dtypes_of(LOAN_SCHEMA))
        ),
        counterparties=pl.DataFrame(
            [_COUNTERPARTY], schema_overrides=dtypes_of(COUNTERPARTY_SCHEMA)
        ),
        facility_mappings=pl.DataFrame(
            mappings,
            schema={
                "parent_facility_reference": pl.String,
                "child_reference": pl.String,
                "child_type": pl.String,
            },
        ),
        **kwargs,
    )
    return PipelineOrchestrator().run_with_data(bundle, _config(regime))


def _ledger(case: str, regime: str) -> pl.DataFrame:
    return _run(case, regime).results.collect()


def _row(case: str, regime: str, reference: str) -> dict[str, Any]:
    ledger = _ledger(case, regime)
    rows = ledger.filter(pl.col("exposure_reference") == reference)
    assert rows.height == 1, (
        f"{case}/{regime}: expected one {reference} row, ledger has "
        f"{sorted(ledger['exposure_reference'].to_list())}"
    )
    return rows.row(0, named=True)


def _codes(case: str, regime: str, code: str) -> list[Any]:
    return [e for e in _run(case, regime).errors if e.code == code]


def _assert_money(row: dict[str, Any], ead: float) -> None:
    assert row["risk_weight"] == pytest.approx(1.0), "fixture adequacy: unrated corporate is 100%"
    assert row["ead_final"] == pytest.approx(ead)
    assert row["rwa_final"] == pytest.approx(ead)


@pytest.mark.parametrize("regime", _REGIMES)
class TestUccCommitment:
    """CM-01: an accepted UCC line is a Table A1 row (7) / Annex I 4(a) commitment."""

    def test_uncommitted_line_is_priced_in_the_ucc_bucket(self, regime: str) -> None:
        # B31: 10,000,000 x 10% = 1,000,000. CRR: 10,000,000 x 0% = 0 (row present).
        row = _row("ucc_lr", regime, "F_UCC_UNDRAWN")

        assert row["nominal_amount"] == pytest.approx(10_000_000.0)
        assert row["ccf"] == pytest.approx(_CCF[regime]["LR"])
        _assert_money(row, 10_000_000.0 * _CCF[regime]["LR"])

    def test_contradictory_risk_type_is_overridden_and_reported(self, regime: str) -> None:
        row = _row("ucc_mr", regime, "F_UCC_UNDRAWN")

        assert row["ccf"] == pytest.approx(_CCF[regime]["LR"])
        _assert_money(row, 10_000_000.0 * _CCF[regime]["LR"])
        found = _codes("ucc_mr", regime, ERROR_UNCOMMITTED_FACILITY_RISK_TYPE)
        assert [e.exposure_reference for e in found] == ["F_UCC"]

    def test_documented_ucc_encoding_raises_no_hie004(self, regime: str) -> None:
        assert _codes("ucc_lr", regime, ERROR_UNCOMMITTED_FACILITY_RISK_TYPE) == []


@pytest.mark.parametrize("regime", _REGIMES)
class TestCommittedSubsUnderUncommittedUmbrella:
    """SF-02: P 30m committed=False; S1 / S2 committed OC 10m, 2m drawn on each."""

    @pytest.mark.parametrize("sub", ["P_UNDRAWN_S1", "P_UNDRAWN_S2"])
    def test_each_committed_sub_line_carries_its_own_headroom(self, regime: str, sub: str) -> None:
        # 8,000,000 x OC: CRR 4,000,000, B31 3,200,000 (both lost entirely before).
        row = _row("umbrella", regime, sub)

        assert row["nominal_amount"] == pytest.approx(8_000_000.0)
        _assert_money(row, 8_000_000.0 * _CCF[regime]["OC"])

    def test_umbrella_residual_is_ucc(self, regime: str) -> None:
        # 30 - 4 drawn - 16 allocated = 10,000,000 in the LR bucket.
        row = _row("umbrella", regime, "P_UNDRAWN_RESIDUAL")

        assert row["nominal_amount"] == pytest.approx(10_000_000.0)
        _assert_money(row, 10_000_000.0 * _CCF[regime]["LR"])

    def test_book_total(self, regime: str) -> None:
        # Drawn 4,000,000 + 16,000,000 x OC + 10,000,000 x LR.
        expected = 4_000_000.0 + 16_000_000.0 * _CCF[regime]["OC"] + 1e7 * _CCF[regime]["LR"]

        assert _ledger("umbrella", regime)["rwa_final"].sum() == pytest.approx(expected)


@pytest.mark.parametrize("regime", _REGIMES)
class TestMultiCurrencyHeadroom:
    """CM-02 / SF-01: utilisation is converted into the facility currency first."""

    def test_eur_drawing_fixture_adequacy_rate_applied(self, regime: str) -> None:
        # EUR 5,000,000 x 0.85 = GBP 4,250,000 on the loan itself.
        assert _row("eur", regime, "L_EUR")["drawn_amount"] == pytest.approx(4_250_000.0)

    def test_eur_drawing_leaves_gbp_5_75m_undrawn(self, regime: str) -> None:
        # 10,000,000 - 4,250,000 = 5,750,000 (raw netting gave 5,000,000).
        # CRR 5.75m x 50% = 2,875,000; B31 5.75m x 40% = 2,300,000.
        row = _row("eur", regime, "F_GBP_UNDRAWN")

        assert row["nominal_amount"] == pytest.approx(5_750_000.0)
        _assert_money(row, 5_750_000.0 * _CCF[regime]["OC"])

    def test_jpy_drawing_no_longer_deletes_the_commitment(self, regime: str) -> None:
        # JPY 1,000,000,000 x 0.005 = GBP 5,000,000; undrawn 5,000,000 (row was absent).
        row = _row("jpy", regime, "F_GBP_UNDRAWN")

        assert row["nominal_amount"] == pytest.approx(5_000_000.0)
        _assert_money(row, 5_000_000.0 * _CCF[regime]["OC"])

    def test_unconvertible_drawing_is_not_netted_and_is_reported(self, regime: str) -> None:
        # No USD rate: the 6.5m is not netted, so the whole 10m limit is undrawn.
        row = _row("usd_no_rate", regime, "F_GBP_UNDRAWN")

        assert row["nominal_amount"] == pytest.approx(10_000_000.0)
        _assert_money(row, 10_000_000.0 * _CCF[regime]["OC"])
        found = _codes("usd_no_rate", regime, ERROR_FACILITY_HEADROOM_FX_RATE_MISSING)
        assert [(e.exposure_reference, e.actual_value) for e in found] == [("F_GBP", "USD")]

    def test_convertible_drawing_raises_no_hie005(self, regime: str) -> None:
        assert _codes("eur", regime, ERROR_FACILITY_HEADROOM_FX_RATE_MISSING) == []


@pytest.mark.parametrize("regime", _REGIMES)
class TestNullLimit:
    """CM-11 / SF-12: a facility with no limit is reported, and nothing is invented."""

    def test_null_limit_raises_exactly_one_hie006(self, regime: str) -> None:
        found = _codes("null_limit", regime, ERROR_FACILITY_LIMIT_MISSING)

        assert [e.exposure_reference for e in found] == ["F_NOLIMIT"]

    def test_null_limit_moves_no_number(self, regime: str) -> None:
        ledger = _ledger("null_limit", regime)

        assert ledger["exposure_reference"].to_list() == ["L1"]
        assert ledger["rwa_final"].sum() == pytest.approx(2_000_000.0)
