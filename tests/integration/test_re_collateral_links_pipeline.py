"""
Integration tests: one real-estate item spread over several loans by
``collateral_links``, weighted end to end (P1.450, review CL-13).

Pipeline position:
    Loader -> HierarchyResolver -> Classifier -> CRMProcessor -> RealEstateSplitter
    -> SACalculator -> OutputAggregator (``PipelineOrchestrator.run_with_data``)

Before the fix the hierarchy stage read only the collateral row's own
beneficiary: that loan took the whole property value and an LTV on its own loan
alone, and every other linked loan took no property at all. A linked mortgage
then lost its class (RE005, counterparty weight - capital OVERSTATED), while a
linked loan of an ADC or a non-qualifying property escaped the higher
real-estate weight (capital UNDERSTATED). The tests below pin each direction in
each regime it exists in.

Hand calculations (one natural person, LN_A 100k drawn, LN_B 100k drawn plus
20k interest, one qualifying residential property of 300k linked to both):

- Pooled LTV (PS1/26 Art. 124C(3)): (100k + 120k) / 300k = 0.7333.
- CRR Art. 125(1)(a) / 125(2)(d): 0.7333 <= 0.80, so 35% on the whole of each
  loan. RWA 35,000 + 42,000 = 77,000.
- PS1/26 Art. 124F(1): 20% on the part up to 55% of the property value. Shared
  pro rata (the owner-approved convention), the part is 0.55 / 0.7333 = 75% of
  each loan; the residual 25% takes 75% (Art. 124L(1)(a), a natural person).
  RW 0.75 x 0.20 + 0.25 x 0.75 = 0.3375. RWA 33,750 + 40,500 = 74,250.

The same property value reaches the IRB stage too: the classifier's mortgage
flag reads the linked value, so a linked loan whose product type names no
mortgage moves into the IRB retail-mortgage class (correlation 0.15), and its
Basel 3.1 output-floor SA-equivalent is the Art. 124F weight above.

A linked mortgage's share of the house also leaves the obligor's retail-threshold
aggregate (CRR Art. 123(c), PS1/26 Art. 123A(1)(b)(ii)), so a loan of the same
obligor that no link names can fall within the threshold and become regulatory
retail - a fall in RWA on a loan the links do not touch.

A contingent is named by a link of ``beneficiary_type`` ``contingent`` (the CRM
stage rejects any other label for it, CRM010). It takes the property's
attributes as a loan does, and its share of the value is measured on its undrawn
committed amount (Art. 124C(2)).

References:
- PS1/26 Art. 124, 124C(2)-(3), 124F(1), 124J(3), 124K(1), 124L(1)(a)
- CRR Art. 124(1), 125(1)-(2), 154(3)
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from typing import Any

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.data.schemas import COLLATERAL_LINK_SCHEMA, COLLATERAL_SCHEMA, RATINGS_SCHEMA
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.fixtures.irb_test_helpers import (
    create_full_irb_model_permissions,
    enrich_ratings_with_model_id,
)
from tests.fixtures.raw_bundle import seal_raw_table

from .conftest import (
    _rows_to_lazyframe,
    make_contingent,
    make_counterparty,
    make_facility,
    make_loan,
    make_raw_data_bundle,
)

_CONFIGS = {
    "crr": CalculationConfig.crr(reporting_date=date(2026, 6, 30)),
    "b31": CalculationConfig.basel_3_1(reporting_date=date(2027, 6, 30)),
}
_IRB_CONFIGS = {
    "crr": CalculationConfig.crr(
        reporting_date=date(2026, 6, 30), permission_mode=PermissionMode.IRB
    ),
    "b31": CalculationConfig.basel_3_1(
        reporting_date=date(2027, 6, 30), permission_mode=PermissionMode.IRB
    ),
}


def _bundle(*, kind: str, ln_b_interest: float = 0.0) -> Any:
    """LN_A and LN_B linked to property C1; LN_C, the same obligor's, unlinked.

    ``kind`` is ``"residential"`` (a natural person's mortgages on a qualifying
    house), ``"non_qualifying"`` (the same, the property failing Art. 124A /
    CRR Art. 125(2)) or ``"adc"`` (a corporate's term loans on an ADC site).
    """
    if kind == "adc":
        counterparty = make_counterparty(counterparty_reference="CP_P", entity_type="corporate")
        product, property_type, extra = "TERM_LOAN", "commercial", {"is_adc": True}
    else:
        counterparty = _natural_person()
        product, property_type, extra = "RESIDENTIAL_MORTGAGE", "residential", {}
    loans = [
        make_loan(
            loan_reference="LN_A",
            counterparty_reference="CP_P",
            product_type=product,
            drawn_amount=100_000.0,
            interest=0.0,
            due_diligence_performed=True,
        ),
        make_loan(
            loan_reference="LN_B",
            counterparty_reference="CP_P",
            product_type=product,
            drawn_amount=100_000.0,
            interest=ln_b_interest,
            due_diligence_performed=True,
        ),
        make_loan(
            loan_reference="LN_C",
            counterparty_reference="CP_P",
            product_type="TERM_LOAN",
            drawn_amount=50_000.0,
            interest=0.0,
            due_diligence_performed=True,
        ),
    ]
    facilities = [
        make_facility(
            facility_reference="FAC_P",
            counterparty_reference="CP_P",
            product_type=product,
            limit=250_000.0,
            is_revolving=False,
        )
    ]
    bundle = make_raw_data_bundle(counterparties=[counterparty], loans=loans, facilities=facilities)
    collateral = _rows_to_lazyframe(
        [
            {
                "collateral_reference": "C1",
                "collateral_type": "real_estate",
                "currency": "GBP",
                "market_value": 300_000.0,
                "property_type": property_type,
                "is_qualifying_re": kind != "non_qualifying",
                "beneficiary_type": "loan",
                "beneficiary_reference": "LN_A",
                **extra,
            }
        ],
        COLLATERAL_SCHEMA,
    )
    links = _rows_to_lazyframe(
        [
            {"collateral_reference": "C1", "beneficiary_type": "loan", "beneficiary_reference": r}
            for r in ("LN_A", "LN_B")
        ],
        COLLATERAL_LINK_SCHEMA,
    )
    return replace(
        bundle,
        collateral=seal_raw_table(collateral, "collateral"),
        collateral_links=seal_raw_table(links, "collateral_links"),
    )


def _natural_person() -> dict[str, Any]:
    return make_counterparty(
        counterparty_reference="CP_P",
        entity_type="individual",
        annual_revenue=None,
        total_assets=None,
        is_natural_person=True,
        borrower_income_currency="GBP",
    )


def _irb_bundle() -> Any:
    """A-IRB: LN_A and LN_B, TERM_LOAN products, linked to C1; LN_C unlinked.

    The product type names no mortgage, so the IRB class of LN_B follows from
    the linked property value alone (the classifier's mortgage flag).
    """
    loans = [
        make_loan(
            loan_reference=ref,
            counterparty_reference="CP_P",
            product_type="TERM_LOAN",
            drawn_amount=drawn,
            interest=interest,
            lgd=lgd,
            due_diligence_performed=True,
        )
        for ref, drawn, interest, lgd in (
            ("LN_A", 100_000.0, 0.0, 0.10),
            ("LN_B", 100_000.0, 20_000.0, 0.10),
            ("LN_C", 50_000.0, 0.0, 0.45),
        )
    ]
    facilities = [
        make_facility(
            facility_reference="FAC_P",
            counterparty_reference="CP_P",
            product_type="TERM_LOAN",
            limit=250_000.0,
            is_revolving=False,
        )
    ]
    bundle = make_raw_data_bundle(
        counterparties=[_natural_person()], loans=loans, facilities=facilities
    )
    ratings = _rows_to_lazyframe(
        [
            {
                "rating_reference": "R_CP_P",
                "counterparty_reference": "CP_P",
                "rating_type": "internal",
                "rating_agency": "internal",
                "rating_value": "BB",
                "cqs": None,
                "pd": 0.01,
                "rating_date": date(2026, 1, 1),
                "is_solicited": True,
            }
        ],
        RATINGS_SCHEMA,
    )
    collateral = _rows_to_lazyframe(
        [
            {
                "collateral_reference": "C1",
                "collateral_type": "real_estate",
                "currency": "GBP",
                "market_value": 300_000.0,
                "property_type": "residential",
                "is_qualifying_re": True,
                "is_eligible_irb_collateral": True,
                "beneficiary_type": "loan",
                "beneficiary_reference": "LN_A",
            }
        ],
        COLLATERAL_SCHEMA,
    )
    links = _rows_to_lazyframe(
        [
            {"collateral_reference": "C1", "beneficiary_type": "loan", "beneficiary_reference": r}
            for r in ("LN_A", "LN_B")
        ],
        COLLATERAL_LINK_SCHEMA,
    )
    return replace(
        bundle,
        ratings=seal_raw_table(enrich_ratings_with_model_id(ratings), "ratings"),
        model_permissions=seal_raw_table(create_full_irb_model_permissions(), "model_permissions"),
        collateral=seal_raw_table(collateral, "collateral"),
        collateral_links=seal_raw_table(links, "collateral_links"),
    )


def _contingent_bundle() -> Any:
    """LN_A (a 100k loan) and CT_1 (a wholly undrawn 100k commitment) on one property.

    The property is a 400k commercial one failing the qualifying conditions,
    linked to LN_A by a ``loan`` link and to CT_1 by a ``contingent`` link; the
    collateral row itself names LN_A.
    """
    loans = [
        make_loan(
            loan_reference="LN_A",
            counterparty_reference="CP_P",
            product_type="TERM_LOAN",
            drawn_amount=100_000.0,
            interest=0.0,
            due_diligence_performed=True,
        )
    ]
    contingents = [
        make_contingent(
            contingent_reference="CT_1",
            counterparty_reference="CP_P",
            product_type="LOAN_COMMITMENT",
            nominal_amount=100_000.0,
            is_obs_commitment=True,
            due_diligence_performed=True,
        )
    ]
    facilities = [
        make_facility(
            facility_reference="FAC_P",
            counterparty_reference="CP_P",
            product_type="TERM_LOAN",
            limit=100_000.0,
            is_revolving=False,
        )
    ]
    bundle = make_raw_data_bundle(
        counterparties=[_natural_person()],
        loans=loans,
        facilities=facilities,
        contingents=contingents,
    )
    collateral = _rows_to_lazyframe(
        [
            {
                "collateral_reference": "C1",
                "collateral_type": "real_estate",
                "currency": "GBP",
                "market_value": 400_000.0,
                "property_type": "commercial",
                "is_qualifying_re": False,
                "beneficiary_type": "loan",
                "beneficiary_reference": "LN_A",
            }
        ],
        COLLATERAL_SCHEMA,
    )
    links = _rows_to_lazyframe(
        [
            {
                "collateral_reference": "C1",
                "beneficiary_type": "loan",
                "beneficiary_reference": "LN_A",
            },
            {
                "collateral_reference": "C1",
                "beneficiary_type": "contingent",
                "beneficiary_reference": "CT_1",
            },
        ],
        COLLATERAL_LINK_SCHEMA,
    )
    return replace(
        bundle,
        collateral=seal_raw_table(collateral, "collateral"),
        collateral_links=seal_raw_table(links, "collateral_links"),
    )


def _run(bundle: Any, regime: str) -> tuple[pl.DataFrame, set[str]]:
    result = PipelineOrchestrator().run_with_data(bundle, _CONFIGS[regime])
    return result.results.collect(), {error.code for error in result.errors}


def _row(results: pl.DataFrame, ref: str) -> dict[str, Any]:
    rows = results.filter(pl.col("exposure_reference") == ref).to_dicts()
    assert len(rows) == 1, f"expected one result row for {ref}, got {len(rows)}"
    return rows[0]


class TestLinkedResidentialMortgages:
    """The OVERSTATEMENT: a linked mortgage lost its class and its property."""

    @pytest.mark.parametrize("regime", ["crr", "b31"])
    def test_linked_mortgage_keeps_its_class_and_no_re005(self, regime: str) -> None:
        # Act
        results, codes = _run(_bundle(kind="residential", ln_b_interest=20_000.0), regime)

        # Assert - LN_B is secured by the property, so it is a mortgage with evidence.
        assert _row(results, "LN_B")["exposure_class"] == "retail_mortgage"
        assert "RE005" not in codes

    @pytest.mark.parametrize(
        ("regime", "risk_weight"),
        [
            ("crr", 0.35),  # Art. 125(2)(d): pooled LTV 0.7333 <= 0.80
            ("b31", 0.3375),  # Art. 124F(1): 75% at 20%, 25% at 75% (Art. 124L(1)(a))
        ],
    )
    def test_linked_mortgages_are_weighted_on_the_pooled_ltv(
        self, regime: str, risk_weight: float
    ) -> None:
        # Act
        results, _ = _run(_bundle(kind="residential", ln_b_interest=20_000.0), regime)

        # Assert - absolute weights and RWA on both linked loans.
        row_a = _row(results, "LN_A")
        row_b = _row(results, "LN_B")
        assert row_b["ead_final"] == pytest.approx(120_000.0), "LN_B EAD carries its interest"
        assert row_a["risk_weight"] == pytest.approx(risk_weight)
        assert row_b["risk_weight"] == pytest.approx(risk_weight)
        assert row_a["rwa_final"] + row_b["rwa_final"] == pytest.approx(220_000.0 * risk_weight)

    @pytest.mark.parametrize("regime", ["crr", "b31"])
    def test_unlinked_loan_of_the_same_obligor_is_not_secured(self, regime: str) -> None:
        # Guard (green before the fix too): LN_C shares the obligor, not the property.
        results, _ = _run(_bundle(kind="residential", ln_b_interest=20_000.0), regime)

        row_c = _row(results, "LN_C")
        assert row_c["exposure_class"] != "retail_mortgage"
        assert row_c["ltv"] is None


def _threshold_bundle() -> Any:
    """LN_A (400k) and LN_B (900k) linked to a 1.5m house; LN_C (50k) unlinked.

    One natural person, managed as part of a retail pool (PS1/26 Art.
    123A(1)(b)(iii)). The obligor owes 1.35m in all, 1.3m of it on the linked
    mortgages.
    """
    counterparty = {**_natural_person(), "is_managed_as_retail": True}
    loans = [
        make_loan(
            loan_reference=ref,
            counterparty_reference="CP_P",
            product_type=product,
            drawn_amount=drawn,
            interest=0.0,
            due_diligence_performed=True,
        )
        for ref, product, drawn in (
            ("LN_A", "RESIDENTIAL_MORTGAGE", 400_000.0),
            ("LN_B", "RESIDENTIAL_MORTGAGE", 900_000.0),
            ("LN_C", "TERM_LOAN", 50_000.0),
        )
    ]
    facilities = [
        make_facility(
            facility_reference="FAC_P",
            counterparty_reference="CP_P",
            product_type="RESIDENTIAL_MORTGAGE",
            limit=1_350_000.0,
            is_revolving=False,
        )
    ]
    bundle = make_raw_data_bundle(counterparties=[counterparty], loans=loans, facilities=facilities)
    collateral = _rows_to_lazyframe(
        [
            {
                "collateral_reference": "C1",
                "collateral_type": "real_estate",
                "currency": "GBP",
                "market_value": 1_500_000.0,
                "property_type": "residential",
                "is_qualifying_re": True,
                "beneficiary_type": "loan",
                "beneficiary_reference": "LN_A",
            }
        ],
        COLLATERAL_SCHEMA,
    )
    links = _rows_to_lazyframe(
        [
            {"collateral_reference": "C1", "beneficiary_type": "loan", "beneficiary_reference": r}
            for r in ("LN_A", "LN_B")
        ],
        COLLATERAL_LINK_SCHEMA,
    )
    return replace(
        bundle,
        collateral=seal_raw_table(collateral, "collateral"),
        collateral_links=seal_raw_table(links, "collateral_links"),
    )


class TestRetailThresholdOfAnUnlinkedLoan:
    """A loan no link names can change class: the threshold excludes the linked mortgages."""

    @pytest.mark.parametrize("regime", ["crr", "b31"])
    def test_unlinked_loan_falls_within_the_retail_threshold(self, regime: str) -> None:
        # CRR Art. 123(c) excludes "exposures fully and completely secured on
        # residential property collateral"; PS1/26 Art. 123A(1)(b)(ii) excludes
        # "all residential real estate exposures". LN_A and LN_B each hold a share
        # of the house at least their own amount (1.5m x 400/1,300 and x 900/1,300),
        # so the obligor's aggregate is LN_C's 50k alone, within the threshold.
        # Before: LN_B held no property, so the aggregate was 950k, above it in both
        # regimes - CRR corporate 100%, Basel 3.1 non-regulatory retail 100%.

        # Act
        results, _ = _run(_threshold_bundle(), regime)

        # Assert - LN_C is regulatory retail at 75% (CRR Art. 123; PS1/26 Art. 123(3)(b)).
        row_c = _row(results, "LN_C")
        assert row_c["exposure_class"] == "retail_other"
        assert row_c["risk_weight"] == pytest.approx(0.75)
        assert row_c["rwa_final"] == pytest.approx(37_500.0)


class TestLinkedHigherWeightProperty:
    """A linked loan now takes the property's weight: higher under CRR, lower under Basel 3.1.

    At HEAD (before P1.450) LN_B took its counterparty weight. Under CRR that
    understated it (retail 75% against Art. 124(1) 100%); under Basel 3.1 it
    overstated it ("other retail" 100% against the Art. 124J 75%).
    """

    @pytest.mark.parametrize(
        ("regime", "risk_weight"),
        [
            # CRR Art. 124(1): conditions not met -> 100% up to the property value
            # (pooled LTV 0.6667). Before: retail 75% on the counterparty.
            ("crr", 1.00),
            # PS1/26 Art. 124J: other residential RE not dependent on the property's
            # cash flows takes the counterparty weight, 75% for a natural person.
            # Before: "other retail" 100% on the counterparty, so this direction is
            # RWA-reducing under Basel 3.1 (the class is not regulatory retail).
            ("b31", 0.75),
        ],
    )
    def test_non_qualifying_property_reaches_every_linked_loan(
        self, regime: str, risk_weight: float
    ) -> None:
        # Act
        results, _ = _run(_bundle(kind="non_qualifying"), regime)

        # Assert - LN_B takes the same real-estate weight as LN_A.
        assert _row(results, "LN_A")["risk_weight"] == pytest.approx(risk_weight)
        assert _row(results, "LN_B")["risk_weight"] == pytest.approx(risk_weight)

    def test_adc_property_weights_every_linked_loan_at_150(self) -> None:
        # Basel 3.1 only: CRR has no ADC weight - Art. 124(1) gives 100%, the same
        # as the unsecured corporate weight, so the CRR leg cannot be reddened here.

        # Act
        results, _ = _run(_bundle(kind="adc"), "b31")

        # Assert - PS1/26 Art. 124K(1): 150% to an ADC exposure. Before: LN_B 100%.
        assert _row(results, "LN_A")["risk_weight"] == pytest.approx(1.50)
        assert _row(results, "LN_B")["risk_weight"] == pytest.approx(1.50)
        assert _row(results, "LN_C")["risk_weight"] == pytest.approx(1.00)


class TestLinkedContingent:
    """A contingent named by a ``contingent`` link is secured as a loan is."""

    @pytest.mark.parametrize(
        ("regime", "risk_weight"),
        [
            # CRR Art. 124(1): the conditions of Art. 126 are not met, so 100% on
            # the part secured by the pledged value (all of it). At HEAD (before
            # P1.450) the contingent took no property value or LTV and stayed
            # retail_other at 75%.
            ("crr", 1.00),
            # PS1/26 Art. 124J(3): other commercial RE not dependent on the
            # property's cash flows takes the higher of 60% and the Art. 124L(1)(a)
            # natural-person weight of 75%. At HEAD (before P1.450) it stayed
            # retail_other at 100%, so this leg is RWA-reducing (175,000 to 150,000).
            ("b31", 0.75),
        ],
    )
    def test_contingent_link_takes_the_property_attributes_and_weight(
        self, regime: str, risk_weight: float
    ) -> None:
        # Act
        results, codes = _run(_contingent_bundle(), regime)

        # Assert - CT_1 is secured by a non-qualifying commercial property, as LN_A is.
        row = _row(results, "CT_1")
        assert "CRM010" not in codes, "the contingent link must be well-typed"
        assert row["ead_final"] == pytest.approx(100_000.0)
        assert row["property_type"] == "commercial"
        assert row["is_qualifying_re"] is False
        assert row["risk_weight"] == pytest.approx(risk_weight)
        assert row["rwa_final"] == pytest.approx(100_000.0 * risk_weight)
        assert _row(results, "LN_A")["risk_weight"] == pytest.approx(risk_weight)

    @pytest.mark.parametrize("regime", ["crr", "b31"])
    def test_undrawn_commitment_shares_the_value_on_its_committed_amount(self, regime: str) -> None:
        # PS1/26 Art. 124C(2): the loan amount includes "any undrawn committed
        # amount". CT_1 is wholly undrawn, so a share measured on drawn + interest
        # alone would give it nothing and LN_A all 400k (LTV 0.25, CT_1 none).

        # Act
        results, _ = _run(_contingent_bundle(), regime)

        # Assert - (100k + 100k) / 400k on both: each holds 200k of the value.
        for ref in ("LN_A", "CT_1"):
            assert _row(results, ref)["ltv"] == pytest.approx(0.5), ref


class TestLinkedIrbLoan:
    """The linked value reaches the IRB class and the Basel 3.1 output floor."""

    @pytest.mark.parametrize("regime", ["crr", "b31"])
    def test_linked_term_loan_is_an_irb_retail_mortgage(self, regime: str) -> None:
        # Act
        result = PipelineOrchestrator().run_with_data(_irb_bundle(), _IRB_CONFIGS[regime])
        results = result.results.collect()

        # Assert - LN_B is secured by the property, so a retail exposure secured by
        # residential property: correlation 0.15 (CRR Art. 154(3); the same under
        # PS1/26). Before: CRR retail_other (correlation 0.1216), Basel 3.1 corporate.
        row_b = _row(results, "LN_B")
        assert row_b["approach_applied"] == "advanced_irb"
        assert row_b["exposure_class"] == "retail_mortgage"
        assert row_b["correlation"] == pytest.approx(0.15)
        assert _row(results, "LN_C")["exposure_class"] != "retail_mortgage"

    def test_linked_loans_output_floor_sa_equivalent_is_the_art_124f_weight(self) -> None:
        # Basel 3.1 only: CRR has no output floor.

        # Act
        result = PipelineOrchestrator().run_with_data(_irb_bundle(), _IRB_CONFIGS["b31"])
        results = result.results.collect()

        # Assert - the SA-equivalent of each linked loan is the Art. 124F weight on
        # the pooled LTV (0.3375, see the module docstring), and of LN_C its
        # unsecured 100%: S-TREA 33,750 + 40,500 + 50,000. Before: LN_A 20% on its
        # own loan, LN_B 100% unsecured, so S-TREA 190,000 and the floor bound.
        assert _row(results, "LN_A")["sa_rwa"] == pytest.approx(33_750.0)
        assert _row(results, "LN_B")["sa_rwa"] == pytest.approx(40_500.0)
        summary = result.output_floor_summary
        assert summary is not None
        assert summary.s_trea == pytest.approx(124_250.0)
