"""RC-01 / RC-02 / SF-03: the facility-mapping graph is validated and resolved.

``facility_mappings`` is consumed everywhere as a TREE, but nothing made it one:

- **RC-02 multi-parent sub-facility.** ``S -> U1`` and ``S -> U2``: the root
  lookup was a last-wins dict over an unordered ``unique()``, so S's root — and
  the RWA — changed from run to run (verifier: U1 19x / U2 21x in 40 calls).
- **RC-02 cycle.** ``F1 -> F2 -> F1``: every member is somebody's child, and only
  roots emit an undrawn row, so BOTH commitments vanished (EAD 2.25m -> 0.5m).
- **RC-01 loan under two independent facilities** consumed both headrooms
  (EAD 2.5m -> 2.0m), and **SF-03 loan under two sub-limits of one root**
  consumed the root's headroom twice (root headroom 80 -> 60).

None raised anything. Rule: CRR Art. 4(1)(56) / PS1/26 Glossary "conversion
factor" — the CF applies to "the currently undrawn amount of the commitment ...
the extent of the commitment being determined by the advised limit", and CRR /
PS1/26 Art. 111(1) measures every off-balance-sheet item's exposure value. One
drawing reduces a given limit once, and a malformed graph does not extinguish a
commitment. The verifier notes Art. 111(1) sets no GRAPH rule: these shapes are
malformed input, so the fix is a visible DQ control (DQ021 / DQ022 WARNINGs)
plus a deterministic, documented, conservative resolution (orchestrator
decision): one parent per sub-facility (lowest reference); one root per loan /
contingent (that of its lowest-referenced parent), reduced once; every cycle
member treated as a root.

Hand calculations: unrated non-SME corporate obligor (100% RW both regimes)
unless stated; ``medium_risk`` (MR) 50% CCF in both regimes; ``OC`` (original
maturity > 1y) CRR 50%, Basel 3.1 40%.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import polars as pl
import pytest

from rwa_calc.contracts.bundles import AggregatedResultBundle
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.contracts.errors import (
    ERROR_FACILITY_MAPPING_CYCLE,
    ERROR_FACILITY_MAPPING_MULTI_PARENT,
)
from rwa_calc.domain.enums import ErrorSeverity
from rwa_calc.engine.hierarchy.graph import build_facility_root_lookup, collect_facility_graph
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.integration.conftest import (
    make_counterparty,
    make_facility,
    make_loan,
    make_rating,
    make_raw_data_bundle,
)

_REGIMES = ("CRR", "B31")
_CCF_OC = {"CRR": 0.50, "B31": 0.40}


def _config(regime: str) -> CalculationConfig:
    if regime == "CRR":
        return CalculationConfig.crr(reporting_date=date(2026, 6, 30))
    return CalculationConfig.basel_3_1(reporting_date=date(2027, 6, 30))


def _map(parent: str, child: str, child_type: str = "loan") -> dict[str, str]:
    return {"parent_facility_reference": parent, "child_reference": child, "child_type": child_type}


def _mappings(rows: list[dict[str, str]]) -> pl.LazyFrame:
    return pl.LazyFrame(
        rows,
        schema={
            "parent_facility_reference": pl.String,
            "child_reference": pl.String,
            "child_type": pl.String,
        },
    )


def _edges(rows: list[dict[str, str]]) -> list[tuple[str, str]]:
    graph = collect_facility_graph(_mappings(rows))
    assert graph.edges is not None
    return sorted(
        graph.edges.select(["child_facility_reference", "parent_facility_reference"]).rows()
    )


def _run(
    regime: str,
    facilities: list[dict[str, Any]],
    loans: list[dict[str, Any]],
    mappings: list[dict[str, str]],
    **kwargs: Any,
) -> AggregatedResultBundle:
    bundle = make_raw_data_bundle(
        facilities=facilities, loans=loans, facility_mappings=mappings, **kwargs
    )
    return PipelineOrchestrator().run_with_data(bundle, _config(regime))


def _ledger(result: AggregatedResultBundle) -> dict[str, dict[str, Any]]:
    ledger = result.results.collect()
    references = ledger["exposure_reference"].to_list()
    assert len(references) == len(set(references)), "fixture adequacy: one row per reference"
    return {row["exposure_reference"]: row for row in ledger.iter_rows(named=True)}


def _codes(result: AggregatedResultBundle, code: str) -> list[Any]:
    return [e for e in result.errors if e.code == code]


class TestFacilityGraphResolution:
    """``graph.collect_facility_graph``: a forest, deterministically, with findings."""

    def test_a_tree_is_left_alone_and_silent(self) -> None:
        rows = [
            _map("U", "S1", "facility"),
            _map("U", "S2", "facility"),
            _map("S1", "S3", "facility"),
        ]

        graph = collect_facility_graph(_mappings(rows))

        assert _edges(rows) == [("S1", "U"), ("S2", "U"), ("S3", "S1")]
        assert graph.errors == ()

    @pytest.mark.parametrize("order", [("U1", "U2"), ("U2", "U1")])
    def test_a_second_parent_is_dropped_deterministically(self, order: tuple[str, str]) -> None:
        rows = [_map(order[0], "S", "facility"), _map(order[1], "S", "facility")]

        graph = collect_facility_graph(_mappings(rows))

        assert _edges(rows) == [("S", "U1")]
        assert [(e.code, e.exposure_reference, e.actual_value) for e in graph.errors] == [
            (ERROR_FACILITY_MAPPING_MULTI_PARENT, "S", "U1, U2")
        ]
        assert graph.errors[0].severity == ErrorSeverity.WARNING

    def test_the_root_lookup_no_longer_depends_on_the_call(self) -> None:
        # The verifier measured U1 19x / U2 21x over 40 identical calls.
        rows = [_map("U1", "S", "facility"), _map("U2", "S", "facility")]

        roots = {
            build_facility_root_lookup(_mappings(rows))
            .collect()
            .filter(pl.col("child_facility_reference") == "S")["root_facility_reference"]
            .item()
            for _ in range(40)
        }

        assert roots == {"U1"}

    @pytest.mark.parametrize(
        ("rows", "kept", "members"),
        [
            ([_map("F2", "F1", "facility"), _map("F1", "F2", "facility")], [], "F1, F2"),
            ([_map("F", "F", "facility")], [], "F"),
            (
                [
                    _map("B", "A", "facility"),
                    _map("C", "B", "facility"),
                    _map("B", "C", "facility"),
                ],
                [("A", "B")],
                "B, C",
            ),
        ],
        ids=["two_cycle", "self_loop", "cycle_with_tail"],
    )
    def test_every_cycle_member_becomes_a_root(
        self, rows: list[dict[str, str]], kept: list[tuple[str, str]], members: str
    ) -> None:
        graph = collect_facility_graph(_mappings(rows))

        assert _edges(rows) == kept
        assert [(e.code, e.actual_value) for e in graph.errors] == [
            (ERROR_FACILITY_MAPPING_CYCLE, members)
        ]


@pytest.mark.parametrize("regime", _REGIMES)
class TestLoanUnderTwoIndependentFacilities:
    """RC-01: F1, F2 standalone 2m MR; L1 1m drawn, mapped to both.

    L1 reduces only F1's headroom (the root of its lowest-referenced parent):
    EAD = 1,000,000 + (2,000,000 - 1,000,000) x 50% + 2,000,000 x 50% = 2,500,000
    = RWA (100%). Before the fix both headrooms fell: 2,000,000.
    """

    @staticmethod
    def _result(regime: str) -> AggregatedResultBundle:
        facilities = [
            make_facility(facility_reference=ref, limit=2_000_000.0, risk_type="medium_risk")
            for ref in ("F1", "F2")
        ]
        loans = [make_loan(loan_reference="L1", drawn_amount=1_000_000.0, interest=0.0)]
        return _run(regime, facilities, loans, [_map("F2", "L1"), _map("F1", "L1")])

    def test_only_one_headroom_is_consumed(self, regime: str) -> None:
        ledger = _ledger(self._result(regime))

        assert ledger["F1_UNDRAWN"]["undrawn_amount"] == pytest.approx(1_000_000.0)
        assert ledger["F2_UNDRAWN"]["undrawn_amount"] == pytest.approx(2_000_000.0)
        assert sum(r["ead_final"] for r in ledger.values()) == pytest.approx(2_500_000.0)
        assert sum(r["rwa_final"] for r in ledger.values()) == pytest.approx(2_500_000.0)

    def test_the_loan_hangs_under_the_kept_root(self, regime: str) -> None:
        ledger = _ledger(self._result(regime))

        assert ledger["L1"]["parent_facility_reference"] == "F1"

    def test_dq021_names_the_ignored_mapping(self, regime: str) -> None:
        found = _codes(self._result(regime), ERROR_FACILITY_MAPPING_MULTI_PARENT)

        assert [(e.exposure_reference, e.actual_value) for e in found] == [("L1", "F1, F2")]
        assert "root 'F1' only" in found[0].message
        assert "F2" in found[0].message


@pytest.mark.parametrize("regime", _REGIMES)
class TestLoanUnderTwoSubLimitsOfOneRoot:
    """SF-03 case D: umbrella G 100m (OC); sub-limits CCY 40m and REG 30m (OC);
    LX 20m drawn, mapped to BOTH sub-limits.

    The drawing reduces each sub-limit's own headroom (CCY 20m, REG 10m: an
    overlapping sub-limit genuinely constrains the same drawing) but G's headroom
    ONCE: 100m - 20m = 80m, so the waterfall emits CCY 20m, REG 10m and a 50m
    residual. Undrawn total 80m (60m before: G's headroom was netted twice).
    CRR undrawn EAD 80m x 50% = 40m; B31 80m x 40% = 32m.
    """

    @staticmethod
    def _result(regime: str) -> AggregatedResultBundle:
        facilities = [
            make_facility(facility_reference="G", limit=100e6, risk_type="OC"),
            make_facility(facility_reference="CCY", limit=40e6, risk_type="OC"),
            make_facility(facility_reference="REG", limit=30e6, risk_type="OC"),
        ]
        loans = [make_loan(loan_reference="LX", drawn_amount=20e6, interest=0.0)]
        mappings = [
            _map("G", "CCY", "facility"),
            _map("G", "REG", "facility"),
            _map("REG", "LX"),
            _map("CCY", "LX"),
        ]
        return _run(regime, facilities, loans, mappings)

    def test_root_headroom_is_reduced_once(self, regime: str) -> None:
        ledger = _ledger(self._result(regime))
        undrawn = {ref: row["undrawn_amount"] for ref, row in ledger.items() if ref != "LX"}

        assert undrawn == pytest.approx(
            {"G_UNDRAWN_CCY": 20e6, "G_UNDRAWN_REG": 10e6, "G_UNDRAWN_RESIDUAL": 50e6}
        )

    def test_undrawn_ead_is_the_hand_calculation(self, regime: str) -> None:
        ledger = _ledger(self._result(regime))
        undrawn_ead = sum(row["ead_final"] for ref, row in ledger.items() if ref != "LX")

        assert ledger["LX"]["ead_final"] == pytest.approx(20e6), "adequacy: LX appears once"
        assert undrawn_ead == pytest.approx(80e6 * _CCF_OC[regime])

    def test_dq021_says_the_root_is_reduced_once(self, regime: str) -> None:
        found = _codes(self._result(regime), ERROR_FACILITY_MAPPING_MULTI_PARENT)

        assert [(e.exposure_reference, e.actual_value) for e in found] == [("LX", "CCY, REG")]
        assert "only once" in found[0].message

    def test_the_exposure_row_hangs_under_the_lowest_parent(self, regime: str) -> None:
        # The mappings list REG before CCY; the row's own parent is the lowest
        # reference, not the first row (it was ``keep="first"`` over an unordered
        # frame), and its root is G.
        row = _ledger(self._result(regime))["LX"]

        assert (row["parent_facility_reference"], row["root_facility_reference"]) == ("CCY", "G")


@pytest.mark.parametrize("regime", _REGIMES)
class TestFacilityCycle:
    """RC-02: F1 <-> F2 (2m MR each); L1 0.5m drawn on F1.

    Both are treated as roots: EAD = 500,000 + 1,500,000 x 50% + 2,000,000 x 50%
    = 2,250,000 = RWA (100%). Before the fix both undrawn rows were dropped:
    500,000.
    """

    @staticmethod
    def _result(regime: str) -> AggregatedResultBundle:
        facilities = [
            make_facility(facility_reference=ref, limit=2e6, risk_type="medium_risk")
            for ref in ("F1", "F2")
        ]
        loans = [make_loan(loan_reference="L1", drawn_amount=500_000.0, interest=0.0)]
        mappings = [_map("F1", "L1"), _map("F1", "F2", "facility"), _map("F2", "F1", "facility")]
        return _run(regime, facilities, loans, mappings)

    def test_no_undrawn_commitment_is_dropped(self, regime: str) -> None:
        ledger = _ledger(self._result(regime))

        assert sorted(ledger) == ["F1_UNDRAWN", "F2_UNDRAWN", "L1"]
        assert sum(r["ead_final"] for r in ledger.values()) == pytest.approx(2_250_000.0)
        assert sum(r["rwa_final"] for r in ledger.values()) == pytest.approx(2_250_000.0)

    def test_dq022_names_the_cycle(self, regime: str) -> None:
        found = _codes(self._result(regime), ERROR_FACILITY_MAPPING_CYCLE)

        assert [e.actual_value for e in found] == ["F1, F2"]


@pytest.mark.parametrize("regime", _REGIMES)
class TestSubFacilityUnderTwoUmbrellas:
    """RC-02: S (2m, CPA) mapped under U1 (5m, CPA unrated 100%) AND U2 (5m, CPB
    CQS 1, 20%); L 1m drawn under S. MR 50% throughout.

    S is attached to U1 (lowest reference), whatever the row order:
    L 1,000,000 x 100% + U1_UNDRAWN_S (2m - 1m) x 50% x 100% + U1 residual
    (5m - 1m - 1m) x 50% x 100% + U2 5m x 50% x 20% = 1,000,000 + 500,000 +
    1,500,000 + 500,000 = 3,500,000. The verifier saw 3,500,000 or 4,300,000
    from one input across 12 identical runs.
    """

    @staticmethod
    def _result(regime: str, order: tuple[str, str]) -> AggregatedResultBundle:
        facilities = [
            make_facility(facility_reference="U1", counterparty_reference="CPA", limit=5e6),
            make_facility(facility_reference="U2", counterparty_reference="CPB", limit=5e6),
            make_facility(facility_reference="S", counterparty_reference="CPA", limit=2e6),
        ]
        loans = [
            make_loan(
                loan_reference="L", counterparty_reference="CPA", drawn_amount=1e6, interest=0.0
            )
        ]
        mappings = [
            _map(order[0], "S", "facility"),
            _map(order[1], "S", "facility"),
            _map("S", "L"),
        ]
        return _run(
            regime,
            facilities,
            loans,
            mappings,
            counterparties=[
                make_counterparty(counterparty_reference="CPA"),
                make_counterparty(counterparty_reference="CPB"),
            ],
            ratings=[
                make_rating(
                    rating_reference="RB",
                    counterparty_reference="CPB",
                    rating_type="external",
                    rating_agency="SP",
                    rating_value="AA",
                    cqs=1,
                    pd=None,
                )
            ],
        )

    @pytest.mark.parametrize("order", [("U1", "U2"), ("U2", "U1")])
    def test_rwa_is_the_hand_calculation_in_either_row_order(
        self, regime: str, order: tuple[str, str]
    ) -> None:
        ledger = _ledger(self._result(regime, order))

        assert sum(r["ead_final"] for r in ledger.values()) == pytest.approx(5_500_000.0)
        assert sum(r["rwa_final"] for r in ledger.values()) == pytest.approx(3_500_000.0)
        assert ledger["L"]["root_facility_reference"] == "U1"

    def test_dq021_names_the_kept_parent(self, regime: str) -> None:
        found = _codes(self._result(regime, ("U2", "U1")), ERROR_FACILITY_MAPPING_MULTI_PARENT)

        assert [(e.exposure_reference, e.actual_value) for e in found] == [("S", "U1, U2")]
        assert "attached to 'U1'" in found[0].message
