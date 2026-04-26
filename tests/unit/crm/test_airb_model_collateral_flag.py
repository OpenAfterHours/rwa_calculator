"""
Tests for the ``is_airb_model_collateral`` flag on the collateral table.

The flag asserts that the collateral has been used to construct the firm's
internal LGD model (CRR Art. 181 / Basel 3.1 Art. 169A). When set, the row is
allocated only to AIRB-pool exposures (where modelled LGD is preserved) and is
excluded from non-AIRB exposures of the same counterparty/facility — preventing
the collateral from being double-counted via supervisory CRM on top of the
already-incorporated effect inside the AIRB LGD.

Pool-aware pro-rata: even unflagged counterparty/facility-level collateral is
allocated only over the non-AIRB pool. AIRB exposures are excluded from the
pro-rata base, so non-AIRB rows absorb the full collateral instead of having
some "wasted" on AIRB rows that ignore it (their LGD is preserved either way).

Coverage:
- Default flag value is False.
- Unflagged counterparty-level collateral on mixed AIRB+FIRB CP: all of it
  routes to the FIRB exposure (AIRB excluded from the pro-rata base).
- Flagged counterparty-level collateral on mixed AIRB+FIRB CP: routes to
  AIRB-pool exposures, FIRB gets nothing.
- User scenario: loan_1 (AIRB), loan_2 (FIRB), loan_3 (AIRB) under one CP with
  flagged counterparty-level collateral — splits across loan_1/loan_3 only.
- Flagged direct collateral on a non-AIRB exposure emits CRM006 and has zero
  allocation effect.
- Flagged direct collateral on an AIRB exposure is silently ignored from a
  CRM standpoint (modelled LGD preserved) and produces no warning.
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.bundles import (
    ClassifiedExposuresBundle,
    CounterpartyLookup,
)
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.contracts.errors import ERROR_AIRB_MODEL_COLLATERAL_MISDIRECTED
from rwa_calc.data.schemas import COLLATERAL_SCHEMA
from rwa_calc.domain.enums import ApproachType, PermissionMode
from rwa_calc.engine.crm.processor import CRMProcessor

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def processor() -> CRMProcessor:
    return CRMProcessor()


@pytest.fixture
def crr_config() -> CalculationConfig:
    return CalculationConfig.crr(
        reporting_date=date(2024, 12, 31),
        permission_mode=PermissionMode.IRB,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _exposure(
    ref: str,
    approach: str,
    *,
    drawn: float = 1000.0,
    lgd: float = 0.45,
    cp_ref: str = "CP001",
    facility_ref: str = "FAC001",
) -> dict:
    return {
        "exposure_reference": ref,
        "counterparty_reference": cp_ref,
        "exposure_class": "corporate",
        "approach": approach,
        "drawn_amount": drawn,
        "interest": 0.0,
        "nominal_amount": 0.0,
        "risk_type": "FR",
        "lgd": lgd,
        "seniority": "senior",
        "parent_facility_reference": facility_ref,
        "currency": "GBP",
        "maturity_date": None,
    }


def _collateral(
    coll_ref: str,
    beneficiary_ref: str,
    *,
    market_value: float,
    beneficiary_type: str = "counterparty",
    is_airb_model: bool = False,
) -> dict:
    return {
        "collateral_reference": coll_ref,
        "beneficiary_reference": beneficiary_ref,
        "beneficiary_type": beneficiary_type,
        "collateral_type": "cash",
        "market_value": market_value,
        "currency": "GBP",
        "issuer_cqs": None,
        "issuer_type": None,
        "residual_maturity_years": None,
        "is_eligible_financial_collateral": True,
        "is_airb_model_collateral": is_airb_model,
        "pledge_percentage": None,
        "collateral_maturity_date": None,
    }


_COLL_SCHEMA: dict[str, pl.DataType] = {
    "collateral_reference": pl.String,
    "beneficiary_reference": pl.String,
    "beneficiary_type": pl.String,
    "collateral_type": pl.String,
    "market_value": pl.Float64,
    "currency": pl.String,
    "issuer_cqs": pl.Int64,
    "issuer_type": pl.String,
    "residual_maturity_years": pl.Float64,
    "is_eligible_financial_collateral": pl.Boolean,
    "is_airb_model_collateral": pl.Boolean,
    "pledge_percentage": pl.Float64,
    "collateral_maturity_date": pl.Date,
}


def _make_bundle(exposures: pl.LazyFrame, collateral: pl.LazyFrame) -> ClassifiedExposuresBundle:
    empty_cp = pl.LazyFrame(schema={"counterparty_reference": pl.String, "entity_type": pl.String})
    empty_mappings = pl.LazyFrame(
        schema={
            "child_counterparty_reference": pl.String,
            "parent_counterparty_reference": pl.String,
        }
    )
    empty_ultimate = pl.LazyFrame(
        schema={
            "counterparty_reference": pl.String,
            "ultimate_parent_reference": pl.String,
            "hierarchy_depth": pl.Int32,
        }
    )
    empty_ri = pl.LazyFrame(
        schema={"counterparty_reference": pl.String, "cqs": pl.Int8, "rating_type": pl.String}
    )
    return ClassifiedExposuresBundle(
        all_exposures=exposures,
        sa_exposures=pl.LazyFrame(),
        irb_exposures=pl.LazyFrame(),
        slotting_exposures=pl.LazyFrame(),
        equity_exposures=None,
        counterparty_lookup=CounterpartyLookup(
            counterparties=empty_cp,
            parent_mappings=empty_mappings,
            ultimate_parent_mappings=empty_ultimate,
            rating_inheritance=empty_ri,
        ),
        collateral=collateral,
        guarantees=None,
        provisions=None,
    )


def _run(
    processor: CRMProcessor,
    config: CalculationConfig,
    exposures: list[dict],
    collateral: list[dict],
):
    exposures_lf = pl.LazyFrame(exposures)
    collateral_lf = pl.LazyFrame(collateral, schema=_COLL_SCHEMA)
    bundle = _make_bundle(exposures_lf, collateral_lf)
    result = processor.get_crm_adjusted_bundle(bundle, config)
    return result.exposures.collect(), result.crm_errors


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


class TestSchema:
    def test_flag_present_in_collateral_schema(self):
        spec = COLLATERAL_SCHEMA["is_airb_model_collateral"]
        assert spec.dtype == pl.Boolean
        assert spec.required is False
        assert spec.default is False


# ---------------------------------------------------------------------------
# Pool-aware pro-rata for unflagged counterparty-level collateral
# ---------------------------------------------------------------------------


class TestUnflaggedCounterpartyCollateral:
    def test_airb_excluded_from_pro_rata_base(
        self, processor: CRMProcessor, crr_config: CalculationConfig
    ):
        """
        Counterparty has one AIRB and one FIRB exposure of equal EAD; an
        unflagged counterparty-level cash collateral should route entirely to
        the FIRB exposure (AIRB excluded from the base) under the new
        pool-aware logic. Old behaviour would have split 50/50.
        """
        df, _ = _run(
            processor,
            crr_config,
            [
                _exposure("AIRB1", ApproachType.AIRB.value, drawn=1000.0, lgd=0.20),
                _exposure("FIRB1", ApproachType.FIRB.value, drawn=1000.0),
            ],
            [_collateral("C1", "CP001", market_value=400.0)],
        )
        airb_row = df.filter(pl.col("exposure_reference") == "AIRB1")
        firb_row = df.filter(pl.col("exposure_reference") == "FIRB1")
        # AIRB modelled LGD is preserved regardless of allocation, but the
        # pool-aware logic also drops collateral lineage from the AIRB row.
        assert airb_row["collateral_adjusted_value"][0] == pytest.approx(0.0, abs=0.01)
        # FIRB absorbs the full 400 (no longer halved with AIRB).
        assert firb_row["collateral_adjusted_value"][0] == pytest.approx(400.0, abs=1.0)


# ---------------------------------------------------------------------------
# Flagged counterparty-level collateral
# ---------------------------------------------------------------------------


class TestFlaggedCounterpartyCollateral:
    def test_flagged_collateral_excluded_from_non_airb(
        self, processor: CRMProcessor, crr_config: CalculationConfig
    ):
        """
        Flagged collateral (already in AIRB internal LGD model) must not be
        allocated to FIRB / SA / Slotting exposures. The FIRB exposure receives
        zero collateral, preventing double-counting.
        """
        df, _ = _run(
            processor,
            crr_config,
            [
                _exposure("AIRB1", ApproachType.AIRB.value, drawn=1000.0, lgd=0.20),
                _exposure("FIRB1", ApproachType.FIRB.value, drawn=1000.0),
            ],
            [_collateral("C1", "CP001", market_value=400.0, is_airb_model=True)],
        )
        firb_row = df.filter(pl.col("exposure_reference") == "FIRB1")
        # FIRB exposure must not see any of the AIRB-model-flagged collateral.
        assert firb_row["collateral_adjusted_value"][0] == pytest.approx(0.0, abs=0.01)

    def test_user_scenario_loan_1_2_3(self, processor: CRMProcessor, crr_config: CalculationConfig):
        """
        loan_1 (AIRB), loan_2 (FIRB), loan_3 (AIRB) under one counterparty.
        Flagged counterparty-level collateral splits across loan_1 and loan_3
        (AIRB pool, EAD-weighted) and excludes loan_2 entirely.
        """
        df, _ = _run(
            processor,
            crr_config,
            [
                _exposure("loan_1", ApproachType.AIRB.value, drawn=1000.0, lgd=0.20),
                _exposure("loan_2", ApproachType.FIRB.value, drawn=1000.0),
                _exposure("loan_3", ApproachType.AIRB.value, drawn=1000.0, lgd=0.20),
            ],
            [_collateral("C1", "CP001", market_value=600.0, is_airb_model=True)],
        )
        loan_2 = df.filter(pl.col("exposure_reference") == "loan_2")
        assert loan_2["collateral_adjusted_value"][0] == pytest.approx(0.0, abs=0.01)
        # loan_1 and loan_3 split the 600 pro-rata (300 each given equal EAD).
        loan_1 = df.filter(pl.col("exposure_reference") == "loan_1")
        loan_3 = df.filter(pl.col("exposure_reference") == "loan_3")
        assert loan_1["collateral_adjusted_value"][0] == pytest.approx(300.0, abs=1.0)
        assert loan_3["collateral_adjusted_value"][0] == pytest.approx(300.0, abs=1.0)


# ---------------------------------------------------------------------------
# Flagged direct collateral validation (CRM006)
# ---------------------------------------------------------------------------


class TestFlaggedDirectCollateralValidation:
    def test_flagged_direct_on_non_airb_emits_crm006(
        self, processor: CRMProcessor, crr_config: CalculationConfig
    ):
        """A direct flagged collateral pledged to a FIRB exposure is a
        misconfiguration — emit CRM006 and contribute zero collateral."""
        df, errors = _run(
            processor,
            crr_config,
            [_exposure("FIRB1", ApproachType.FIRB.value, drawn=1000.0)],
            [
                _collateral(
                    "C1",
                    "FIRB1",
                    market_value=400.0,
                    beneficiary_type="exposure",
                    is_airb_model=True,
                )
            ],
        )
        codes = [e.code for e in errors]
        assert ERROR_AIRB_MODEL_COLLATERAL_MISDIRECTED in codes
        # Zero allocation: FIRB exposure does not receive the AIRB-model collateral.
        firb_row = df.filter(pl.col("exposure_reference") == "FIRB1")
        assert firb_row["collateral_adjusted_value"][0] == pytest.approx(0.0, abs=0.01)

    def test_flagged_direct_on_airb_no_warning(
        self, processor: CRMProcessor, crr_config: CalculationConfig
    ):
        """A direct flagged collateral pledged to an AIRB exposure is correctly
        configured: modelled LGD is preserved (no LGD effect) and no warning."""
        df, errors = _run(
            processor,
            crr_config,
            [_exposure("AIRB1", ApproachType.AIRB.value, drawn=1000.0, lgd=0.18)],
            [
                _collateral(
                    "C1",
                    "AIRB1",
                    market_value=400.0,
                    beneficiary_type="exposure",
                    is_airb_model=True,
                )
            ],
        )
        codes = [e.code for e in errors]
        assert ERROR_AIRB_MODEL_COLLATERAL_MISDIRECTED not in codes
        airb_row = df.filter(pl.col("exposure_reference") == "AIRB1")
        # AIRB modelled LGD preserved unchanged.
        assert airb_row["lgd_post_crm"][0] == pytest.approx(0.18)


# ---------------------------------------------------------------------------
# Backward compatibility
# ---------------------------------------------------------------------------


class TestBackwardCompatibility:
    def test_homogeneous_firb_counterparty_unaffected(
        self, processor: CRMProcessor, crr_config: CalculationConfig
    ):
        """When a counterparty has only non-AIRB exposures, pool-aware logic
        is a no-op: counterparty-level collateral splits pro-rata as before."""
        df, _ = _run(
            processor,
            crr_config,
            [
                _exposure("FIRB1", ApproachType.FIRB.value, drawn=700.0),
                _exposure("FIRB2", ApproachType.FIRB.value, drawn=300.0),
            ],
            [_collateral("C1", "CP001", market_value=200.0)],
        )
        firb1 = df.filter(pl.col("exposure_reference") == "FIRB1")
        firb2 = df.filter(pl.col("exposure_reference") == "FIRB2")
        assert firb1["collateral_adjusted_value"][0] == pytest.approx(140.0, abs=1.0)
        assert firb2["collateral_adjusted_value"][0] == pytest.approx(60.0, abs=1.0)
