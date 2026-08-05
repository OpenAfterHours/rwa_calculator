"""
Unit tests for the RD-8 "other funded credit protection" (OFCP) routing
defect in ``engine/crm/``.

PS1/26 col 0060 (``docs/plans/irb-collateral-corep-reporting.md``, RD-8),
verbatim: "Other funded credit protection that is treated as a guarantee in
accordance with Article 232 ... shall be included [in 0060]. ... Other
funded credit protection recognised by firms applying the AIRB approach and
using the LGD Modelling Collateral Method shall be reported in columns
0171, 0172 and 0173." PS1/26 p.107 (repeated for cols 0171/0172/0173): "The
value of collateral reported shall be limited to the value of the exposure
at the level of an individual exposure."

The routing decision depends on the run-level ``AIRBCollateralMethod``
election, which never reaches the COREP generator (``generate_c08_01`` and
siblings take only ``(results, cols, framework, errors)``). RD-8 records
that ``engine/crm/`` -- which already holds the config and pack and already
computes ``airb_lgd_preserved_expr`` -- must make the decision ONCE and emit
three mutually-exclusive-by-construction amounts, built from the two
existing Art. 200(1) carriers:

    third_party_deposit_value (Art. 200(1)(a), engine/crm/third_party_deposit.py)
    life_ins_collateral_value (Art. 200(1)(b), engine/crm/life_insurance.py)

        ->  ofcp_lgd_cash_deposit    (route condition true: third_party_deposit_value)
        ->  ofcp_lgd_life_insurance  (route condition true: life_ins_collateral_value)
        ->  ofcp_substitution_amount (route condition false: the sum of both)

Route condition: the leg's own approach is A-IRB AND the firm has elected
the LGD Modelling Collateral Method (``AIRBCollateralMethod.LGD_MODELLING``,
gated by the Basel-3.1-only pack Feature
``airb_lgd_collateral_method_applicable``).

Both source carriers are ALREADY capped at the exposure value by their
existing producers (``third_party_deposit.py``:
``pl.min_horizontal(inst_value, ead)``; ``life_insurance.py``:
``pl.min_horizontal(total_value, ead)``), so PS1/26 p.107's per-exposure cap
is a property the routing must PRESERVE, not (re-)apply.

DECIDED, not left ambiguous -- settled twice against the implementer, with
code evidence, and now final: today ``compute_third_party_deposit_columns``
zeroes ``third_party_deposit_value`` for EVERY IRB approach
(``is_firb = approach.is_in([FIRB, AIRB])``, ``third_party_deposit.py:140``,
with a CRM017 "F-IRB holder-RW substitution is a deferred follow-up"
warning) -- including A-IRB (verified empirically, pre-fix: both FIRB and
AIRB legs give ``third_party_deposit_value == 0.0``; SA gives the real
value, since SA is not in that gate at all). The variable name and the
F-IRB-only warning text are inconsistent with also gating A-IRB, but
**narrowing the gate is explicitly OUT OF SCOPE for this branch and stays
out permanently**: the obvious argument for narrowing -- "no A-IRB capital
consumes this column" -- is WRONG. ``engine/sa/calculator.py:85-91``'s own
docstring: "Operates on the full unified frame (SA + IRB + slotting rows
together). Only modifies the RWA column for rows where approach ==
'standardised'; the risk-weight pipeline itself runs unconditionally so
that all rows carry an SA-equivalent RW used by the IRB output floor." That
pipeline runs ``apply_third_party_deposit_rw_mapping`` unconditionally
(:110-118) before ``sa_rwa = ead x risk_weight`` is taken for ALL rows
(:128-135) -- so populating the carrier on an A-IRB leg would lower its
SA-equivalent RW and hence the Basel 3.1 output floor wherever it binds.
Narrowing the gate is therefore an RWA-REDUCING capital change via the
output floor, unreviewed and outside "reporting-basis correctness". It is a
recorded, DECLINED follow-up (with this refutation attached in the plan),
not part of RD-8.

Consequence, load-bearing for every A-IRB fixture in this file:
``ofcp_lgd_cash_deposit`` is 0.0 on EVERY A-IRB leg, on EVERY route
(LGD_MODELLING, FOUNDATION, or CRR) -- not because the routing failed to
recognise the deposit, but because its SOURCE (``third_party_deposit_value``)
is already zero by the time the routing runs. A 0.0 that traces to this
upstream deferral is the correct, EXPECTED outcome; only
``ofcp_lgd_life_insurance`` (routed from ``life_ins_collateral_value``,
which carries NO approach gate at all) demonstrates the LGD-carrier route
on an A-IRB leg in this file. The conservation tests (section 7) check
against the ACTUAL source values the producers emit on each fixture, not
against the raw pledge amounts, precisely so a deferred source reads as "no
value to conserve" rather than "value the routing destroyed".

References:
    PRA PS1/26 Annex II, cols 0060/0171/0172/0173
    docs/plans/irb-collateral-corep-reporting.md, RD-8
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest
from tests.fixtures.resolved_bundle import make_classified_bundle
from tests.unit.crm._crm_bundles import (
    empty_counterparty_lookup,
    normalise_collateral,
    with_ancestor_facilities,
)

from rwa_calc.contracts.bundles import ClassifiedExposuresBundle, CRMAdjustedBundle
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import AIRBCollateralMethod, ApproachType, ExposureClass, PermissionMode
from rwa_calc.engine.crm.processor import CRMProcessor

# =============================================================================
# Fixtures / helpers
# =============================================================================


@pytest.fixture
def processor() -> CRMProcessor:
    return CRMProcessor()


def _b31_config(method: AIRBCollateralMethod) -> CalculationConfig:
    return CalculationConfig.basel_3_1(
        reporting_date=date(2030, 6, 30),
        permission_mode=PermissionMode.IRB,
        airb_collateral_method=method,
    )


def _crr_config() -> CalculationConfig:
    return CalculationConfig.crr(
        reporting_date=date(2024, 12, 31),
        permission_mode=PermissionMode.IRB,
    )


def _exposure_row(
    ref: str = "EXP1",
    approach: str = ApproachType.AIRB.value,
    ead: float = 1_000_000.0,
    cp_ref: str = "CP1",
) -> pl.LazyFrame:
    """One senior corporate IRB loan (mirrors test_p1_235's proven shape).

    Carries ``original_currency`` explicitly (== ``currency``, both "GBP"):
    ``compute_life_insurance_columns`` matches each policy's currency against
    the exposure's PRE-conversion denomination
    (``denomination_currency_expr``), which reads ``original_currency`` when
    the column is present at all -- even as an all-null placeholder from an
    earlier pipeline step -- falling back to ``currency`` only when the
    column is wholly ABSENT. Omitting it here would silently apply the
    Art. 233(3) 8% FX cut to every matched-currency life-insurance pledge
    (an unrelated confound this file's tests must not carry).
    """
    return (
        pl.DataFrame(
            {
                "exposure_reference": [ref],
                "counterparty_reference": [cp_ref],
                "parent_facility_reference": [None],
                "exposure_class": [ExposureClass.CORPORATE.value],
                "approach": [approach],
                "drawn_amount": [ead],
                "ead_gross": [ead],
                "lgd": [None],
                "pd": [0.02],
                "maturity_date": [date(2029, 12, 31)],
                "currency": ["GBP"],
                "original_currency": ["GBP"],
                "seniority": ["senior"],
                "exposure_type": ["loan"],
                "nominal_amount": [0.0],
                "interest": [0.0],
                "undrawn_amount": [0.0],
                "risk_type": [None],
                "ccf_modelled": [None],
                "is_short_term_trade_lc": [False],
                "product_type": ["TERM_LOAN"],
                "value_date": [date(2024, 1, 1)],
                "book_code": ["BOOK1"],
                "is_sft": [False],
            }
        )
        .lazy()
        .with_columns(pl.col("parent_facility_reference").cast(pl.String))
    )


def _life_insurance_row(beneficiary_ref: str, market_value: float, ref: str = "LI1") -> dict:
    """One Art. 200(1)(b) life-insurance policy pledge."""
    return {
        "collateral_reference": ref,
        "collateral_type": "life_insurance",
        "currency": "GBP",
        "market_value": market_value,
        "beneficiary_type": "loan",
        "beneficiary_reference": beneficiary_ref,
        "maturity_date": date(2035, 12, 31),
        "issuer_type": "",
        "issuer_cqs": 1,
        "is_main_index": False,
        "is_eligible_financial_collateral": False,
        "is_eligible_irb_collateral": True,
        "residual_maturity_years": 10.0,
        "original_maturity_years": 10.0,
        "liquidation_period_days": 10,
        "insurer_risk_weight": 1.0,
        "held_by_counterparty_reference": None,
    }


def _third_party_deposit_row(beneficiary_ref: str, market_value: float, ref: str = "TPD1") -> dict:
    """One Art. 200(1)(a) third-party (institution-held) cash deposit pledge."""
    return {
        "collateral_reference": ref,
        "collateral_type": "cash",
        "currency": "GBP",
        "market_value": market_value,
        "beneficiary_type": "loan",
        "beneficiary_reference": beneficiary_ref,
        "maturity_date": date(2035, 12, 31),
        "issuer_type": "institution",
        "issuer_cqs": 2,
        "is_main_index": False,
        "is_eligible_financial_collateral": True,
        "is_eligible_irb_collateral": True,
        "residual_maturity_years": 10.0,
        "original_maturity_years": 10.0,
        "liquidation_period_days": 10,
        "insurer_risk_weight": None,
        "held_by_counterparty_reference": "THIRD_PARTY_BANK",
    }


def _make_bundle(exposures: pl.LazyFrame, collateral_rows: list[dict]) -> ClassifiedExposuresBundle:
    exposures = with_ancestor_facilities(exposures)
    collateral = normalise_collateral(pl.DataFrame(collateral_rows).lazy())
    return make_classified_bundle(
        all_exposures=exposures,
        equity_exposures=None,
        collateral=collateral,
        guarantees=None,
        provisions=None,
        counterparty_lookup=empty_counterparty_lookup(),
        classification_audit=None,
        classification_errors=[],
    )


def _run_crm(
    processor: CRMProcessor,
    config: CalculationConfig,
    bundle: ClassifiedExposuresBundle,
) -> pl.DataFrame:
    result: CRMAdjustedBundle = processor.get_crm_unified_bundle(bundle, config)
    return result.exposures.collect()


# =============================================================================
# 1. B3.1 A-IRB + LGD_MODELLING -> routes to the two LGD carriers
# =============================================================================


class TestLgdModellingElectionRoutesToLgdCarriers:
    """RD-8 assertion #1."""

    def test_airb_lgd_modelling_routes_life_insurance(self, processor: CRMProcessor) -> None:
        """``ofcp_lgd_life_insurance`` carries the life-policy value (its
        source, ``life_ins_collateral_value``, carries no approach gate).
        ``ofcp_lgd_cash_deposit`` is 0.0 -- NOT because the routing failed
        to pick up the deposit, but because ``third_party_deposit_value``
        is ALREADY 0.0 by the time the routing runs: the F-IRB/A-IRB
        deferral in ``third_party_deposit.py:140`` (CRM017) is a deliberate,
        out-of-scope-for-this-branch decision (see module docstring), not
        touched here. ``ofcp_substitution_amount`` is 0.0 too, since there
        is nothing left to route there once the deposit itself is zero.
        """
        # Arrange
        exposures = _exposure_row(approach=ApproachType.AIRB.value, ead=1_000_000.0)
        collateral = [
            _life_insurance_row("EXP1", 200_000.0),
            _third_party_deposit_row("EXP1", 150_000.0),
        ]
        bundle = _make_bundle(exposures, collateral)
        config = _b31_config(AIRBCollateralMethod.LGD_MODELLING)

        # Act
        df = _run_crm(processor, config, bundle)
        row = df.filter(pl.col("exposure_reference") == "EXP1")

        # Assert
        assert row["ofcp_lgd_life_insurance"][0] == pytest.approx(200_000.0)
        assert row["ofcp_lgd_cash_deposit"][0] == pytest.approx(0.0)
        assert row["ofcp_substitution_amount"][0] == pytest.approx(0.0)


# =============================================================================
# 2. B3.1 A-IRB + FOUNDATION -> the mirror: substitution carries the sum
# =============================================================================


class TestFoundationElectionRoutesToSubstitutionCarrier:
    """RD-8 assertion #2."""

    def test_airb_foundation_routes_life_insurance_to_substitution(
        self, processor: CRMProcessor
    ) -> None:
        """``ofcp_substitution_amount`` is 200,000 (life insurance only),
        NOT 350,000: the third-party deposit's source is 0.0 on this A-IRB
        leg regardless of election (see module docstring) -- FOUNDATION
        changes WHERE the life-insurance amount routes (here, not the two
        LGD carriers), it does not resurrect the deferred deposit."""
        # Arrange: identical fixture, FOUNDATION election instead.
        exposures = _exposure_row(approach=ApproachType.AIRB.value, ead=1_000_000.0)
        collateral = [
            _life_insurance_row("EXP1", 200_000.0),
            _third_party_deposit_row("EXP1", 150_000.0),
        ]
        bundle = _make_bundle(exposures, collateral)
        config = _b31_config(AIRBCollateralMethod.FOUNDATION)

        # Act
        df = _run_crm(processor, config, bundle)
        row = df.filter(pl.col("exposure_reference") == "EXP1")

        # Assert
        assert row["ofcp_substitution_amount"][0] == pytest.approx(200_000.0)
        assert row["ofcp_lgd_cash_deposit"][0] == pytest.approx(0.0)
        assert row["ofcp_lgd_life_insurance"][0] == pytest.approx(0.0)


# =============================================================================
# 3. CRR A-IRB -> substitution route, unchanged (the regression that matters
#    most: the Basel-3.1-only Feature means the LGD-Modelling route can
#    never arise under CRR)
# =============================================================================


class TestCrrAirbRoutesToSubstitutionUnchanged:
    """RD-8 assertion #3 -- the regression guard that matters most: a CRR
    A-IRB leg must never take the LGD-Modelling route (the Feature is
    Basel-3.1-only)."""

    def test_crr_airb_routes_life_insurance_to_substitution(self, processor: CRMProcessor) -> None:
        """200,000 (life insurance), NOT 350,000 -- same reason as the
        FOUNDATION case: the deposit's source is already 0.0 on this A-IRB
        leg (untouched, out of this branch's scope). The structural point
        this test exists for is unaffected: neither LGD carrier is
        populated under CRR, ruling out an accidental LGD-Modelling route."""
        # Arrange
        exposures = _exposure_row(approach=ApproachType.AIRB.value, ead=1_000_000.0)
        collateral = [
            _life_insurance_row("EXP1", 200_000.0),
            _third_party_deposit_row("EXP1", 150_000.0),
        ]
        bundle = _make_bundle(exposures, collateral)
        config = _crr_config()

        # Act
        df = _run_crm(processor, config, bundle)
        row = df.filter(pl.col("exposure_reference") == "EXP1")

        # Assert
        assert row["ofcp_substitution_amount"][0] == pytest.approx(200_000.0)
        assert row["ofcp_lgd_cash_deposit"][0] == pytest.approx(0.0)
        assert row["ofcp_lgd_life_insurance"][0] == pytest.approx(0.0)


# =============================================================================
# 4. F-IRB and SA legs -> substitution route
# =============================================================================


class TestNonAirbLegsRouteToSubstitution:
    """RD-8 assertion #4: the LGD-Modelling route requires the LEG's own
    approach to be A-IRB -- electing LGD_MODELLING at firm level does not
    pull an F-IRB or SA leg onto the LGD carriers."""

    def test_firb_leg_routes_to_substitution_even_under_lgd_modelling_election(
        self, processor: CRMProcessor
    ) -> None:
        """F-IRB's substitution total is 200,000 (life insurance only), NOT
        350,000: ``third_party_deposit.py`` already deferred the third-party
        deposit's benefit to 0.0 for F-IRB specifically, citing Art. 232's
        F-IRB holder-RW substitution as "a deferred follow-up" (CRM017,
        unconditional on this leg's collateral method -- verified
        empirically pre-fix). CONFIRMED (team-lead, after this file's first
        revision): the deferral -- for BOTH F-IRB and A-IRB -- is
        intentionally out of scope for RD-8, so 200,000 is the correct,
        final expected value here, not a flagged guess.
        """
        # Arrange
        exposures = _exposure_row(approach=ApproachType.FIRB.value, ead=1_000_000.0)
        collateral = [
            _life_insurance_row("EXP1", 200_000.0),
            _third_party_deposit_row("EXP1", 150_000.0),
        ]
        bundle = _make_bundle(exposures, collateral)
        config = _b31_config(AIRBCollateralMethod.LGD_MODELLING)

        # Act
        df = _run_crm(processor, config, bundle)
        row = df.filter(pl.col("exposure_reference") == "EXP1")

        # Assert
        assert row["ofcp_substitution_amount"][0] == pytest.approx(200_000.0)
        assert row["ofcp_lgd_cash_deposit"][0] == pytest.approx(0.0)
        assert row["ofcp_lgd_life_insurance"][0] == pytest.approx(0.0)

    def test_sa_leg_routes_to_substitution_even_under_lgd_modelling_election(
        self, processor: CRMProcessor
    ) -> None:
        # Arrange
        exposures = _exposure_row(approach=ApproachType.SA.value, ead=1_000_000.0)
        collateral = [
            _life_insurance_row("EXP1", 200_000.0),
            _third_party_deposit_row("EXP1", 150_000.0),
        ]
        bundle = _make_bundle(exposures, collateral)
        config = _b31_config(AIRBCollateralMethod.LGD_MODELLING)

        # Act
        df = _run_crm(processor, config, bundle)
        row = df.filter(pl.col("exposure_reference") == "EXP1")

        # Assert
        assert row["ofcp_substitution_amount"][0] == pytest.approx(350_000.0)
        assert row["ofcp_lgd_cash_deposit"][0] == pytest.approx(0.0)
        assert row["ofcp_lgd_life_insurance"][0] == pytest.approx(0.0)


# =============================================================================
# 5. Structural exclusivity as ONE invariant over a parametrized matrix
# =============================================================================


def _exclusivity_cases() -> list[tuple[str, str, CalculationConfig]]:
    """(case_id, approach, config) covering every route in this file."""
    return [
        (
            "airb_b31_lgd_modelling",
            ApproachType.AIRB.value,
            _b31_config(AIRBCollateralMethod.LGD_MODELLING),
        ),
        (
            "airb_b31_foundation",
            ApproachType.AIRB.value,
            _b31_config(AIRBCollateralMethod.FOUNDATION),
        ),
        ("airb_crr", ApproachType.AIRB.value, _crr_config()),
        (
            "firb_b31_lgd_modelling",
            ApproachType.FIRB.value,
            _b31_config(AIRBCollateralMethod.LGD_MODELLING),
        ),
        (
            "sa_b31_lgd_modelling",
            ApproachType.SA.value,
            _b31_config(AIRBCollateralMethod.LGD_MODELLING),
        ),
    ]


class TestStructuralExclusivity:
    """RD-8 assertion #5: exactly one of the two routes is ever populated per
    leg -- pinned as ONE invariant over every case in this file's matrix,
    the property that makes ``{c0170} = {c0171}+{c0172}+{c0173}`` (and the
    0060/0171/0172 mutual exclusivity) hold by construction rather than by a
    reporting-layer convention."""

    @pytest.mark.parametrize(
        ("case_id", "approach", "config"),
        _exclusivity_cases(),
        ids=lambda c: c if isinstance(c, str) else None,
    )
    def test_lgd_and_substitution_routes_are_mutually_exclusive(
        self,
        processor: CRMProcessor,
        case_id: str,
        approach: str,
        config: CalculationConfig,
    ) -> None:
        # Arrange
        exposures = _exposure_row(approach=approach, ead=1_000_000.0)
        collateral = [
            _life_insurance_row("EXP1", 200_000.0),
            _third_party_deposit_row("EXP1", 150_000.0),
        ]
        bundle = _make_bundle(exposures, collateral)

        # Act
        df = _run_crm(processor, config, bundle)
        row = df.filter(pl.col("exposure_reference") == "EXP1")
        lgd_total = row["ofcp_lgd_cash_deposit"][0] + row["ofcp_lgd_life_insurance"][0]
        substitution = row["ofcp_substitution_amount"][0]

        # Assert: exactly one side is nonzero (the fixture always carries a
        # nonzero total, so this also rules out "both zero").
        assert (lgd_total > 0) != (substitution > 0), (
            f"[{case_id}] expected exactly one route populated, got "
            f"lgd_total={lgd_total}, substitution={substitution}"
        )


# =============================================================================
# 6. Per-exposure cap (PS1/26 p.107)
# =============================================================================


class TestPerExposureCap:
    """RD-8 assertion #6: a 500,000 policy against a 300,000 exposure gives
    300,000 -- capped per exposure, before aggregation. Both source carriers
    are already capped at the exposure by their existing producers
    (third_party_deposit.py / life_insurance.py); this pins that the routing
    PRESERVES that cap rather than reading an uncapped raw value.

    The third-party-deposit half is pinned on an SA leg, not A-IRB: an
    A-IRB leg's ``third_party_deposit_value`` is deliberately 0.0 (module
    docstring), so it cannot demonstrate a cap -- there would be nothing to
    cap. SA is not in the F-IRB/A-IRB deferral gate at all (verified
    empirically), so its deposit value is real and still routes via
    ``ofcp_substitution_amount`` (SA is never A-IRB, so it can never take
    the LGD-Modelling route regardless of election), giving a clean,
    meaningful cap-preservation test on the actual routing code path.
    """

    def test_life_insurance_capped_at_exposure_value(self, processor: CRMProcessor) -> None:
        # Arrange
        exposures = _exposure_row(approach=ApproachType.AIRB.value, ead=300_000.0)
        collateral = [_life_insurance_row("EXP1", 500_000.0)]
        bundle = _make_bundle(exposures, collateral)
        config = _b31_config(AIRBCollateralMethod.LGD_MODELLING)

        # Act
        df = _run_crm(processor, config, bundle)
        row = df.filter(pl.col("exposure_reference") == "EXP1")

        # Assert
        assert row["ofcp_lgd_life_insurance"][0] == pytest.approx(300_000.0)

    def test_third_party_deposit_capped_at_exposure_value_on_sa_leg(
        self, processor: CRMProcessor
    ) -> None:
        # Arrange
        exposures = _exposure_row(approach=ApproachType.SA.value, ead=300_000.0)
        collateral = [_third_party_deposit_row("EXP1", 500_000.0)]
        bundle = _make_bundle(exposures, collateral)
        config = _b31_config(AIRBCollateralMethod.LGD_MODELLING)

        # Act
        df = _run_crm(processor, config, bundle)
        row = df.filter(pl.col("exposure_reference") == "EXP1")

        # Assert
        assert row["ofcp_substitution_amount"][0] == pytest.approx(300_000.0)


# =============================================================================
# 7. Conservation
# =============================================================================


class TestConservation:
    """RD-8 assertion #7, restated per team-lead's scope call: the three
    routing carriers together equal the capped total of the source amounts
    AS THE PRODUCERS ACTUALLY EMIT THEM -- ``life_ins_collateral_value`` and
    ``third_party_deposit_value``, read from the SAME row -- not the raw
    pledge amounts. This makes the identity robust to a source the
    producers themselves zero out (the A-IRB deposit deferral, module
    docstring): a deferred source is "no value to conserve", not "value the
    routing destroyed". Reading the two source columns directly (rather
    than hard-coding an assumed total) is also what makes this test
    independent of the exact deferral-scope decision -- it holds whatever
    the sources turn out to be.
    """

    def test_three_carriers_sum_to_the_source_total(self, processor: CRMProcessor) -> None:
        # Arrange
        exposures = _exposure_row(approach=ApproachType.AIRB.value, ead=1_000_000.0)
        collateral = [
            _life_insurance_row("EXP1", 200_000.0),
            _third_party_deposit_row("EXP1", 150_000.0),
        ]
        bundle = _make_bundle(exposures, collateral)
        config = _b31_config(AIRBCollateralMethod.LGD_MODELLING)

        # Act
        df = _run_crm(processor, config, bundle)
        row = df.filter(pl.col("exposure_reference") == "EXP1")
        routed_total = (
            row["ofcp_lgd_cash_deposit"][0]
            + row["ofcp_lgd_life_insurance"][0]
            + row["ofcp_substitution_amount"][0]
        )
        source_total = row["life_ins_collateral_value"][0] + row["third_party_deposit_value"][0]

        # Assert
        assert routed_total == pytest.approx(source_total)

    def test_three_carriers_sum_to_the_source_total_when_over_exposure(
        self, processor: CRMProcessor
    ) -> None:
        """The conservation identity holds on the CAPPED source total too:
        a 500,000 life-insurance pledge against a 300,000 exposure is
        already capped to 300,000 by ``life_insurance.py`` before routing
        ever runs; the routed total must match THAT (300,000 + whatever the
        deposit source is), not the raw 500,000 pledge nor a doubled
        figure."""
        # Arrange
        exposures = _exposure_row(approach=ApproachType.AIRB.value, ead=300_000.0)
        collateral = [
            _life_insurance_row("EXP1", 500_000.0),
            _third_party_deposit_row("EXP1", 150_000.0),
        ]
        bundle = _make_bundle(exposures, collateral)
        config = _b31_config(AIRBCollateralMethod.LGD_MODELLING)

        # Act
        df = _run_crm(processor, config, bundle)
        row = df.filter(pl.col("exposure_reference") == "EXP1")
        routed_total = (
            row["ofcp_lgd_cash_deposit"][0]
            + row["ofcp_lgd_life_insurance"][0]
            + row["ofcp_substitution_amount"][0]
        )
        source_total = row["life_ins_collateral_value"][0] + row["third_party_deposit_value"][0]

        # Assert
        assert routed_total == pytest.approx(source_total)
        assert source_total == pytest.approx(300_000.0)
