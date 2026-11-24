"""
Standardised Transitional Approach for equities — PS1/26 Credit Risk: General Provisions 4.1-4.3.

A firm that did NOT have IRB permission on 31 December 2026 weights its equity
exposures in 2027, 2028 and 2029 at the rule 4.2 / 4.3 weights, in place of the
Art. 133(3) / (4) end-state weights. The engine used to apply those weights as a
floor under 250% / 400% (``max_horizontal``), which can never bind, so such a
firm was weighted 250% / 400% throughout the transition. These tests pin the
assignment the rules make, the exclusions they make, and the firm fact they
turn on.

Rule text (``docs/assets/ps126app1.pdf``, PDF page = printed page):

- p.20, 4.1: "4.2 and 4.3 only apply to an institution that did not have
  permission to use the Internal Ratings Based Approach under Article 143 of CRR
  on 31 December 2026."
- p.20, 4.2: "This rule modifies paragraph 3 of Credit Risk: Standardised
  Approach (CRR) Part Article 133 for a transitional period beginning with
  1 January 2027 and ending with 31 December 2029, in which equity exposures
  that are not higher risk equity exposures or within the scope of paragraph 6
  of Credit Risk: Standardised Approach (CRR) Part Article 133 shall be assigned
  the following risk weights: (1) 160% during the period beginning with
  1 January 2027 and ending with 31 December 2027; (2) 190% during the period
  beginning with 1 January 2028 and ending with 31 December 2028; and (3) 220%
  during the period beginning with 1 January 2029 and ending with 31 December
  2029."
- p.21, 4.3: "This rule modifies paragraph 4 of [...] Article 133 for a
  transitional period between 1 January 2027 and 31 December 2029, in which
  equity exposures that are higher risk equity exposures and are not within
  scope of paragraph 6 [...] shall be assigned the following risk weights:
  (1) 220% [...] 2027; (2) 280% [...] 2028; and (3) 340% [...] 2029."
- p.21, 4.6 (a firm WITH IRB permission, not implemented here): "the higher
  of: (1) the risk weight calculated using the relevant methodology [...] under
  Article 155 of CRR as that provision was in force on 31 December 2026; and
  (2) the risk weight calculated under 4.2 or 4.3."
- p.22, 4.9: "instead of using the alternative approaches set out in 4.5, 4.6
  and 4.8, an institution may choose to calculate [...] risk weights for equity
  exposures in accordance with [...] Article 133".
- p.68, Art. 133(5): "An institution shall assign a risk weight of 150% to an
  exposure that is a subordinated debt instrument, an own funds instrument or an
  equity instrument and is not classified as an equity exposure"; 133(6)(c):
  "exposures assigned a risk weight of 250% in accordance with paragraph 4 of
  Own Funds (CRR) Part Article 48."

What stays put, and why each is guarded:

- subordinated debt (150%) is not an equity exposure (Art. 133(5)), so neither
  rule reaches it;
- a significant investment (Art. 133(6)(c), Own Funds Art. 48(4)) is "within
  scope of paragraph 6" and is excluded by the words of 4.2 and 4.3;
- CIUs are weighted under Arts. 132-132C, not Art. 133 (fall-back 1,250%,
  mandate-based as supplied);
- the engine's 0% central-bank equity type is not an Art. 133(3) weight.

Each of these is green today and goes red under the naive change of the floor's
``max_horizontal`` into an assignment (sub debt and CIU mandate to 0%, the CIU
fall-back and the significant investment to 160%), and the four higher-risk
routes go red under any predicate narrower than the one that assigns 400%.

Hand calculation (EAD 1,000,000 each, Standardised firm):
    2027  listed 1,600,000   higher risk 2,200,000
    2028  listed 1,900,000   higher risk 2,800,000
    2029  listed 2,200,000   higher risk 3,400,000
    2030  listed 2,500,000   higher risk 4,000,000   (Art. 133(3) / (4))
"""

from __future__ import annotations

import dataclasses
from datetime import date
from typing import Any

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig, IRBPermissions
from rwa_calc.contracts.errors import ERROR_EQUITY_TRANSITIONAL_CONFIG
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import COUNTERPARTY_SCHEMA, EQUITY_EXPOSURE_SCHEMA, LOAN_SCHEMA
from rwa_calc.domain.enums import ApproachType, ExposureClass, PermissionMode
from rwa_calc.engine.equity.calculator import EquityCalculator
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.fixtures.raw_bundle import make_raw_bundle
from tests.fixtures.resolved_bundle import make_crm_bundle

# ---------------------------------------------------------------------------
# Scenario constants — the weights are the rule text's, not the pack's
# ---------------------------------------------------------------------------

#: (reporting date, rule 4.2 / Art. 133(3) weight, rule 4.3 / Art. 133(4) weight)
SCHEDULE = (
    (date(2027, 1, 1), 1.60, 2.20),  # first day of rule 4.2(1) / 4.3(1)
    (date(2027, 6, 30), 1.60, 2.20),
    (date(2028, 6, 30), 1.90, 2.80),  # 4.2(2) / 4.3(2)
    (date(2029, 6, 30), 2.20, 3.40),  # 4.2(3) / 4.3(3)
    (date(2029, 12, 31), 2.20, 3.40),  # last day of the transitional period
    (date(2030, 1, 1), 2.50, 4.00),  # Art. 133(3) / (4) end state
)
_SCHEDULE_IDS = [d.isoformat() for d, _, _ in SCHEDULE]
_TRANSITIONAL_DATES = [d for d, std, _ in SCHEDULE if d < date(2030, 1, 1)]

END_STATE_RW = 2.50
END_STATE_HIGHER_RISK_RW = 4.00
EAD = 1_000_000.0

#: A firm whose only IRB permission is slotting — an IRB Approach (Art. 143(2A)(a)).
SLOTTING_ONLY = IRBPermissions(
    permissions={ExposureClass.SPECIALISED_LENDING: {ApproachType.SA, ApproachType.SLOTTING}}
)

#: A permission map that names classes but grants only the Standardised Approach.
STANDARDISED_ONLY = IRBPermissions(
    permissions={
        ExposureClass.EQUITY: {ApproachType.SA},
        ExposureClass.CORPORATE: {ApproachType.SA},
    }
)

#: Rows that rule 4.2 moves: ordinary equity exposures under Art. 133(3).
STANDARD_ROWS: dict[str, dict[str, Any]] = {
    "listed": {"equity_type": "listed", "is_exchange_traded": True},
    "unlisted_established": {
        "equity_type": "other",
        "is_exchange_traded": False,
        "business_age_years": 10.0,
    },
    "government_supported": {
        "equity_type": "government_supported",
        "is_government_supported": True,
    },
}

#: Rows that rule 4.3 moves — one per route the engine takes to the 400% rung.
HIGHER_RISK_ROWS: dict[str, dict[str, Any]] = {
    "speculative_flag": {"equity_type": "other", "is_speculative": True},
    "speculative_type_without_flag": {"equity_type": "speculative"},
    "unlisted_business_age_2": {
        "equity_type": "other",
        "is_exchange_traded": False,
        "business_age_years": 2.0,
    },
    "private_equity_age_unknown": {"equity_type": "private_equity"},
}

#: Rows neither rule reaches, with the weight they keep on every date.
SURVIVING_ROWS: dict[str, tuple[dict[str, Any], float]] = {
    "subordinated_debt": ({"equity_type": "subordinated_debt"}, 1.50),
    "central_bank": ({"equity_type": "central_bank"}, 0.00),
    "ciu_fallback": ({"equity_type": "ciu", "ciu_approach": "fallback"}, 12.50),
    "ciu_no_approach": ({"equity_type": "ciu"}, 12.50),
    "ciu_mandate": (
        {"equity_type": "ciu", "ciu_approach": "mandate_based", "ciu_mandate_rw": 0.75},
        0.75,
    ),
    "significant_investment": (
        {"equity_type": "listed", "is_exchange_traded": True, "is_significant_investment": True},
        2.50,
    ),
}

_FRAME_SCHEMA: dict[str, pl.DataType] = {
    "exposure_reference": pl.String(),
    "ead_final": pl.Float64(),
    "equity_type": pl.String(),
    "is_speculative": pl.Boolean(),
    "is_exchange_traded": pl.Boolean(),
    "is_government_supported": pl.Boolean(),
    "is_significant_investment": pl.Boolean(),
    "business_age_years": pl.Float64(),
    "ciu_approach": pl.String(),
    "ciu_mandate_rw": pl.Float64(),
    "ciu_third_party_calc": pl.Boolean(),
    "ciu_look_through_rw": pl.Float64(),
    "ciu_unrestricted_access": pl.Boolean(),
}

_FLAG_DEFAULTS: dict[str, Any] = {
    "is_speculative": False,
    "is_exchange_traded": False,
    "is_government_supported": False,
    "is_significant_investment": False,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _all_rows() -> dict[str, dict[str, Any]]:
    rows = {**STANDARD_ROWS, **HIGHER_RISK_ROWS}
    rows.update({name: spec for name, (spec, _) in SURVIVING_ROWS.items()})
    return rows


def _frame(rows: dict[str, dict[str, Any]]) -> pl.LazyFrame:
    records = [
        {"exposure_reference": ref, "ead_final": EAD, **_FLAG_DEFAULTS, **spec}
        for ref, spec in rows.items()
    ]
    return pl.DataFrame(records, schema=_FRAME_SCHEMA).lazy()


def _config(
    on: date,
    *,
    permission_mode: PermissionMode = PermissionMode.STANDARDISED,
    **equity_transitional: Any,
) -> CalculationConfig:
    config = CalculationConfig.basel_3_1(reporting_date=on, permission_mode=permission_mode)
    if not equity_transitional:
        return config
    return dataclasses.replace(
        config,
        equity_transitional=dataclasses.replace(config.equity_transitional, **equity_transitional),
    )


def _branch(config: CalculationConfig, rows: dict[str, dict[str, Any]] | None = None) -> dict:
    out = EquityCalculator().calculate_branch(_frame(rows or _all_rows()), config).collect()
    return {r["exposure_reference"]: r for r in out.to_dicts()}


def _bundle_errors(config: CalculationConfig) -> list:
    bundle = make_crm_bundle(exposures=pl.LazyFrame(), equity_exposures=_frame(STANDARD_ROWS))
    return [
        e
        for e in EquityCalculator().get_equity_result_bundle(bundle, config).errors
        if e.code == ERROR_EQUITY_TRANSITIONAL_CONFIG
    ]


# ---------------------------------------------------------------------------
# Rules 4.2 / 4.3 — a firm without IRB permission
# ---------------------------------------------------------------------------


class TestRule42AssignsTheStandardWeight:
    """Rule 4.2: ordinary equity takes 160% / 190% / 220%, then 250% from 2030."""

    @pytest.mark.parametrize(("on", "std_rw", "hr_rw"), SCHEDULE, ids=_SCHEDULE_IDS)
    @pytest.mark.parametrize("row", sorted(STANDARD_ROWS))
    def test_standard_equity_takes_the_rule_4_2_weight(
        self, row: str, on: date, std_rw: float, hr_rw: float
    ) -> None:
        # Arrange / Act
        result = _branch(_config(on))[row]

        # Assert
        assert result["risk_weight"] == pytest.approx(std_rw)
        assert result["rwa"] == pytest.approx(EAD * std_rw)


class TestRule43AssignsTheHigherRiskWeight:
    """Rule 4.3: higher risk equity takes 220% / 280% / 340%, then 400% from 2030.

    One row per route to the Art. 133(4) rung. A transitional predicate that is
    narrower than the one that assigned 400% gives the missing routes 160%.
    """

    @pytest.mark.parametrize(("on", "std_rw", "hr_rw"), SCHEDULE, ids=_SCHEDULE_IDS)
    @pytest.mark.parametrize("row", sorted(HIGHER_RISK_ROWS))
    def test_higher_risk_equity_takes_the_rule_4_3_weight(
        self, row: str, on: date, std_rw: float, hr_rw: float
    ) -> None:
        # Arrange / Act
        result = _branch(_config(on))[row]

        # Assert
        assert result["risk_weight"] == pytest.approx(hr_rw)
        assert result["rwa"] == pytest.approx(EAD * hr_rw)


class TestExcludedExposuresKeepTheirWeight:
    """Art. 133(5), Art. 133(6)(c), CIUs and the central-bank type are outside 4.2 / 4.3."""

    @pytest.mark.parametrize("on", _TRANSITIONAL_DATES, ids=str)
    @pytest.mark.parametrize("row", sorted(SURVIVING_ROWS))
    def test_excluded_row_keeps_its_weight(self, row: str, on: date) -> None:
        # Arrange
        _, expected = SURVIVING_ROWS[row]

        # Act
        result = _branch(_config(on))[row]

        # Assert
        assert result["risk_weight"] == pytest.approx(expected)


# ---------------------------------------------------------------------------
# Rule 4.1 — the firm fact
# ---------------------------------------------------------------------------


class TestRule41FirmWithIrbPermission:
    """A firm that had IRB permission (F-IRB, A-IRB or slotting) is outside rules 4.2 / 4.3.

    Its own rules (4.5(1): the 4.2 / 4.3 weights for equity it held under
    Standardised permission; 4.6: the higher of the legacy Art. 155 weight and
    the 4.2 / 4.3 weight for equity it held under the IRB Approach) are not
    implemented, so it keeps the Art. 133 weights — which is the rule 4.9
    election — and the run says so with a warning. A map that grants only the
    Standardised Approach is the negative control: it is no IRB permission.
    """

    def test_irb_firm_keeps_the_article_133_weights(self) -> None:
        # Arrange
        config = _config(date(2027, 6, 30), permission_mode=PermissionMode.IRB)

        # Act
        result = _branch(config)

        # Assert
        assert result["listed"]["risk_weight"] == pytest.approx(END_STATE_RW)
        assert result["unlisted_business_age_2"]["risk_weight"] == pytest.approx(
            END_STATE_HIGHER_RISK_RW
        )

    def test_irb_firm_without_the_rule_4_9_election_is_warned(self) -> None:
        # Arrange
        config = _config(date(2027, 6, 30), permission_mode=PermissionMode.IRB)

        # Act
        warnings = _bundle_errors(config)

        # Assert
        assert len(warnings) == 1
        assert "4.6" in warnings[0].message
        assert "4.9" in warnings[0].message

    def test_the_warning_names_both_rules_the_engine_does_not_apply(self) -> None:
        """Rule 4.5(1) (4.2 / 4.3 weights for equity under SA permission) and 4.6 (higher-of).

        p.21, 4.5: "(1) apply the approaches in 4.2 and 4.3 for equity exposures
        for which, on 31 December 2026, the institution had permission to apply
        the Standardised Approach under Article 148 of CRR or Article 150 of CRR;
        and (2) apply the approach in 4.6 for equity exposures for which [...] the
        institution had permission to apply the Internal Ratings Based Approach".
        The message is built before the equity frame is materialised, so it is
        conditional on the firm holding Art. 133 equity rather than gated on it.
        """
        # Arrange
        config = _config(date(2027, 6, 30), permission_mode=PermissionMode.IRB)

        # Act
        message = _bundle_errors(config)[0].message

        # Assert
        assert "4.5(1)" in message
        assert "Article 148" in message
        assert "if the firm holds Art. 133 equity" in message

    def test_a_slotting_only_firm_had_irb_permission(self) -> None:
        """A firm whose only IRB permission is slotting is outside rule 4.1.

        p.81, Art. 143(2A): an application names "one or more of the following IRB
        Approaches instead of the Standardised Approach: (a) the Slotting
        Approach; (b) the Foundation IRB Approach; or (c) the Advanced IRB
        Approach"; p.102, Art. 153(5): "The Slotting Approach applies as follows
        for specialised lending exposures". Weighting such a firm's listed equity
        at 160% would understate it by 36% against the Art. 133 weight it keeps.
        """
        # Arrange
        config = dataclasses.replace(
            _config(date(2027, 6, 30), permission_mode=PermissionMode.IRB),
            irb_permissions=SLOTTING_ONLY,
        )

        # Act
        result = _branch(config)
        warnings = _bundle_errors(config)

        # Assert
        assert result["listed"]["risk_weight"] == pytest.approx(END_STATE_RW)
        assert result["listed"]["equity_transitional_approach"] is None
        assert len(warnings) == 1

    def test_a_slotting_only_firm_that_made_the_rule_4_9_election_is_not_warned(self) -> None:
        """A slotting-only firm's ``opt_out`` is the rule 4.9 election, and is honoured.

        p.21, 4.4: rules 4.5 to 4.6 apply "to an institution which, on 31
        December 2026, had permission to apply the Internal Ratings Based
        Approach under Article 143 of CRR", which a slotting-only firm had; p.22,
        4.9: such a firm "may choose to calculate [...] risk weights for equity
        exposures in accordance with [...] Article 133, instead of in accordance
        with the two approaches set out in 4.5 and 4.6". So it keeps 250% with
        no transitional label, and is warned of nothing: not that it has failed
        to elect (it has), nor that it elected without IRB permission (it had
        one).

        The empty warning list is the assertion that matters. Were ``opt_out``
        honoured only for an F-IRB / A-IRB firm, this firm would be warned that
        it had not elected while its weight and carriers stayed exactly as here.
        """
        # Arrange
        config = dataclasses.replace(
            _config(date(2027, 6, 30), permission_mode=PermissionMode.IRB, opt_out=True),
            irb_permissions=SLOTTING_ONLY,
        )

        # Act
        result = _branch(config)
        warnings = _bundle_errors(config)

        # Assert
        assert result["listed"]["risk_weight"] == pytest.approx(END_STATE_RW)
        assert result["listed"]["equity_transitional_approach"] is None
        assert warnings == []

    @pytest.mark.parametrize(
        "mode", [PermissionMode.IRB, PermissionMode.STANDARDISED], ids=lambda m: m.name.lower()
    )
    def test_a_map_permitting_only_the_standardised_approach_is_not_irb_permission(
        self, mode: PermissionMode
    ) -> None:
        """The negative control for rule 4.1's firm fact: what the map grants, not its shape.

        p.20, 4.1 turns on "permission to use the Internal Ratings Based Approach
        under Article 143 of CRR". A map that names equity and corporates but
        grants each only the Standardised Approach grants no IRB Approach
        (Art. 143(2A) lists slotting, F-IRB and A-IRB), so the firm is inside rule
        4.1 and its listed equity takes the rule 4.2(1) 160% in 2027, labelled,
        with no CFG003. Every other config in this file has an empty map, a
        full-IRB map or a slotting map, so none of them can tell the derivation
        from one keyed on the run being in IRB mode, or on the map being
        non-empty. The IRB-mode case catches both; the Standardised-mode case
        catches the second.
        """
        # Arrange
        config = dataclasses.replace(
            _config(date(2027, 6, 30), permission_mode=mode), irb_permissions=STANDARDISED_ONLY
        )

        # Act
        result = _branch(config)
        warnings = _bundle_errors(config)

        # Assert
        assert result["listed"]["risk_weight"] == pytest.approx(1.60)
        assert result["listed"]["equity_transitional_approach"] == "sa_transitional"
        assert warnings == []

    def test_irb_firm_that_made_the_rule_4_9_election_is_not_warned(self) -> None:
        # Arrange
        config = _config(date(2027, 6, 30), permission_mode=PermissionMode.IRB, opt_out=True)

        # Act / Assert
        assert _bundle_errors(config) == []

    def test_no_warning_outside_the_transitional_period(self) -> None:
        # Arrange
        config = _config(date(2030, 1, 1), permission_mode=PermissionMode.IRB)

        # Act / Assert
        assert _bundle_errors(config) == []

    def test_explicit_irb_permission_overrides_a_standardised_config(self) -> None:
        # Arrange: an IRB firm running a Standardised shadow run states the fact.
        config = _config(date(2027, 6, 30), irb_permission_at_2026_year_end=True)

        # Act
        result = _branch(config)

        # Assert
        assert result["listed"]["risk_weight"] == pytest.approx(END_STATE_RW)
        assert len(_bundle_errors(config)) == 1

    def test_explicit_no_irb_permission_overrides_an_irb_config(self) -> None:
        # Arrange: permission granted after 31 December 2026 does not count.
        config = _config(
            date(2027, 6, 30),
            permission_mode=PermissionMode.IRB,
            irb_permission_at_2026_year_end=False,
        )

        # Act
        result = _branch(config)

        # Assert
        assert result["listed"]["risk_weight"] == pytest.approx(1.60)


class TestRule49IsNotAvailableToAStandardisedFirm:
    """Rule 4.9 replaces only 4.5, 4.6 and 4.8; a 4.1 firm has nothing to elect."""

    def test_opt_out_does_not_restore_250_percent(self) -> None:
        # Arrange
        config = _config(date(2027, 6, 30), opt_out=True)

        # Act
        result = _branch(config)

        # Assert
        assert result["listed"]["risk_weight"] == pytest.approx(1.60)

    def test_ignored_opt_out_is_warned(self) -> None:
        # Arrange
        config = _config(date(2027, 6, 30), opt_out=True)

        # Act
        warnings = _bundle_errors(config)

        # Assert
        assert len(warnings) == 1
        assert "4.9" in warnings[0].message

    def test_standardised_firm_without_opt_out_is_not_warned(self) -> None:
        # Act / Assert
        assert _bundle_errors(_config(date(2027, 6, 30))) == []


# ---------------------------------------------------------------------------
# Full pipeline — the capital reaches the sealed results frame
# ---------------------------------------------------------------------------

_CP_EQUITY = "CP-O01-EQ"
_CP_CORP = "CP-O01-CORP"
_EQ_LISTED = "EQ-O01-LISTED"
_EQ_YOUNG = "EQ-O01-UNLISTED-YOUNG"
_EQ_SUB_DEBT = "EQ-O01-SUB-DEBT"
_EQ_SIGNIFICANT = "EQ-O01-SIGNIFICANT"
_EQ_CIU = "EQ-O01-CIU-FALLBACK"
_LN_CORP = "LN-O01-CORP"

#: (reference, EAD, 2027 weight under rules 4.1-4.3, end-state Art. 133 weight)
_PIPELINE_LEGS = (
    (_EQ_LISTED, 1_000_000.0, 1.60, 2.50),
    (_EQ_YOUNG, 500_000.0, 2.20, 4.00),
    (_EQ_SUB_DEBT, 200_000.0, 1.50, 1.50),
    (_EQ_SIGNIFICANT, 300_000.0, 2.50, 2.50),
    (_EQ_CIU, 400_000.0, 12.50, 12.50),
)


def _pipeline_bundle():
    counterparties = pl.DataFrame(
        [
            {
                "counterparty_reference": ref,
                "counterparty_name": ref,
                "entity_type": "corporate",
                "country_code": "GB",
                "is_natural_person": False,
                "is_managed_as_retail": False,
                "default_status": False,
            }
            for ref in (_CP_EQUITY, _CP_CORP)
        ],
        schema_overrides=dtypes_of(COUNTERPARTY_SCHEMA),
    )
    loans = pl.DataFrame(
        [
            {
                "loan_reference": _LN_CORP,
                "counterparty_reference": _CP_CORP,
                "product_type": "term_loan",
                "drawn_amount": 1_000_000.0,
                "currency": "GBP",
                "value_date": date(2020, 1, 1),
                "maturity_date": date(2032, 1, 1),
                "seniority": "senior",
                "is_defaulted": False,
            }
        ],
        schema_overrides=dtypes_of(LOAN_SCHEMA),
    )
    specs: dict[str, dict[str, Any]] = {
        _EQ_LISTED: {"equity_type": "listed", "is_exchange_traded": True},
        _EQ_YOUNG: {"equity_type": "other", "business_age_years": 2.0},
        _EQ_SUB_DEBT: {"equity_type": "subordinated_debt"},
        _EQ_SIGNIFICANT: {
            "equity_type": "listed",
            "is_exchange_traded": True,
            "is_significant_investment": True,
        },
        _EQ_CIU: {"equity_type": "ciu", "ciu_approach": "fallback"},
    }
    equity = pl.DataFrame(
        [
            {
                "exposure_reference": ref,
                "counterparty_reference": _CP_EQUITY,
                "currency": "GBP",
                "carrying_value": ead,
                "fair_value": ead,
                **specs[ref],
            }
            for ref, ead, _, _ in _PIPELINE_LEGS
        ],
        schema_overrides=dtypes_of(EQUITY_EXPOSURE_SCHEMA),
    )
    return make_raw_bundle(counterparties=counterparties, loans=loans, equity_exposures=equity)


@pytest.fixture(scope="module")
def pipeline_2027():
    config = _config(date(2027, 6, 30))
    return PipelineOrchestrator().run_with_data(_pipeline_bundle(), config)


class TestPipelineCarriesTheTransitionalCapital:
    """Through the full pipeline, a Standardised firm in 2027 (rules 4.1-4.3)."""

    def test_the_portfolio_holds_moving_and_surviving_legs(self) -> None:
        # Adequacy: two legs the rules move and three they must not.
        moving = [ref for ref, _, rw, end in _PIPELINE_LEGS if rw != end]
        surviving = [ref for ref, _, rw, end in _PIPELINE_LEGS if rw == end]
        assert len(moving) == 2
        assert len(surviving) == 3

    @pytest.mark.parametrize(
        ("reference", "ead", "rw", "end_state_rw"),
        _PIPELINE_LEGS,
        ids=[ref for ref, *_ in _PIPELINE_LEGS],
    )
    def test_sealed_leg_carries_the_rule_weight_and_rwea(
        self, pipeline_2027, reference: str, ead: float, rw: float, end_state_rw: float
    ) -> None:
        # Arrange
        ledger = pipeline_2027.results.collect()

        # Act
        rows = ledger.filter(pl.col("exposure_reference") == reference).to_dicts()

        # Assert
        assert len(rows) == 1, f"{reference} did not reach the sealed results frame"
        assert rows[0]["risk_weight"] == pytest.approx(rw)
        assert rows[0]["rwa_final"] == pytest.approx(ead * rw)
        assert rows[0]["sa_rwa"] == pytest.approx(ead * rw)

    def test_standardised_run_raises_no_equity_transitional_warning(self, pipeline_2027) -> None:
        # Act
        codes = [e.code for e in pipeline_2027.errors]

        # Assert
        assert ERROR_EQUITY_TRANSITIONAL_CONFIG not in codes

    def test_irb_run_reports_the_warning_through_the_stage_error_channel(self) -> None:
        # Arrange
        config = _config(date(2027, 6, 30), permission_mode=PermissionMode.IRB)

        # Act
        result = PipelineOrchestrator().run_with_data(_pipeline_bundle(), config)
        ledger = result.results.collect()
        listed = ledger.filter(pl.col("exposure_reference") == _EQ_LISTED).to_dicts()[0]

        # Assert
        assert listed["rwa_final"] == pytest.approx(1_000_000.0 * END_STATE_RW)
        assert [e.code for e in result.errors].count(ERROR_EQUITY_TRANSITIONAL_CONFIG) == 1
