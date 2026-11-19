"""TR-01 through the real pipeline: one trade-LC facility must not flag a counterparty's other loans.

Pipeline position:
    RawDataBundle -> PipelineOrchestrator -> AggregatedResultBundle (both regimes)

Scenario (identical shape in both regimes): one counterparty holds a trade-LC
facility (``is_short_term_trade_lc=True``) with one loan drawn under it, plus a
second loan of the same tenor booked under NO facility. Only the first loan
"arose from the movement of goods"; the second is ordinary lending.

Rule text (verbatim):
    PS1/26 Art. 121(4) (Basel 3.1): "Exposures to institutions for which a credit
    assessment by a nominated ECAI is not available, where the original maturity
    of the exposure was six months or less and the exposure arose from the
    movement of goods, shall be assigned a risk weight in accordance with Table
    5A."
    CRR Art. 162(3) (CRR): "In addition, for qualifying short-term exposures
    which are not part of the institution's ongoing financing of the obligor, M
    shall be at least one-day. Qualifying short term exposures shall include the
    following: ... (b) self-liquidating short-term trade finance transactions
    connected to the exchange of goods or services with a residual maturity of up
    to one year as referred to in point (80) of Article 4(1)".

Hand calculations:
    Basel 3.1 SA, unrated SCRA Grade A bank, GBP 1,000,000 each, original
    maturity 150 days (0.4110y: above the 3-month Table 5A window, inside the
    six-month Art. 121(4) trade window):
        trade loan       RW 20% (Table 5A Grade A)   RWA 200,000
        standalone loan  RW 40% (Table 5 Grade A)    RWA 400,000   (pre-fix 200,000)

    CRR F-IRB, corporate (turnover GBP 500m, no SME adjustment), PD 0.40%,
    supervisory LGD 45%, GBP 1,000,000 each, residual 273 days (0.7479y):
        standalone loan  Art. 162(2) floor -> M = 1.0
                         R = 0.12*A + 0.24*(1-A), A = (1-e^-0.2)/(1-e^-50)
                         RWA = LGD*(N(...)-PD)*MA(M=1)*12.5*1.06*EAD = 488,072.96
                         (pre-fix: the leaked flag set the one-day floor)
        trade loan       carries the Art. 162(3) one-day floor flag

    CRR SA, unrated bank whose central government is CQS 1, 11.5-month loans
    (RWA-REDUCING for the standalone loan, which is correct): CRR Art. 121(1)
    "Exposures to institutions for which a credit assessment by a nominated ECAI
    is not available shall be assigned a risk weight in accordance with the
    credit quality step to which exposures to the central government ... are
    assigned in accordance with Table 5" (CQS 1 -> 20%). Art. 121(4) reaches only
    "trade finance exposures referred to in point (b) of the second subparagraph
    of Article 162(3)", which the engine holds out of the Table 5 ladder at the
    100% residual while P1.326 / P7.8 settle the 50% / 20% reading
    (``sovereign_derived.crr_art_121_4_trade_finance_expr``):
        trade loan       RW 100% (held out)          RWA 1,000,000
        standalone loan  RW 20% (Table 5 CQS 1)      RWA   200,000   (pre-fix
                         the leaked flag held it out too: 100%, 1,000,000)

    The figures are re-derived with ``tests/oracle/derivations/formulas.py``,
    which imports nothing from ``rwa_calc``.
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig, PermissionMode
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import (
    COUNTERPARTY_SCHEMA,
    FACILITY_MAPPING_SCHEMA,
    FACILITY_SCHEMA,
    LOAN_SCHEMA,
    RATINGS_SCHEMA,
)
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.fixtures.irb_test_helpers import create_full_irb_model_permissions
from tests.fixtures.raw_bundle import make_raw_bundle
from tests.oracle.derivations import formulas as oracle

_CP = "CP_TR01"
_FAC = "FAC_TR01_TRADE_LC"
_TRADE_LOAN = "LN_TR01_UNDER_TRADE_LC"
_OTHER_LOAN = "LN_TR01_STANDALONE"
_EAD = 1_000_000.0


def _bundle(
    *,
    entity_type: str,
    value_date: date,
    maturity_date: date,
    irb: bool,
    sovereign_cqs: int | None = None,
):
    """One trade-LC facility with one mapped loan, plus one standalone loan."""
    cp_row = {
        "counterparty_reference": _CP,
        "counterparty_name": "TR-01 counterparty",
        "entity_type": entity_type,
        "country_code": "GB",
        "default_status": False,
        "scra_grade": "A",
        "annual_revenue": 500_000_000.0,
    }
    if sovereign_cqs is not None:
        cp_row |= {"sovereign_cqs": sovereign_cqs, "local_currency": "GBP"}
    counterparties = pl.DataFrame([cp_row], schema_overrides=dtypes_of(COUNTERPARTY_SCHEMA))
    facilities = pl.DataFrame(
        [
            {
                "facility_reference": _FAC,
                "counterparty_reference": _CP,
                "value_date": value_date,
                "maturity_date": maturity_date,
                "currency": "GBP",
                "limit": _EAD,
                "committed": True,
                "risk_type": "MLR",
                "is_short_term_trade_lc": True,
            }
        ],
        schema_overrides=dtypes_of(FACILITY_SCHEMA),
    )
    loans = pl.DataFrame(
        [
            {
                "loan_reference": ref,
                "counterparty_reference": _CP,
                "value_date": value_date,
                "maturity_date": maturity_date,
                "currency": "GBP",
                "drawn_amount": _EAD,
                "interest": 0.0,
                "seniority": "senior",
            }
            for ref in (_TRADE_LOAN, _OTHER_LOAN)
        ],
        schema_overrides=dtypes_of(LOAN_SCHEMA),
    )
    facility_mappings = pl.DataFrame(
        [{"parent_facility_reference": _FAC, "child_reference": _TRADE_LOAN, "child_type": "loan"}],
        schema_overrides=dtypes_of(FACILITY_MAPPING_SCHEMA),
    )
    kwargs: dict = {
        "counterparties": counterparties,
        "facilities": facilities,
        "loans": loans,
        "facility_mappings": facility_mappings,
    }
    if irb:
        kwargs["ratings"] = pl.DataFrame(
            [
                {
                    "rating_reference": "RTG_TR01",
                    "counterparty_reference": _CP,
                    "rating_type": "internal",
                    "pd": 0.004,
                    "rating_date": value_date,
                    "model_id": "TEST_FULL_IRB",
                }
            ],
            schema_overrides=dtypes_of(RATINGS_SCHEMA),
        )
        kwargs["model_permissions"] = create_full_irb_model_permissions()
    return make_raw_bundle(**kwargs)


def _rows(bundle, config) -> dict[str, dict]:
    result = PipelineOrchestrator().run_with_data(bundle, config)
    df = result.results.collect()
    return {r["exposure_reference"]: r for r in df.to_dicts()}


@pytest.fixture(scope="module")
def b31_sa_rows() -> dict[str, dict]:
    """Basel 3.1 SA: unrated SCRA Grade A bank, 150-day original maturity."""
    config = CalculationConfig.basel_3_1(
        reporting_date=date(2027, 1, 31), permission_mode=PermissionMode.STANDARDISED
    )
    bundle = _bundle(
        entity_type="bank",
        value_date=date(2027, 1, 15),
        maturity_date=date(2027, 6, 14),
        irb=False,
    )
    return _rows(bundle, config)


@pytest.fixture(scope="module")
def crr_sa_rows() -> dict[str, dict]:
    """CRR SA: unrated bank, central government CQS 1, 350-day loans."""
    config = CalculationConfig.crr(
        reporting_date=date(2026, 12, 31), permission_mode=PermissionMode.STANDARDISED
    )
    bundle = _bundle(
        entity_type="bank",
        value_date=date(2026, 12, 15),
        maturity_date=date(2027, 11, 30),
        irb=False,
        sovereign_cqs=1,
    )
    return _rows(bundle, config)


@pytest.fixture(scope="module")
def crr_firb_rows() -> dict[str, dict]:
    """CRR F-IRB: large corporate, 273-day residual maturity."""
    config = CalculationConfig.crr(
        reporting_date=date(2026, 12, 31), permission_mode=PermissionMode.IRB
    )
    bundle = _bundle(
        entity_type="corporate",
        value_date=date(2026, 12, 31),
        maturity_date=date(2027, 9, 30),
        irb=True,
    )
    return _rows(bundle, config)


class TestBasel31SAShortTermTradeWindow:
    """PS1/26 Art. 121(4): the six-month window is for the trade exposure only."""

    def test_trade_loan_takes_table_5a_grade_a(self, b31_sa_rows: dict[str, dict]) -> None:
        """The loan drawn under the trade-LC facility keeps the 20% (P1.128 intent)."""
        row = b31_sa_rows[_TRADE_LOAN]

        assert row["risk_weight"] == pytest.approx(0.20, abs=1e-12)
        assert row["rwa_final"] == pytest.approx(200_000.0, abs=0.01)

    def test_standalone_loan_takes_long_term_grade_a(self, b31_sa_rows: dict[str, dict]) -> None:
        """Pre-fix the counterparty broadcast gave this ordinary loan 20% too."""
        row = b31_sa_rows[_OTHER_LOAN]

        assert row["ead_final"] == pytest.approx(_EAD, abs=0.01)
        assert row["risk_weight"] == pytest.approx(0.40, abs=1e-12), (
            "a loan under no facility took the Art. 121(4) trade window through the "
            "counterparty-level broadcast of a sibling facility's trade-LC flag"
        )
        assert row["rwa_final"] == pytest.approx(400_000.0, abs=0.01)


class TestCrrSATradeFinanceHoldOut:
    """CRR Art. 121(4) holds out trade finance only; other lending is Art. 121(1)."""

    def test_trade_loan_is_held_out_of_the_table_5_ladder(
        self, crr_sa_rows: dict[str, dict]
    ) -> None:
        """The loan under the trade-LC facility keeps the P1.316 hold-out (100%)."""
        row = crr_sa_rows[_TRADE_LOAN]

        assert row["is_short_term_trade_lc"] is True
        assert row["risk_weight"] == pytest.approx(1.0, abs=1e-12)

    def test_standalone_loan_takes_table_5_cqs_1(self, crr_sa_rows: dict[str, dict]) -> None:
        """Pre-fix the leaked flag held this ordinary loan out of Table 5 too."""
        row = crr_sa_rows[_OTHER_LOAN]

        assert row["is_short_term_trade_lc"] is False
        assert row["risk_weight"] == pytest.approx(0.20, abs=1e-12)
        assert row["rwa_final"] == pytest.approx(200_000.0, abs=0.01)


class TestCrrFirbOneDayMaturityFloor:
    """CRR Art. 162(3)(b): the one-day M floor is for the trade transaction only."""

    def test_standalone_loan_keeps_the_one_year_floor(self, crr_firb_rows: dict[str, dict]) -> None:
        """M = 1.0 (Art. 162(2) floor) and the hand-derived Art. 153(1) RWA."""
        row = crr_firb_rows[_OTHER_LOAN]
        expected_rw = oracle.irb_risk_weight_corporate(
            pd_value=0.004,
            lgd=0.45,
            maturity=1.0,
            correlation=oracle.correlation_corporate(0.004),
            scaling_factor=oracle.CRR_IRB_SCALING_FACTOR,
        )

        assert row["approach_applied"] == "foundation_irb"
        assert row["has_one_day_maturity_floor"] is False
        assert row["maturity"] == pytest.approx(1.0, abs=1e-12)
        assert row["rwa_final"] == pytest.approx(expected_rw * _EAD, abs=0.01)
        assert row["rwa_final"] == pytest.approx(488_072.96, abs=0.01)

    def test_trade_loan_carries_the_one_day_floor(self, crr_firb_rows: dict[str, dict]) -> None:
        """The loan under the trade-LC facility is the Art. 162(3)(b) population."""
        row = crr_firb_rows[_TRADE_LOAN]

        assert row["has_one_day_maturity_floor"] is True
