"""
P1.210: Art. 159 'D' holds defaulted SPECIFIC credit risk adjustments only —
end to end, both regimes, through every route the split can be lost on.

Pipeline position:
    Loader -> SecuritisationAllocator -> HierarchyResolver -> Classifier
        -> CRMProcessor (resolve_provisions) -> IRB / Slotting calculators
        -> OutputAggregator (apply_residual_multiplier -> compute_el_portfolio_summary)

Key responsibilities:
- Prove the specific / general split that ``resolve_provisions`` allocates
  (``provision_specific_allocated``, P1.208) reaches the expected-loss summary,
  so a GENERAL credit risk adjustment allocated to a defaulted obligor lands in
  'B' and not in 'D' — on each of the three routes that carry it there:
    1. the sealed IRB branch (``IRB_BRANCH_EDGE`` must declare the carrier);
    2. the sealed slotting branch (``SLOTTING_BRANCH_EDGE`` must declare it);
    3. the aggregator's securitisation residual scaling (``MONEY_COLS`` must
       list it, or the unscaled 'D' is taken out of a scaled Pool B).
  A sealed edge drops every column it does not declare, and the EL summary
  then counts the whole provision as specific: each leg below fails on its own
  route's loss.
- Prove the ring-fence survives: the defaulted SPECIFIC adjustment, typed
  ``"SCRA"`` in upper case as books and fixtures write it, stays in 'D' and is
  not used to cover the non-defaulted expected loss.
- Parametrised over CRR and Basel 3.1: the rule is the same in both.

Regulatory basis:
    PS1/26 Art. 159(1): 'B' = (i) general credit risk adjustments, (ii) specific
    credit risk adjustments for non-defaulted exposures, (iii) additional value
    adjustments, (iv) other own funds reductions; 'D' = specific credit risk
    adjustments for defaulted exposures. Art. 159(3): "Where 'A' > 'B' and 'D' >
    'C'" report 'B' - 'A' and 'D' - 'C' separately. UK CRR Art. 159: "Specific
    credit risk adjustments on exposures in default shall not be used to cover
    expected loss amounts on other exposures" — general ones may. Slotting is an
    IRB sub-approach (Art. 153(5), Art. 158(6)), so its EL enters the same pools.

Leg 1 — IRB (one corporate counterparty, two A-IRB loans, reused from P1.127):
    LN-P1127-ND: non-defaulted, drawn 1,500,000, PD 0.5%, LGD 45%
        A = 0.005 x 0.45 x 1,500,000 = 3,375
    LN-P1127-D:  defaulted, drawn 1,000,000, BEEL 45% (Art. 158(5))
        C = 0.45 x 1,000,000 = 450,000
    Provisions:
        "SCRA" 460,000 on LN-P1127-D (beneficiary_type loan)
        "GCRA"   2,500 on the counterparty, pro-rata on drawn 1.5m : 1.0m
                 -> 1,500 to ND, 1,000 to the DEFAULTED loan
    AVA 500 on the defaulted loan; no other own funds reductions.

    B = 1,500 + 1,000 (defaulted GCRA) + 500 (defaulted AVA) = 3,000
    D = 460,000
    A > B (3,375 > 3,000) and D > C (460,000 > 450,000) -> Art. 159(3)(a)/(b):
        shortfall = A - B = 375; excess = D - C = 10,000; CET1 deduction 375.

    HEAD (no split; defaulted GCRA and AVA in 'D'): B = 1,500, D = 461,500 ->
    shortfall 1,875, excess 11,500. The carrier stripped by the IRB edge
    (whole defaulted provision specific): B = 2,000, D = 461,000 -> 1,375 /
    11,000. Sending every defaulted provision to 'B' (a case-sensitive "scra"
    test, say) would remove the ring-fence: B = 463,000, D = 0 -> net excess
    9,625 and no shortfall.

Leg 2 — Leg 1 with 60% of LN-P1127-D securitised (residual 0.4):
    The aggregator scales every money column of the defaulted row by 0.4
    before the EL summary reads it (CRR Art. 244(1) / 245(1)):
        C = 0.4 x 450,000 = 180,000;  D = 0.4 x 460,000 = 184,000
        B = 1,500 + 0.4 x (1,000 GCRA + 500 AVA) = 2,100;  A = 3,375
    A > B and D > C -> shortfall 1,275, excess 4,000.
    Carrier left UNscaled (dropped from ``MONEY_COLS``): 'D' = 460,000 is taken
    out of a scaled provision of 184,400, B = -273,900 -> 277,275 / 280,000.

Leg 3 — supervisory slotting (two object-finance SL obligors, permission
slotting, maturity 3 years; the Art. 158(6) Table B satisfactory and default
rates are the same at both maturities and in both regimes):
    LN-P1210-SL-ND: satisfactory, drawn 1,000,000 -> A = 2.8% x 1,000,000 = 28,000
    LN-P1210-SL-D:  default (obligor in default), drawn 1,000,000
                    -> C = 50% x 1,000,000 = 500,000
    Provisions: "SCRA" 15,000 on LN-P1210-SL-ND; "SCRA" 520,000 on
    LN-P1210-SL-D; "GCRA" 10,000 on the DEFAULTED obligor (all to its one loan).
    B = 15,000 + 10,000 = 25,000;  D = 520,000
    A > B and D > C -> shortfall 3,000, excess 20,000.
    HEAD, or the carrier stripped by the slotting edge: B = 15,000,
    D = 530,000 -> 13,000 / 30,000.

The T2 credit is not asserted here: it is capped against IRB RWA, a separate
concern from the pool split.

References:
    - PS1/26 Art. 153(5), 158(5), 158(6), 159(1), 159(3); UK CRR Art. 158, 159
    - CRR Art. 36(1)(d): CET1 deduction of the shortfall
    - CRR Art. 244(1) / 245(1): securitised share carved out of the exposure
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.bundles import AggregatedResultBundle, RawDataBundle
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import (
    COUNTERPARTY_SCHEMA,
    LOAN_SCHEMA,
    MODEL_PERMISSIONS_SCHEMA,
    PROVISION_SCHEMA,
    RATINGS_SCHEMA,
    SECURITISATION_ALLOCATION_SCHEMA,
    SPECIALISED_LENDING_SCHEMA,
)
from rwa_calc.domain.enums import ApproachType, ExposureClass, PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.fixtures.p1_127 import p1_127 as base
from tests.fixtures.raw_bundle import make_raw_bundle

# Leg 1 — IRB
_DEFAULTED_SCRA = 460_000.0
_COUNTERPARTY_GCRA = 2_500.0
_GCRA_TO_DEFAULTED = 1_000.0  # 2,500 x 1,000,000 / 2,500,000
_DEFAULTED_AVA = 500.0

_EXPECTED_SHORTFALL = 375.0  # A - B = 3,375 - 3,000
_EXPECTED_EXCESS = 10_000.0  # D - C = 460,000 - 450,000

# Leg 2 — Leg 1 with the defaulted loan 60% securitised
_SECURITISED_SHARE = 0.6
_RESIDUAL = 0.4
_SECURITISED_EXPECTED_SHORTFALL = 1_275.0  # A - B = 3,375 - 2,100
_SECURITISED_EXPECTED_EXCESS = 4_000.0  # D - C = 184,000 - 180,000

# Leg 3 — slotting
_SL_CP_ND = "CP-P1210-SL-ND"
_SL_CP_D = "CP-P1210-SL-D"
_SL_LOAN_ND = "LN-P1210-SL-ND"
_SL_LOAN_D = "LN-P1210-SL-D"
_SL_MODEL_ID = "P1210-SLOTTING"
_SL_DRAWN = 1_000_000.0
_SL_ND_SCRA = 15_000.0
_SL_D_SCRA = 520_000.0
_SL_D_GCRA = 10_000.0
_SL_EXPECTED_EL_ND = 28_000.0  # satisfactory, Art. 158(6) Table B
_SL_EXPECTED_EL_D = 500_000.0  # default, Art. 158(6) Table B
_SL_EXPECTED_SHORTFALL = 3_000.0  # A - B = 28,000 - 25,000
_SL_EXPECTED_EXCESS = 20_000.0  # D - C = 520,000 - 500,000

_REGIMES = {
    "crr": lambda: CalculationConfig.crr(
        reporting_date=date(2026, 1, 1), permission_mode=PermissionMode.IRB
    ),
    "basel_3_1": lambda: CalculationConfig.basel_3_1(
        reporting_date=date(2027, 1, 1), permission_mode=PermissionMode.IRB
    ),
}


@pytest.fixture(scope="module", params=sorted(_REGIMES))
def results(request: pytest.FixtureRequest) -> AggregatedResultBundle:
    """Leg 1: run the IRB scenario through the full pipeline under one regime."""
    config = _REGIMES[request.param]()
    return PipelineOrchestrator().run_with_data(_irb_bundle(config), config)


@pytest.fixture(scope="module", params=sorted(_REGIMES))
def securitised_results(request: pytest.FixtureRequest) -> AggregatedResultBundle:
    """Leg 2: the IRB scenario with 60% of the defaulted loan securitised."""
    config = _REGIMES[request.param]()
    allocations = pl.LazyFrame(
        [
            {
                "exposure_reference": base.LOAN_REF_D,
                "exposure_type": "loan",
                "pool_reference": "POOL-P1210",
                "allocation_pct": _SECURITISED_SHARE,
                "transfer_type": "traditional",
                "significant_risk_transfer": True,
                "effective_date": config.reporting_date,
            }
        ],
        schema=dtypes_of(SECURITISATION_ALLOCATION_SCHEMA),
    )
    bundle = _irb_bundle(config, securitisation_allocations=allocations)
    return PipelineOrchestrator().run_with_data(bundle, config)


@pytest.fixture(scope="module", params=sorted(_REGIMES))
def slotting_results(request: pytest.FixtureRequest) -> AggregatedResultBundle:
    """Leg 3: run the slotting scenario through the full pipeline under one regime."""
    config = _REGIMES[request.param]()
    return PipelineOrchestrator().run_with_data(_slotting_bundle(config), config)


class TestP1210DefaultedGCRAInPoolB:
    """Leg 1: a general CRA on a defaulted IRB obligor is 'B'; the specific one stays 'D'."""

    def test_scenario_reaches_the_defaulted_obligor(self, results: AggregatedResultBundle) -> None:
        """Adequacy: the GCRA share and the AVA really sit on the defaulted IRB row.

        Without this the pool assertions below would prove nothing — a GCRA
        that never reached the defaulted row leaves 'D' unchanged either way.
        """
        # Arrange / Act
        defaulted = _row(results.irb_results, base.LOAN_REF_D)

        # Assert
        assert defaulted.get_column("is_defaulted").item() is True
        assert defaulted.get_column("provision_allocated").item() == pytest.approx(
            _DEFAULTED_SCRA + _GCRA_TO_DEFAULTED
        ), "the counterparty-level GCRA share did not land on the defaulted loan"
        assert defaulted.get_column("ava_amount").item() == pytest.approx(_DEFAULTED_AVA)
        assert defaulted.get_column("expected_loss").item() == pytest.approx(450_000.0)

    def test_two_branch_split_with_general_cra_in_pool_b(
        self, results: AggregatedResultBundle
    ) -> None:
        """Art. 159(3)(a)/(b): shortfall A - B = 375, excess D - C = 10,000.

        HEAD gives 1,875 / 11,500 (the defaulted GCRA and AVA counted in 'D');
        the carrier stripped by ``IRB_BRANCH_EDGE`` gives 1,375 / 11,000.
        """
        # Arrange
        summary = results.el_summary

        # Assert
        assert summary is not None, "no expected-loss summary for an IRB book"
        assert summary.art_159_3_applies is True
        assert float(summary.total_el_shortfall) == pytest.approx(_EXPECTED_SHORTFALL)
        assert float(summary.total_el_excess) == pytest.approx(_EXPECTED_EXCESS)
        assert float(summary.cet1_deduction) == pytest.approx(_EXPECTED_SHORTFALL)


class TestP1210SecuritisedResidualKeepsTheSplit:
    """Leg 2: the residual scaling scales 'D' with the provision it is part of."""

    def test_scenario_securitises_the_defaulted_loan(
        self, securitised_results: AggregatedResultBundle
    ) -> None:
        """Adequacy: the defaulted IRB row carries the 0.4 residual and the split.

        Without a residual below 1 the aggregator's scaling is a no-op and the
        summary assertion below could not see an unscaled carrier.
        """
        # Arrange / Act
        defaulted = _row(securitised_results.irb_results, base.LOAN_REF_D)

        # Assert
        assert defaulted.get_column("securitisation_residual_pct").item() == pytest.approx(
            _RESIDUAL
        )
        assert defaulted.get_column("provision_specific_allocated").item() == pytest.approx(
            _DEFAULTED_SCRA
        )

    def test_two_branch_split_on_the_on_balance_sheet_residual(
        self, securitised_results: AggregatedResultBundle
    ) -> None:
        """Art. 159(3)(a)/(b) on the residual: shortfall 1,275, excess 4,000.

        With ``provision_specific_allocated`` left out of ``MONEY_COLS`` the
        unscaled 460,000 'D' is taken out of a scaled 184,400 provision:
        277,275 / 280,000.
        """
        # Arrange
        summary = securitised_results.el_summary

        # Assert
        assert summary is not None, "no expected-loss summary for an IRB book"
        assert summary.art_159_3_applies is True
        assert float(summary.total_el_shortfall) == pytest.approx(_SECURITISED_EXPECTED_SHORTFALL)
        assert float(summary.total_el_excess) == pytest.approx(_SECURITISED_EXPECTED_EXCESS)


class TestP1210SlottingDefaultedGCRAInPoolB:
    """Leg 3: the same split on a defaulted slotting exposure."""

    def test_scenario_reaches_the_defaulted_slotting_obligor(
        self, slotting_results: AggregatedResultBundle
    ) -> None:
        """Adequacy: both rows are slotted and the GCRA sits on the defaulted one.

        Reads the carrier off the sealed slotting branch frame itself, so a
        ``SLOTTING_BRANCH_EDGE`` that stopped declaring it fails here by name.
        """
        # Arrange / Act
        defaulted = _row(slotting_results.slotting_results, _SL_LOAN_D)
        non_defaulted = _row(slotting_results.slotting_results, _SL_LOAN_ND)

        # Assert
        assert defaulted.get_column("is_defaulted").item() is True
        assert defaulted.get_column("expected_loss").item() == pytest.approx(_SL_EXPECTED_EL_D)
        assert defaulted.get_column("provision_allocated").item() == pytest.approx(
            _SL_D_SCRA + _SL_D_GCRA
        ), "the obligor-level GCRA did not land on the defaulted slotting loan"
        assert defaulted.get_column("provision_specific_allocated").item() == pytest.approx(
            _SL_D_SCRA
        )
        assert non_defaulted.get_column("is_defaulted").item() is False
        assert non_defaulted.get_column("expected_loss").item() == pytest.approx(_SL_EXPECTED_EL_ND)

    def test_two_branch_split_with_general_cra_in_pool_b(
        self, slotting_results: AggregatedResultBundle
    ) -> None:
        """Art. 159(3)(a)/(b): shortfall A - B = 3,000, excess D - C = 20,000.

        HEAD, or the carrier stripped by ``SLOTTING_BRANCH_EDGE``, gives
        13,000 / 30,000 (the defaulted GCRA counted in 'D').
        """
        # Arrange
        summary = slotting_results.el_summary

        # Assert
        assert summary is not None, "no expected-loss summary for a slotting book"
        assert summary.art_159_3_applies is True
        assert float(summary.total_el_shortfall) == pytest.approx(_SL_EXPECTED_SHORTFALL)
        assert float(summary.total_el_excess) == pytest.approx(_SL_EXPECTED_EXCESS)
        assert float(summary.cet1_deduction) == pytest.approx(_SL_EXPECTED_SHORTFALL)


def _row(branch: pl.LazyFrame | pl.DataFrame | None, reference: str) -> pl.DataFrame:
    """Return the single branch-frame row for ``reference``."""
    assert branch is not None, "the calculator branch produced no frame"
    frame = branch.collect() if isinstance(branch, pl.LazyFrame) else branch
    row = frame.filter(pl.col("exposure_reference") == reference)
    assert row.height == 1, f"{reference} did not reach the calculator branch exactly once"
    return row


def _irb_bundle(
    config: CalculationConfig,
    securitisation_allocations: pl.LazyFrame | None = None,
) -> RawDataBundle:
    """Build the Leg 1 IRB bundle, optionally with a securitisation allocation.

    Value dates sit on the reporting date and maturities keep the P1.127
    shape (2.5 years non-defaulted, 1 year defaulted) relative to it.
    """
    as_of = config.reporting_date
    loans = base.create_p1127_loans().with_columns(
        pl.lit(as_of).alias("value_date"),
        pl.when(pl.col("is_defaulted"))
        .then(pl.lit(date(as_of.year + 1, 1, 1)))
        .otherwise(pl.lit(date(as_of.year + 2, 7, 1)))
        .alias("maturity_date"),
        pl.when(pl.col("is_defaulted"))
        .then(pl.lit(_DEFAULTED_AVA))
        .otherwise(pl.lit(0.0))
        .alias("ava_amount"),
        pl.lit(0.0).alias("other_own_funds_reductions"),
    )
    provisions = _provisions(
        as_of,
        [
            ("PROV-P1210-D-SCRA", "SCRA", 3, _DEFAULTED_SCRA, "loan", base.LOAN_REF_D),
            (
                "PROV-P1210-CP-GCRA",
                "GCRA",
                1,
                _COUNTERPARTY_GCRA,
                "counterparty",
                base.COUNTERPARTY_REF,
            ),
        ],
    )
    return make_raw_bundle(
        facilities=_no_facilities(),
        loans=loans.lazy(),
        counterparties=base.create_p1127_counterparty().lazy(),
        ratings=base.create_p1127_ratings().with_columns(pl.lit(as_of).alias("rating_date")).lazy(),
        provisions=provisions,
        model_permissions=base.create_p1127_model_permission().lazy(),
        securitisation_allocations=securitisation_allocations,
    )


def _slotting_bundle(config: CalculationConfig) -> RawDataBundle:
    """Build the Leg 3 slotting bundle: one non-defaulted and one defaulted SL obligor.

    Each obligor has one 3-year object-finance loan, an internal rating that
    names the slotting model, and specialised-lending metadata giving its
    slotting category; the obligor in default carries ``default_status``.
    """
    as_of = config.reporting_date
    obligors = (
        (_SL_CP_ND, _SL_LOAN_ND, False, "satisfactory"),
        (_SL_CP_D, _SL_LOAN_D, True, "default"),
    )
    counterparties = pl.LazyFrame(
        [
            {
                "counterparty_reference": cp,
                "counterparty_name": f"Object finance SPV {cp} - P1.210",
                "entity_type": "specialised_lending",
                "country_code": "GB",
                "annual_revenue": None,
                "total_assets": 80_000_000.0,
                "default_status": in_default,
                "apply_fi_scalar": False,
                "is_managed_as_retail": False,
            }
            for cp, _, in_default, _ in obligors
        ],
        schema=dtypes_of(COUNTERPARTY_SCHEMA),
    )
    specialised_lending = pl.LazyFrame(
        [
            {
                "counterparty_reference": cp,
                "sl_type": "object_finance",
                "slotting_category": category,
                "is_hvcre": False,
            }
            for cp, _, _, category in obligors
        ],
        schema=dtypes_of(SPECIALISED_LENDING_SCHEMA),
    )
    loans = pl.LazyFrame(
        [
            {
                "loan_reference": loan,
                "product_type": "OBJECT_FINANCE_LOAN",
                "book_code": "SPECIALISED_LENDING",
                "counterparty_reference": cp,
                "value_date": as_of,
                "maturity_date": date(as_of.year + 3, 1, 1),
                "currency": "GBP",
                "drawn_amount": _SL_DRAWN,
                "interest": 0.0,
                "lgd": 0.45,
                "beel": 0.0,
                "seniority": "senior",
            }
            for cp, loan, _, _ in obligors
        ],
        schema=dtypes_of(LOAN_SCHEMA),
    )
    ratings = pl.LazyFrame(
        [
            {
                "rating_reference": f"RTG-{cp}",
                "counterparty_reference": cp,
                "rating_type": "internal",
                "pd": 1.0 if in_default else 0.005,
                "rating_date": as_of,
                "model_id": _SL_MODEL_ID,
            }
            for cp, _, in_default, _ in obligors
        ],
        schema=dtypes_of(RATINGS_SCHEMA),
    )
    model_permissions = pl.LazyFrame(
        [
            {
                "model_id": _SL_MODEL_ID,
                "exposure_class": ExposureClass.SPECIALISED_LENDING.value,
                "approach": ApproachType.SLOTTING.value,
            }
        ],
        schema=dtypes_of(MODEL_PERMISSIONS_SCHEMA),
    )
    provisions = _provisions(
        as_of,
        [
            ("PROV-P1210-SL-ND-SCRA", "SCRA", 2, _SL_ND_SCRA, "loan", _SL_LOAN_ND),
            ("PROV-P1210-SL-D-SCRA", "SCRA", 3, _SL_D_SCRA, "loan", _SL_LOAN_D),
            ("PROV-P1210-SL-D-GCRA", "GCRA", 1, _SL_D_GCRA, "counterparty", _SL_CP_D),
        ],
    )
    return make_raw_bundle(
        facilities=_no_facilities(),
        loans=loans,
        counterparties=counterparties,
        ratings=ratings,
        provisions=provisions,
        model_permissions=model_permissions,
        specialised_lending=specialised_lending,
    )


def _provisions(as_of: date, rows: list[tuple[str, str, int, float, str, str]]) -> pl.LazyFrame:
    """Build provision rows from (reference, type, IFRS 9 stage, amount, beneficiary type, ref)."""
    return pl.LazyFrame(
        [
            {
                "provision_reference": reference,
                "provision_type": provision_type,
                "ifrs9_stage": stage,
                "currency": "GBP",
                "amount": amount,
                "as_of_date": as_of,
                "beneficiary_type": beneficiary_type,
                "beneficiary_reference": beneficiary,
            }
            for reference, provision_type, stage, amount, beneficiary_type, beneficiary in rows
        ],
        schema=dtypes_of(PROVISION_SCHEMA),
    )


def _no_facilities() -> pl.LazyFrame:
    """An empty facilities table: every exposure here is a standalone loan."""
    return pl.LazyFrame(
        schema={"facility_reference": pl.String, "counterparty_reference": pl.String}
    )
