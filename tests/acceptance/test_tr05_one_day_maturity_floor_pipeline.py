"""TR-05 / TR-11 through the real pipeline: the Art. 162(3) one-day M floor, both regimes.

Pipeline position:
    RawDataBundle -> PipelineOrchestrator -> AggregatedResultBundle (IRB rows)

Two defects, one rung of the maturity chain (``irb/transforms.py::_build_maturity_exprs``):

- TR-05 (Basel 3.1, RWA overstated): the ``one_day_maturity_floor`` Feature was OFF
  in the Basel 3.1 pack, so a self-liquidating trade item kept the 1-year M floor.
- TR-11 (both regimes, RWA understated; surfaced by the TR-05 verifier and a
  precondition of enabling TR-05 safely): where the floor applied, the engine SET
  M to exactly one day (1/365) whatever the residual maturity, instead of using
  the residual maturity with a one-day MINIMUM.

Rule text (verbatim):
    PS1/26 Art. 162(3), second subparagraph (Basel 3.1): "In addition, in applying
    the calculation methods set out in paragraph 2A for qualifying short-term
    exposures which are not part of the institution's ongoing financing of the
    obligor, M shall be at least one day, instead of the minimum set in paragraph
    2A. Qualifying short term exposures shall include the following: ... (e)
    self-liquidating trade finance transactions, as set out in point (80) of
    Article 4(1) of CRR, with a residual maturity of less than one year;"
    CRR Art. 162(3), second subparagraph (CRR): "In addition, for qualifying
    short-term exposures which are not part of the institution's ongoing
    financing of the obligor, M shall be at least one-day. Qualifying short term
    exposures shall include the following: ... (b) self-liquidating short-term
    trade finance transactions connected to the exchange of goods or services
    with a residual maturity of up to one year as referred to in point (80) of
    Article 4(1);"

    "at least one day" is a MINIMUM on M, replacing the one-year minimum of
    Art. 162(2) / 162(2A); it is not a fixed value. The residual-maturity
    condition is regime-specific: Basel 3.1 "less than one year" (strict), CRR
    "up to one year" (inclusive).

Scenario: a large corporate (turnover GBP 500m, no SME adjustment), internal PD
0.40%, F-IRB supervisory LGD (B31 40% non-FSE senior, Art. 161(1)(aa); CRR 45%),
documentary-credit contingents of GBP 1,000,000 at the 20% trade CCF, so EAD
200,000 each.

Hand calculations (``tests/oracle/derivations/formulas.py``, no ``rwa_calc`` import):
    Residual 182 days -> M = 182/365 = 0.498630y
      B31 flagged     RW 0.359748  RWA (pre-floor)  71,949.68   (pre-fix M 1.0: 81,857.10)
      B31 not flagged RW 0.409286  RWA (pre-floor)  81,857.10   (M 1.0, unchanged)
      CRR flagged     RW 0.429000  RWA              85,800.00   (pre-fix M 1/365: 74,114.53)
    Residual exactly 365 days -> 1.0y
      B31 flagged     NOT qualifying ("less than one year") -> flag False, M 1.0
      CRR flagged     qualifying ("up to one year") -> flag True, M = max(1 day, 1.0) = 1.0
                      RWA 97,614.59   (pre-fix M 1/365: 74,114.53)

Revolving trade facility (Basel 3.1): a 90-day drawing of GBP 1,000,000 under a
revolving trade-LC facility terminating in exactly 3.0y. PS1/26 Art. 162(2A)(k):
"for revolving exposures, M shall be determined using the maximum contractual
termination date of the facility. An institution shall not use the repayment date
of the current drawing." Art. 162(3) only replaces that method's MINIMUM, so
M = max(1 day, 3.0) = 3.0, RW 0.606892, RWA (pre-floor) 606,892.43 — the same as
before TR-05 enabled the floor. (The first TR-05 / TR-11 cut priced the drawing on
its own 90-day repayment date: M 0.2466, RWA 334,844.54.)
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig, PermissionMode
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import (
    CONTINGENTS_SCHEMA,
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

_PD = 0.004
_EAD = 200_000.0  # GBP 1,000,000 nominal x 20% trade-LC CCF
_M_182_DAYS = 182 / 365

_B31_REPORTING_DATE = date(2027, 1, 31)
_CRR_REPORTING_DATE = date(2026, 12, 31)


def _rw(*, lgd: float, maturity: float, scaling: float) -> float:
    return oracle.irb_risk_weight_corporate(
        pd_value=_PD,
        lgd=lgd,
        maturity=maturity,
        correlation=oracle.correlation_corporate(_PD),
        scaling_factor=scaling,
    )


def _run(config: CalculationConfig, reporting_date: date, items) -> dict[str, dict]:
    """Run documentary-credit contingents for one large corporate through the pipeline."""
    counterparties = pl.DataFrame(
        [
            {
                "counterparty_reference": "CP_TR05",
                "counterparty_name": "TR-05 importer",
                "entity_type": "corporate",
                "country_code": "GB",
                "default_status": False,
                "annual_revenue": 500_000_000.0,
            }
        ],
        schema_overrides=dtypes_of(COUNTERPARTY_SCHEMA),
    )
    ratings = pl.DataFrame(
        [
            {
                "rating_reference": "RTG_TR05",
                "counterparty_reference": "CP_TR05",
                "rating_type": "internal",
                "pd": _PD,
                "rating_date": reporting_date,
                "model_id": "TEST_FULL_IRB",
            }
        ],
        schema_overrides=dtypes_of(RATINGS_SCHEMA),
    )
    contingents = pl.DataFrame(
        [
            {
                "contingent_reference": ref,
                "counterparty_reference": "CP_TR05",
                "value_date": reporting_date,
                "maturity_date": maturity_date,
                "currency": "GBP",
                "nominal_amount": 1_000_000.0,
                "risk_type": "MLR",
                "is_short_term_trade_lc": is_trade,
            }
            for ref, maturity_date, is_trade in items
        ],
        schema_overrides=dtypes_of(CONTINGENTS_SCHEMA),
    )
    bundle = make_raw_bundle(
        counterparties=counterparties,
        contingents=contingents,
        ratings=ratings,
        model_permissions=create_full_irb_model_permissions(),
    )
    df = PipelineOrchestrator().run_with_data(bundle, config).results.collect()
    return {r["exposure_reference"]: r for r in df.to_dicts()}


@pytest.fixture(scope="module")
def b31_rows() -> dict[str, dict]:
    config = CalculationConfig.basel_3_1(
        reporting_date=_B31_REPORTING_DATE, permission_mode=PermissionMode.IRB
    )
    return _run(
        config,
        _B31_REPORTING_DATE,
        [
            ("DC_182D_TRADE", date(2027, 8, 1), True),
            ("DC_182D_NOT_TRADE", date(2027, 8, 1), False),
            ("DC_365D_TRADE", date(2028, 1, 31), True),
        ],
    )


@pytest.fixture(scope="module")
def crr_rows() -> dict[str, dict]:
    config = CalculationConfig.crr(
        reporting_date=_CRR_REPORTING_DATE, permission_mode=PermissionMode.IRB
    )
    return _run(
        config,
        _CRR_REPORTING_DATE,
        [
            ("DC_182D_TRADE", date(2027, 7, 1), True),
            ("DC_365D_TRADE", date(2027, 12, 31), True),
        ],
    )


class TestBasel31Art1623e:
    """PS1/26 Art. 162(3)(e): enabled, as a floor, with a strict one-year bound."""

    def test_adequacy_rows_are_foundation_irb_at_the_trade_ccf(
        self, b31_rows: dict[str, dict]
    ) -> None:
        """The scenario only means something on an F-IRB row with EAD 200,000."""
        for row in b31_rows.values():
            assert row["approach_applied"] == "foundation_irb"
            assert row["ead_final"] == pytest.approx(_EAD, abs=0.01)
            assert row["lgd_floored"] == pytest.approx(0.40, abs=1e-12)

    def test_qualifying_trade_item_takes_its_residual_maturity(
        self, b31_rows: dict[str, dict]
    ) -> None:
        """M = 182/365 (not the 1-year minimum, and not a fixed one day)."""
        row = b31_rows["DC_182D_TRADE"]
        expected_rw = _rw(lgd=0.40, maturity=_M_182_DAYS, scaling=oracle.B31_IRB_SCALING_FACTOR)

        assert row["has_one_day_maturity_floor"] is True
        assert row["maturity"] == pytest.approx(_M_182_DAYS, abs=1e-12)
        assert row["risk_weight"] == pytest.approx(expected_rw, abs=1e-9)
        assert row["rwa_pre_floor"] == pytest.approx(expected_rw * _EAD, abs=0.01)
        assert row["rwa_pre_floor"] == pytest.approx(71_949.68, abs=0.01)

    def test_non_trade_item_keeps_the_one_year_minimum(self, b31_rows: dict[str, dict]) -> None:
        """Control: the same tenor without the trade flag stays at M = 1.0."""
        row = b31_rows["DC_182D_NOT_TRADE"]

        assert row["has_one_day_maturity_floor"] is False
        assert row["maturity"] == pytest.approx(1.0, abs=1e-12)
        assert row["rwa_pre_floor"] == pytest.approx(81_857.10, abs=0.01)

    def test_exactly_one_year_residual_does_not_qualify(self, b31_rows: dict[str, dict]) -> None:
        """ "less than one year" is strict: a 365-day residual is NOT Art. 162(3)(e)."""
        row = b31_rows["DC_365D_TRADE"]

        assert row["has_one_day_maturity_floor"] is False
        assert row["maturity"] == pytest.approx(1.0, abs=1e-12)


class TestCrrArt1623b:
    """CRR Art. 162(3)(b): a floor of one day on M, with an inclusive one-year bound."""

    def test_qualifying_trade_item_takes_its_residual_maturity(
        self, crr_rows: dict[str, dict]
    ) -> None:
        """M = 182/365, not 1/365 (TR-11: the floor was implemented as a fixed M)."""
        row = crr_rows["DC_182D_TRADE"]
        expected_rw = _rw(lgd=0.45, maturity=_M_182_DAYS, scaling=oracle.CRR_IRB_SCALING_FACTOR)

        assert row["approach_applied"] == "foundation_irb"
        assert row["ead_final"] == pytest.approx(_EAD, abs=0.01)
        assert row["has_one_day_maturity_floor"] is True
        assert row["maturity"] == pytest.approx(_M_182_DAYS, abs=1e-12)
        assert row["rwa_final"] == pytest.approx(expected_rw * _EAD, abs=0.01)
        assert row["rwa_final"] == pytest.approx(85_800.00, abs=0.01)

    def test_exactly_one_year_residual_qualifies_but_the_floor_does_not_bind(
        self, crr_rows: dict[str, dict]
    ) -> None:
        """ "up to one year" is inclusive, and M = max(1 day, 1.0y) = 1.0y."""
        row = crr_rows["DC_365D_TRADE"]

        assert row["has_one_day_maturity_floor"] is True
        assert row["maturity"] == pytest.approx(1.0, abs=1e-12)
        assert row["rwa_final"] == pytest.approx(97_614.59, abs=0.01)


@pytest.fixture(scope="module")
def b31_revolving_drawing() -> dict:
    """A 90-day trade drawing under a revolving trade-LC facility terminating in 3.0y."""
    counterparties = pl.DataFrame(
        [
            {
                "counterparty_reference": "CP_TR05_REV",
                "counterparty_name": "TR-05 revolving importer",
                "entity_type": "corporate",
                "country_code": "GB",
                "default_status": False,
                "annual_revenue": 500_000_000.0,
            }
        ],
        schema_overrides=dtypes_of(COUNTERPARTY_SCHEMA),
    )
    facilities = pl.DataFrame(
        [
            {
                "facility_reference": "FAC_TR05_REV",
                "counterparty_reference": "CP_TR05_REV",
                "value_date": date(2027, 1, 1),
                "maturity_date": date(2030, 1, 31),
                "currency": "GBP",
                "limit": 2_000_000.0,
                "committed": True,
                "risk_type": "MLR",
                "is_revolving": True,
                "facility_termination_date": date(2030, 1, 31),
                "is_short_term_trade_lc": True,
            }
        ],
        schema_overrides=dtypes_of(FACILITY_SCHEMA),
    )
    loans = pl.DataFrame(
        [
            {
                "loan_reference": "LN_TR05_REV_DRAWING",
                "counterparty_reference": "CP_TR05_REV",
                "value_date": date(2027, 1, 1),
                "maturity_date": date(2027, 5, 1),
                "currency": "GBP",
                "drawn_amount": 1_000_000.0,
                "interest": 0.0,
                "seniority": "senior",
            }
        ],
        schema_overrides=dtypes_of(LOAN_SCHEMA),
    )
    facility_mappings = pl.DataFrame(
        [
            {
                "parent_facility_reference": "FAC_TR05_REV",
                "child_reference": "LN_TR05_REV_DRAWING",
                "child_type": "loan",
            }
        ],
        schema_overrides=dtypes_of(FACILITY_MAPPING_SCHEMA),
    )
    ratings = pl.DataFrame(
        [
            {
                "rating_reference": "RTG_TR05_REV",
                "counterparty_reference": "CP_TR05_REV",
                "rating_type": "internal",
                "pd": _PD,
                "rating_date": _B31_REPORTING_DATE,
                "model_id": "TEST_FULL_IRB",
            }
        ],
        schema_overrides=dtypes_of(RATINGS_SCHEMA),
    )
    bundle = make_raw_bundle(
        counterparties=counterparties,
        facilities=facilities,
        loans=loans,
        facility_mappings=facility_mappings,
        ratings=ratings,
        model_permissions=create_full_irb_model_permissions(),
    )
    config = CalculationConfig.basel_3_1(
        reporting_date=_B31_REPORTING_DATE, permission_mode=PermissionMode.IRB
    )
    df = PipelineOrchestrator().run_with_data(bundle, config).results.collect()
    return df.filter(pl.col("exposure_reference") == "LN_TR05_REV_DRAWING").to_dicts()[0]


class TestBasel31RevolvingTradeDrawing:
    """Art. 162(3) replaces the Art. 162(2A)(k) minimum, never the termination-date M."""

    def test_adequacy_the_drawing_is_a_flagged_revolving_foundation_irb_row(
        self, b31_revolving_drawing: dict
    ) -> None:
        """Without the flag and the revolving inheritance the rung is never reached."""
        row = b31_revolving_drawing

        assert row["approach_applied"] == "foundation_irb"
        assert row["is_revolving"] is True
        assert row["is_short_term_trade_lc"] is True
        assert row["has_one_day_maturity_floor"] is True
        assert row["ead_final"] == pytest.approx(1_000_000.0, abs=0.01)

    def test_drawing_keeps_the_facility_termination_date_maturity(
        self, b31_revolving_drawing: dict
    ) -> None:
        """M = 3.0 (termination date), not the 90-day repayment date of the drawing."""
        row = b31_revolving_drawing
        expected_rw = _rw(lgd=0.40, maturity=3.0, scaling=oracle.B31_IRB_SCALING_FACTOR)

        assert row["maturity"] == pytest.approx(3.0, abs=1e-12), (
            "the Art. 162(3) one-day rung priced a revolving drawing on its own "
            "repayment date, which PS1/26 Art. 162(2A)(k) forbids"
        )
        assert row["rwa_pre_floor"] == pytest.approx(expected_rw * 1_000_000.0, abs=0.01)
        assert row["rwa_pre_floor"] == pytest.approx(606_892.43, abs=0.01)
