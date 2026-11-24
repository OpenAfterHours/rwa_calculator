"""
P1.444 (review CL-03): a repeated collateral_reference through the whole pipeline.

Two 100,000 term loans to one unrated large corporate (100% in both regimes:
CRR Art. 122(2); PS1/26 Art. 122(5), not an SME at 100m turnover), no accrued
interest, no undrawn headroom. One cash item C1 is linked to both loans through
``collateral_links``; the collateral table states C1 on two rows, one per loan.

Hand calculation (SA, Financial Collateral Comprehensive Method, cash H_c = 0,
same currency so H_fx = 0; Art. 223(5) E* = E - C_VA):

- C1 stated once at 60,000 (the well-formed control): the finite 60,000 goes
  to L1 first (equal density, lexical tie-break), so E*(L1) = 40,000 and
  E*(L2) = 100,000. Total RWA = 40,000 + 100,000 = 140,000.
- C1 stated twice at 60,000: one item, so the same 140,000. HEAD credited L1
  with 120,000 (EAD 0) and reported 100,000.
- C1 stated at 60,000 and at 40,000: the allocator takes the smaller stated
  value (owner sign-off, P1.444), so E*(L1) = 60,000 and the total is
  160,000. HEAD seeded 60,000 from whichever row sorted first and credited it
  twice: 100,000.

A second item sharing a beneficiary (``TestSharedBeneficiaryAllocatesAsWellFormed``)
shows the fix is not one-directional: three 100,000 loans at 150% / 100% / 20%
pre-CRM density (CQS 5 / unrated / CQS 1 corporates; CRR Art. 122(1) Table 6 and
122(2), PS1/26 Art. 122(2) Table 6 and 122(5)), cash items A (linked to L1, L3) and B (linked to L1,
L2), 100,000 each. Well-formed: A fills L1 first (equal fan-out, lexical
tie-break), B spills to L2, L3 is uncovered, so RWA = 100,000 x 20% = 20,000.
HEAD with A stated on two rows doubled A's link edges, so B (fewer edges) drew
first at L1 and A was spent on L3 (credited twice: 200,000), leaving L2
uncovered: RWA = 100,000. The fix restores the well-formed 20,000 -- an 80,000
REDUCTION against HEAD, bounded by the well-formed result.

With ``enable_collateral_link_splitting=False`` the allocator never runs, so the
duplicate rows are applied as stated even with a links table; DQ004 still fires.

Scope: every item here is cash, which reaches the CRM link allocator, so the
duplicated feed's result equals the well-formed feed's. That does not hold for
real-estate collateral, whose property attributes (LTV, type, coverage, loan
split) the hierarchy stage reads row by row without reading
``collateral_links``, nor for third-party deposits, which leave the collateral
frame before the allocator runs: both are still applied once per row -- a
recorded residual of P1.444, not pinned here.

PS1/26 Art. 193(7)(b): allocate each portion of the item "to one of the
exposures it covers, without any double-counting". The DQ004 input-gate finding
is regime-neutral (the input contract), so both regimes are run.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from functools import cache

import pytest

from rwa_calc.contracts.bundles import AggregatedResultBundle, RawDataBundle
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.contracts.errors import ERROR_DUPLICATE_KEY
from rwa_calc.data.schemas import COLLATERAL_LINK_SCHEMA, COLLATERAL_SCHEMA
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.fixtures.raw_bundle import seal_raw_table

from .conftest import (
    _rows_to_lazyframe,
    make_counterparty,
    make_facility,
    make_loan,
    make_raw_data_bundle,
)

_REGIMES = ("CRR", "B31")


def _config(regime: str, *, splitting: bool = True) -> CalculationConfig:
    if regime == "CRR":
        return CalculationConfig.crr(
            reporting_date=date(2026, 6, 30), enable_collateral_link_splitting=splitting
        )
    return CalculationConfig.basel_3_1(
        reporting_date=date(2027, 6, 30), enable_collateral_link_splitting=splitting
    )


def _bundle(values: tuple[float, ...], *, linked: bool) -> RawDataBundle:
    """Loans L1 / L2 of 100,000; C1 on one row per value, the i-th on loan L<i+1>."""
    bundle = make_raw_data_bundle(
        counterparties=[make_counterparty(counterparty_reference="CP1")],
        loans=[
            make_loan(
                loan_reference=ref,
                counterparty_reference="CP1",
                drawn_amount=100_000.0,
                interest=0.0,
            )
            for ref in ("L1", "L2")
        ],
        facilities=[
            make_facility(facility_reference="F1", counterparty_reference="CP1", limit=0.0)
        ],
        facility_mappings=[],
    )
    collateral = _rows_to_lazyframe(
        [
            {
                "collateral_reference": "C1",
                "collateral_type": "cash",
                "currency": "GBP",
                "market_value": value,
                "beneficiary_type": "loan",
                "beneficiary_reference": f"L{i + 1}",
                "is_eligible_financial_collateral": True,
            }
            for i, value in enumerate(values)
        ],
        COLLATERAL_SCHEMA,
    )
    links = _rows_to_lazyframe(
        [
            {"collateral_reference": "C1", "beneficiary_type": "loan", "beneficiary_reference": ref}
            for ref in ("L1", "L2")
        ],
        COLLATERAL_LINK_SCHEMA,
    )
    return replace(
        bundle,
        collateral=seal_raw_table(collateral, "collateral"),
        collateral_links=seal_raw_table(links, "collateral_links") if linked else None,
    )


def _external_rating(counterparty: str, cqs: int) -> dict[str, object]:
    return {
        "rating_reference": f"R_{counterparty}",
        "counterparty_reference": counterparty,
        "rating_type": "external",
        "rating_agency": "S&P",
        "rating_value": "BBB",
        "cqs": cqs,
        "pd": None,
        "rating_date": date(2026, 1, 1),
        "is_solicited": True,
        "model_id": None,
    }


def _shared_beneficiary_bundle(*, a_rows: tuple[str, ...]) -> RawDataBundle:
    """Loans L1-L3 (CQS 5 / unrated / CQS 1); items A -> {L1, L3} and B -> {L1, L2}.

    ``a_rows`` names the beneficiary of each collateral row stating item A: one
    row for the well-formed feed, two for the duplicated one. B is stated once.
    """
    obligors = (("CP1", 5), ("CP2", None), ("CP3", 1))
    bundle = make_raw_data_bundle(
        counterparties=[make_counterparty(counterparty_reference=cp) for cp, _ in obligors],
        loans=[
            make_loan(
                loan_reference=f"L{i + 1}",
                counterparty_reference=cp,
                drawn_amount=100_000.0,
                interest=0.0,
            )
            for i, (cp, _) in enumerate(obligors)
        ],
        facilities=[
            make_facility(facility_reference="F1", counterparty_reference="CP1", limit=0.0)
        ],
        facility_mappings=[],
        ratings=[_external_rating(cp, cqs) for cp, cqs in obligors if cqs is not None],
    )
    rows = [("A", loan) for loan in a_rows] + [("B", "L1")]
    collateral = _rows_to_lazyframe(
        [
            {
                "collateral_reference": item,
                "collateral_type": "cash",
                "currency": "GBP",
                "market_value": 100_000.0,
                "beneficiary_type": "loan",
                "beneficiary_reference": loan,
                "is_eligible_financial_collateral": True,
            }
            for item, loan in rows
        ],
        COLLATERAL_SCHEMA,
    )
    links = _rows_to_lazyframe(
        [
            {
                "collateral_reference": item,
                "beneficiary_type": "loan",
                "beneficiary_reference": loan,
            }
            for item, loan in (("A", "L1"), ("A", "L3"), ("B", "L1"), ("B", "L2"))
        ],
        COLLATERAL_LINK_SCHEMA,
    )
    return replace(
        bundle,
        collateral=seal_raw_table(collateral, "collateral"),
        collateral_links=seal_raw_table(links, "collateral_links"),
    )


@cache
def _run(
    regime: str, values: tuple[float, ...], linked: bool, splitting: bool = True
) -> AggregatedResultBundle:
    return PipelineOrchestrator().run_with_data(
        _bundle(values, linked=linked), _config(regime, splitting=splitting)
    )


@cache
def _run_shared(regime: str, a_rows: tuple[str, ...]) -> AggregatedResultBundle:
    return PipelineOrchestrator().run_with_data(
        _shared_beneficiary_bundle(a_rows=a_rows), _config(regime)
    )


def _by_reference(result: AggregatedResultBundle, column: str) -> dict[str, float]:
    ledger = result.results.collect()
    return dict(zip(ledger["exposure_reference"], ledger[column], strict=True))


@pytest.mark.parametrize("regime", _REGIMES)
class TestLinkedDuplicateIsOneItem:
    def test_single_row_control_matches_the_hand_calculation(self, regime: str) -> None:
        # Arrange / Act
        result = _run(regime, (60_000.0,), True)

        # Assert
        assert _by_reference(result, "collateral_adjusted_value")["L1"] == pytest.approx(60_000.0)
        assert result.results.collect()["rwa_final"].sum() == pytest.approx(140_000.0)

    def test_identical_duplicates_are_credited_once(self, regime: str) -> None:
        # Arrange / Act — HEAD: L1 credited 120,000, total RWA 100,000.
        result = _run(regime, (60_000.0, 60_000.0), True)

        # Assert
        assert _by_reference(result, "collateral_adjusted_value")["L1"] == pytest.approx(60_000.0)
        assert _by_reference(result, "ead_final")["L1"] == pytest.approx(40_000.0)
        assert result.results.collect()["rwa_final"].sum() == pytest.approx(140_000.0)

    def test_differing_duplicates_are_credited_at_the_smallest_value(self, regime: str) -> None:
        # Arrange / Act — HEAD: L1 credited 120,000, total RWA 100,000.
        result = _run(regime, (60_000.0, 40_000.0), True)

        # Assert
        assert _by_reference(result, "collateral_adjusted_value")["L1"] == pytest.approx(40_000.0)
        assert result.results.collect()["rwa_final"].sum() == pytest.approx(160_000.0)


@pytest.mark.parametrize("regime", _REGIMES)
@pytest.mark.parametrize("linked", [True, False], ids=["links", "no_links"])
class TestDuplicateCollateralReferenceIsReported:
    def test_dq004_names_the_collateral_not_an_exposure(self, regime: str, linked: bool) -> None:
        # Arrange / Act
        result = _run(regime, (60_000.0, 60_000.0), linked)
        found = [
            e
            for e in result.errors
            if e.code == ERROR_DUPLICATE_KEY and e.field_name == "collateral_reference"
        ]

        # Assert
        assert [(e.actual_value, e.exposure_reference) for e in found] == [("C1", None)]

    def test_a_unique_reference_is_not_reported(self, regime: str, linked: bool) -> None:
        # Arrange / Act
        result = _run(regime, (60_000.0,), linked)

        # Assert
        assert not [e for e in result.errors if e.field_name == "collateral_reference"]


@pytest.mark.parametrize("regime", _REGIMES)
def test_rows_without_links_stay_applied_as_stated(regime: str) -> None:
    """No links table: each row protects its own beneficiary, as the firm stated it.

    Deliberate and owner-decided (P1.444 sign-off): converting duplicate rows into
    implicit links needs a value rule the input does not carry and can LOWER RWA
    against a firm's own per-row split, so the engine reports the breach (DQ004)
    and leaves the rows as supplied. 60,000 on each loan: E* = 40,000 twice.
    """
    # Arrange / Act
    result = _run(regime, (60_000.0, 60_000.0), False)

    # Assert
    assert _by_reference(result, "collateral_adjusted_value") == pytest.approx(
        {"L1": 60_000.0, "L2": 60_000.0}
    )
    assert result.results.collect()["rwa_final"].sum() == pytest.approx(80_000.0)


@pytest.mark.parametrize("regime", _REGIMES)
class TestSharedBeneficiaryAllocatesAsWellFormed:
    """A duplicated item draws in the same order as the item stated once.

    Pins the RWA REDUCTION against HEAD as deliberate (P1.444 sign-off, either
    direction): HEAD's doubled link edges for A made B draw first at L1, so B's
    supply was spent there and L2 (100%) was left uncovered, RWA 100,000. The
    well-formed allocation leaves only L3 (20%) uncovered: RWA 20,000.
    """

    _WELL_FORMED = ("L1",)
    _DUPLICATED = ("L1", "L3")

    def test_well_formed_control_matches_the_hand_calculation(self, regime: str) -> None:
        # Arrange / Act
        result = _run_shared(regime, self._WELL_FORMED)

        # Assert
        assert _by_reference(result, "collateral_adjusted_value") == pytest.approx(
            {"L1": 100_000.0, "L2": 100_000.0, "L3": 0.0}
        )
        assert result.results.collect()["rwa_final"].sum() == pytest.approx(20_000.0)

    def test_duplicated_item_is_allocated_as_the_well_formed_item(self, regime: str) -> None:
        # Arrange / Act — HEAD: L2 0.0, L3 200,000, total RWA 100,000.
        result = _run_shared(regime, self._DUPLICATED)

        # Assert
        assert _by_reference(result, "collateral_adjusted_value") == pytest.approx(
            {"L1": 100_000.0, "L2": 100_000.0, "L3": 0.0}
        )
        assert result.results.collect()["rwa_final"].sum() == pytest.approx(20_000.0)


@pytest.mark.parametrize("regime", _REGIMES)
def test_splitting_disabled_applies_duplicate_rows_as_stated(regime: str) -> None:
    """With ``enable_collateral_link_splitting=False`` the allocator never runs.

    The links table is ignored, so each C1 row protects its own beneficiary at
    60,000 (E* = 40,000 twice, RWA 80,000) and DQ004 is still raised: the DQ004
    message says the smallest-value split applies only when splitting is enabled.
    """
    # Arrange / Act
    result = _run(regime, (60_000.0, 60_000.0), True, False)
    found = [e for e in result.errors if e.field_name == "collateral_reference"]

    # Assert
    assert _by_reference(result, "collateral_adjusted_value") == pytest.approx(
        {"L1": 60_000.0, "L2": 60_000.0}
    )
    assert result.results.collect()["rwa_final"].sum() == pytest.approx(80_000.0)
    assert [(e.code, e.actual_value) for e in found] == [(ERROR_DUPLICATE_KEY, "C1")]
    assert "splitting disabled" in found[0].message
