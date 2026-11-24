"""
P1.392 — Simple Method equity collateral takes the rule 4.2 weight in 2027-2029.

Under the Financial Collateral Simple Method the covered portion of an exposure
takes the weight of "a direct exposure to the collateral instrument". For a firm
that had no IRB permission on 31 December 2026, General Provisions rule 4.2
modifies that direct-exposure weight (Art. 133(3)) to 160% / 190% / 220% in
2027 / 2028 / 2029. The engine weighted the collateral at the Art. 133(3)
end-state 250% in every year and for every firm, overstating RWEA on the
covered portion.

Rule text (``docs/assets/ps126app1.pdf``, printed page):

- p.199, Art. 222(3): "The institution shall assign a risk weight to those
  portions of exposure values that are collateralised by the market value of
  eligible collateral, being the risk weight that it would assign under the
  Credit Risk: Standardised Approach (CRR) Part and Chapter 2 of Title II of
  Part Three of CRR where the institution had a direct exposure to the
  collateral instrument. The risk weight of the collateralised portion shall be
  at least 20% except as specified in paragraphs 4 to 6."
- p.68, Art. 133(3): "An equity exposure shall be assigned a risk weight of
  250%, unless the exposure is a higher risk equity exposure [...] or is within
  scope of paragraph 6".
- p.20, rule 4.1: "4.2 and 4.3 only apply to an institution that did not have
  permission to use the Internal Ratings Based Approach under Article 143 of
  CRR on 31 December 2026."
- p.20, rule 4.2: "This rule modifies paragraph 3 of Credit Risk: Standardised
  Approach (CRR) Part Article 133 for a transitional period beginning with
  1 January 2027 and ending with 31 December 2029, in which equity exposures
  that are not higher risk equity exposures or within the scope of paragraph 6
  [...] shall be assigned the following risk weights: (1) 160% [...] 2027;
  (2) 190% [...] 2028; and (3) 220% [...] 2029."

Rule 4.3 (higher risk equity) cannot be reached: Simple Method equity must be
"included in a main index" (Art. 197(1)(f); the Art. 198(1)(a) extension is for
the Comprehensive Method only), so it is listed and never a Glossary "higher
risk equity exposure" (not listed AND under five years old).

What stays at 250% (Art. 133(3)), and why each leg is here:

- a Basel 3.1 run dated before 2027: the rule 4.2 Schedule resolves to its
  ``before_first`` 0.0 there, which the Art. 222(3) 20% floor would turn into a
  20% collateral weight under a fix that read the Schedule without the period;
- 2030 onwards, the end state;
- a firm that HAD IRB permission on 31 December 2026, stated or derived from an
  F-IRB / A-IRB map or a slotting-only map (Art. 143(2A)(a): slotting is an IRB
  Approach). The slotting leg separates the rule 4.1 firm fact from the
  narrower F-IRB / A-IRB-only permission predicate beside it. Such a firm's own
  rules (4.5 / 4.6) are not implemented, so its direct equity keeps Art. 133
  with a CFG003 warning (P1.389), and its collateral keeps the same weight.

CRR is unaffected (Art. 133(2) 100%, no equity transitional). The CRR legs
cannot be reddened by the defect, which is Basel 3.1 only; they guard a fix that
reaches the CRR pack.

One leg LOWERS the output floor and is correct by the rule: a firm that states
it had no IRB permission at 31 December 2026 but holds an IRB permission granted
later is inside rule 4.1, so its collateral takes 160% in 2027, including on the
SA-equivalent weight the output floor reads.

Hand calculation (pipeline leg; unrated corporate loan 1,000,000 at 100%,
main-index equity collateral 600,000, so 60% covered, no EAD reduction). These
are the uncapped Art. 222(3) blends. Since P1.346 every Basel 3.1 blend here is
above the unsecured 100%, so the leg is declined under the firm's PS1/26
Art. 193(2A) election and its weight stays 1.00 (RWEA 1,000,000). The pipeline
tests therefore pin the blend from the row's own carriers (the collateral
weight is what this item changed) and the final weight as the lower of the
blend and the unsecured weight:
    2027  0.60 x 1.60 + 0.40 x 1.00 = 1.36  ->  RWEA 1,360,000 (pre-fix 1,900,000)
    2028  0.60 x 1.90 + 0.40 x 1.00 = 1.54  ->  RWEA 1,540,000
    2029  0.60 x 2.20 + 0.40 x 1.00 = 1.72  ->  RWEA 1,720,000
    2030  0.60 x 2.50 + 0.40 x 1.00 = 1.90  ->  RWEA 1,900,000 (end state)
    CRR   0.60 x 1.00 + 0.40 x 1.00 = 1.00  ->  RWEA 1,000,000

References:
- PRA PS1/26 Art. 222(3): Financial Collateral Simple Method
- PRA PS1/26 Art. 133(3): equity exposure risk weight
- PRA PS1/26 Credit Risk: General Provisions (CRR) Part rules 4.1-4.2
- CRR Art. 222(3), Art. 133(2)
"""

from __future__ import annotations

import dataclasses
from datetime import date
from typing import Any

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig, IRBPermissions
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import (
    COLLATERAL_SCHEMA,
    COUNTERPARTY_SCHEMA,
    LOAN_SCHEMA,
    MODEL_PERMISSIONS_SCHEMA,
    RATINGS_SCHEMA,
)
from rwa_calc.domain.enums import ApproachType, CRMCollateralMethod, ExposureClass, PermissionMode
from rwa_calc.engine.crm.simple_method import compute_fcsm_columns
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.fixtures.raw_bundle import make_raw_bundle

# ---------------------------------------------------------------------------
# Scenario constants — the weights are the rule text's, not the pack's
# ---------------------------------------------------------------------------

_LOAN = "LN-P1392-CORP"
_CP = "CP-P1392-CORP"
_COLL = "COLL-P1392-EQUITY"
_IRB_MODEL = "MDL-P1392-FIRB"
_EAD = 1_000_000.0
_COLLATERAL_VALUE = 600_000.0
_COVERED = _COLLATERAL_VALUE / _EAD
_UNSECURED_RW = 1.00  # unrated corporate, Art. 122

END_STATE_RW = 2.50  # PS1/26 Art. 133(3)
CRR_RW = 1.00  # CRR Art. 133(2)

#: (reporting date, rule 4.2 weight) — the legs this item moves.
RULE_4_2_DATES = (
    (date(2027, 1, 1), 1.60),  # first day of rule 4.2(1)
    (date(2027, 6, 30), 1.60),
    (date(2028, 6, 30), 1.90),  # 4.2(2)
    (date(2029, 6, 30), 2.20),  # 4.2(3)
    (date(2029, 12, 31), 2.20),  # last day of the transitional period
)

#: A firm whose only IRB permission is slotting — an IRB Approach (Art. 143(2A)(a)).
SLOTTING_ONLY = IRBPermissions(
    permissions={ExposureClass.SPECIALISED_LENDING: {ApproachType.SA, ApproachType.SLOTTING}}
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _b31(
    on: date,
    *,
    permission_mode: PermissionMode = PermissionMode.STANDARDISED,
    irb_permissions: IRBPermissions | None = None,
    **equity_transitional: Any,
) -> CalculationConfig:
    config = CalculationConfig.basel_3_1(
        reporting_date=on,
        permission_mode=permission_mode,
        crm_collateral_method=CRMCollateralMethod.SIMPLE,
    )
    if irb_permissions is not None:
        config = dataclasses.replace(config, irb_permissions=irb_permissions)
    if equity_transitional:
        config = dataclasses.replace(
            config,
            equity_transitional=dataclasses.replace(
                config.equity_transitional, **equity_transitional
            ),
        )
    return config


def _crr(on: date) -> CalculationConfig:
    return CalculationConfig.crr(
        reporting_date=on, crm_collateral_method=CRMCollateralMethod.SIMPLE
    )


def _exposure_frame() -> pl.LazyFrame:
    return pl.LazyFrame(
        {
            "exposure_reference": [_LOAN],
            "ead_gross": [_EAD],
            "ead": [_EAD],
            "currency": ["GBP"],
            "approach": [ApproachType.SA.value],
            "exposure_class": [ExposureClass.CORPORATE.value],
            "risk_weight": [_UNSECURED_RW],
        }
    )


def _equity_pledge() -> dict[str, Any]:
    """Main-index equity: Art. 197(1)(f) eligible under the Simple Method.

    ``issuer_type`` is corporate, never institution or sovereign: the collateral
    weight chain tests those issuer arms before the equity arm, so a bank share
    pledged with ``issuer_type="institution"`` would measure the Art. 120 debt
    weight, not the equity weight this item is about.
    """
    return {
        "collateral_reference": _COLL,
        "collateral_type": "equity",
        "currency": "GBP",
        "market_value": _COLLATERAL_VALUE,
        "beneficiary_type": "loan",
        "beneficiary_reference": _LOAN,
        "issuer_type": "corporate",
        "issuer_cqs": None,
        "is_main_index": True,
        "is_listed": True,
        "is_eligible_financial_collateral": True,
    }


def _collateral_frame() -> pl.LazyFrame:
    return pl.DataFrame([_equity_pledge()], schema_overrides={"issuer_cqs": pl.Int8}).lazy()


def _fcsm(config: CalculationConfig) -> dict[str, Any]:
    out = compute_fcsm_columns(_exposure_frame(), _collateral_frame(), config).collect()
    row = out.to_dicts()[0]
    assert row["fcsm_collateral_value"] == pytest.approx(_COLLATERAL_VALUE), (
        "the equity pledge did not reach the Simple Method - every leg would be vacuous"
    )
    return row


def _pipeline_bundle(*, irb_model: bool = False):
    """The one-loan scenario; ``irb_model`` adds an internal PD and an F-IRB model permission."""
    counterparties = pl.DataFrame(
        [
            {
                "counterparty_reference": _CP,
                "counterparty_name": _CP,
                "entity_type": "corporate",
                "country_code": "GB",
                "is_natural_person": False,
                "is_managed_as_retail": False,
                "default_status": False,
                "apply_fi_scalar": False,
                "is_financial_sector_entity": False,
            }
        ],
        schema_overrides=dtypes_of(COUNTERPARTY_SCHEMA),
    )
    loans = pl.DataFrame(
        [
            {
                "loan_reference": _LOAN,
                "counterparty_reference": _CP,
                "product_type": "term_loan",
                "currency": "GBP",
                "value_date": date(2026, 1, 1),
                "maturity_date": date(2031, 1, 1),
                "drawn_amount": _EAD,
                "interest": 0.0,
                "seniority": "senior",
                "is_defaulted": False,
            }
        ],
        schema_overrides=dtypes_of(LOAN_SCHEMA),
    )
    collateral = pl.DataFrame([_equity_pledge()], schema_overrides=dtypes_of(COLLATERAL_SCHEMA))
    if not irb_model:
        return make_raw_bundle(counterparties=counterparties, loans=loans, collateral=collateral)
    ratings = pl.DataFrame(
        [
            {
                "rating_reference": "RT-P1392",
                "counterparty_reference": _CP,
                "rating_type": "internal",
                "pd": 0.01,
                "model_id": _IRB_MODEL,
                "rating_date": date(2026, 6, 30),
            }
        ],
        schema_overrides=dtypes_of(RATINGS_SCHEMA),
    )
    model_permissions = pl.DataFrame(
        [{"model_id": _IRB_MODEL, "exposure_class": "corporate", "approach": "foundation_irb"}],
        schema_overrides=dtypes_of(MODEL_PERMISSIONS_SCHEMA),
    )
    return make_raw_bundle(
        counterparties=counterparties,
        loans=loans,
        collateral=collateral,
        ratings=ratings,
        model_permissions=model_permissions,
    )


def _pipeline_row(config: CalculationConfig) -> dict[str, Any]:
    result = PipelineOrchestrator().run_with_data(_pipeline_bundle(), config)
    rows = result.results.collect().filter(pl.col("exposure_reference") == _LOAN).to_dicts()
    assert len(rows) == 1, f"{_LOAN} did not reach the sealed results frame"
    return rows[0]


def _blended(collateral_rw: float) -> float:
    return _COVERED * collateral_rw + (1 - _COVERED) * _UNSECURED_RW


def _final(collateral_rw: float) -> float:
    """The applied weight: the blend, unless it would raise the unsecured weight.

    CRR Art. 193(1) forbids a higher RWEA; under Basel 3.1 the firm's PS1/26
    Art. 193(2A) election disregards the protection (P1.346). Equality applies.
    """
    return min(_blended(collateral_rw), _UNSECURED_RW)


# ---------------------------------------------------------------------------
# Rule 4.2 reaches the Art. 222(3) direct-exposure weight
# ---------------------------------------------------------------------------


class TestRule42ReachesSimpleMethodEquityCollateral:
    """A firm without IRB permission on 31 December 2026: 160% / 190% / 220%."""

    @pytest.mark.parametrize(("on", "rule_rw"), RULE_4_2_DATES, ids=lambda v: str(v))
    def test_collateral_takes_the_rule_4_2_weight(self, on: date, rule_rw: float) -> None:
        # Arrange
        config = _b31(on)

        # Act
        row = _fcsm(config)

        # Assert
        assert row["fcsm_collateral_rw"] == pytest.approx(rule_rw)

    def test_rule_4_9_election_does_not_restore_250_percent_for_a_standardised_firm(
        self,
    ) -> None:
        """Rule 4.9 replaces only 4.5, 4.6 and 4.8; a rule 4.1 firm has nothing to elect.

        The direct-equity treatment keeps 160% for such a firm with ``opt_out``
        set, so the direct-exposure weight Art. 222(3) reads is 160% too.
        """
        # Arrange
        config = _b31(date(2027, 6, 30), opt_out=True)

        # Act
        row = _fcsm(config)

        # Assert
        assert row["fcsm_collateral_rw"] == pytest.approx(1.60)

    def test_permission_granted_after_2026_year_end_is_inside_rule_4_1(self) -> None:
        """The floor-reducing leg: IRB permission held now, stated absent on 31 Dec 2026.

        Rule 4.1 turns on the permission held "on 31 December 2026", not on the
        run's. Such a firm's collateral takes 160% in 2027, including on the
        SA-equivalent weight the output floor reads (the Simple Method blend runs
        in the unconditional SA weight pipe), so S-TREA falls with it.
        """
        # Arrange
        config = _b31(
            date(2027, 6, 30),
            permission_mode=PermissionMode.IRB,
            irb_permission_at_2026_year_end=False,
        )

        # Act
        row = _fcsm(config)

        # Assert
        assert row["fcsm_collateral_rw"] == pytest.approx(1.60)


class TestArticle133EndStateStillApplies:
    """Outside rule 4.1 / 4.2 the collateral keeps Art. 133(3)'s 250%."""

    def test_basel_3_1_run_before_2027_keeps_250_percent(self) -> None:
        """Before the period the rule 4.2 Schedule resolves to ``before_first`` = 0.0.

        Read without the period gate, that 0.0 would reach the Art. 222(3) 20%
        floor and weight the collateral at 20%.
        """
        # Act
        row = _fcsm(_b31(date(2026, 12, 31)))

        # Assert
        assert row["fcsm_collateral_rw"] == pytest.approx(END_STATE_RW)

    def test_end_state_from_2030(self) -> None:
        # Act
        row = _fcsm(_b31(date(2030, 1, 1)))

        # Assert
        assert row["fcsm_collateral_rw"] == pytest.approx(END_STATE_RW)

    def test_stated_irb_permission_at_2026_year_end_keeps_250_percent(self) -> None:
        # Arrange: an IRB firm's Standardised shadow run states the fact.
        config = _b31(date(2027, 6, 30), irb_permission_at_2026_year_end=True)

        # Act
        row = _fcsm(config)

        # Assert
        assert row["fcsm_collateral_rw"] == pytest.approx(END_STATE_RW)

    def test_irb_permission_map_keeps_250_percent(self) -> None:
        # Arrange
        config = _b31(date(2027, 6, 30), permission_mode=PermissionMode.IRB)

        # Act
        row = _fcsm(config)

        # Assert
        assert row["fcsm_collateral_rw"] == pytest.approx(END_STATE_RW)

    def test_slotting_only_firm_had_irb_permission(self) -> None:
        """Art. 143(2A)(a): slotting is an IRB Approach, so rule 4.1 excludes the firm.

        A predicate that counted only F-IRB / A-IRB permission would give this
        firm 160%.
        """
        # Arrange
        config = _b31(
            date(2027, 6, 30), permission_mode=PermissionMode.IRB, irb_permissions=SLOTTING_ONLY
        )

        # Act
        row = _fcsm(config)

        # Assert
        assert row["fcsm_collateral_rw"] == pytest.approx(END_STATE_RW)


class TestCrrIsUnaffected:
    """CRR Art. 133(2): 100%, with no equity transitional in the CRR pack."""

    @pytest.mark.parametrize("on", [date(2026, 6, 30), date(2027, 6, 30)], ids=str)
    def test_crr_collateral_keeps_100_percent(self, on: date) -> None:
        # Act
        row = _fcsm(_crr(on))

        # Assert
        assert row["fcsm_collateral_rw"] == pytest.approx(CRR_RW)


# ---------------------------------------------------------------------------
# Full pipeline — the capital reaches the sealed results frame
# ---------------------------------------------------------------------------


class TestPipelineCarriesTheTransitionalCollateralWeight:
    """A Standardised firm, 60% covered by main-index equity, through every stage."""

    @pytest.mark.parametrize(
        ("config", "collateral_rw"),
        [
            pytest.param(_b31(date(2027, 6, 30)), 1.60, id="b31-2027-rule-4.2"),
            pytest.param(_b31(date(2029, 6, 30)), 2.20, id="b31-2029-rule-4.2"),
            pytest.param(_b31(date(2030, 1, 1)), END_STATE_RW, id="b31-2030-end-state"),
            pytest.param(_crr(date(2026, 6, 30)), CRR_RW, id="crr"),
        ],
    )
    def test_sealed_row_carries_the_blended_weight_and_rwea(
        self, config: CalculationConfig, collateral_rw: float
    ) -> None:
        # Act
        row = _pipeline_row(config)

        # Assert
        assert row["fcsm_collateral_value"] == pytest.approx(_COLLATERAL_VALUE)
        assert row["ead_final"] == pytest.approx(_EAD)
        assert _COVERED * row["fcsm_collateral_rw"] + (1 - _COVERED) * row[
            "pre_fcsm_risk_weight"
        ] == pytest.approx(_blended(collateral_rw))
        assert row["risk_weight"] == pytest.approx(_final(collateral_rw))
        assert row["rwa_final"] == pytest.approx(_EAD * _final(collateral_rw))


class TestOutputFloorFollowsTheCollateralWeight:
    """An F-IRB row's SA-equivalent weight carries the Simple Method blend into S-TREA.

    Since P1.346 both legs' blends are above the unsecured 100% and are declined
    under the PS1/26 Art. 193(2A) election, so S-TREA is the unsecured RWEA on
    both; the transitional weight is pinned on the row's own collateral weight.

    The blend runs in the unconditional SA weight pipe, so the collateral weight
    reaches the output floor on an IRB row. A firm that states it had no IRB
    permission on 31 December 2026 (a permission granted later) is inside rule
    4.1, so its S-TREA falls with the rule 4.2 weight: correct by the rule, and
    the one path on which this item lowers the floor. A firm whose F-IRB
    permission is taken as held on that date keeps 250%.
    """

    @pytest.mark.parametrize(
        ("stated", "collateral_rw"),
        [
            pytest.param(False, 1.60, id="stated-no-irb-permission-at-2026-ye"),
            pytest.param(None, END_STATE_RW, id="irb-permission-derived-from-run"),
        ],
    )
    def test_s_trea_carries_the_collateral_weight(
        self, stated: bool | None, collateral_rw: float
    ) -> None:
        # Arrange
        config = _b31(
            date(2027, 6, 30),
            permission_mode=PermissionMode.IRB,
            irb_permission_at_2026_year_end=stated,
        )

        # Act
        result = PipelineOrchestrator().run_with_data(_pipeline_bundle(irb_model=True), config)
        row = result.results.collect().filter(pl.col("exposure_reference") == _LOAN).to_dicts()[0]
        floor = result.output_floor_summary

        # Assert
        assert row["approach_applied"] == ApproachType.FIRB.value, (
            "the loan did not reach F-IRB - S-TREA would be SA RWEA and prove nothing here"
        )
        assert row["fcsm_collateral_value"] == pytest.approx(_COLLATERAL_VALUE)
        assert row["fcsm_collateral_rw"] == pytest.approx(collateral_rw)
        assert floor is not None
        assert floor.s_trea == pytest.approx(_EAD * _final(collateral_rw))
