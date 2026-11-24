"""Unit tests: what a facility's undrawn headroom row is, before any CCF is applied.

Covers the review findings CM-01, SF-02 and CM-02 / SF-01 at the hierarchy
stage (``calculate_facility_undrawn``), the float-dust headroom gates (escape
log 2026-11-24: a headroom that is exactly zero in the inputs emits no row, in
any summation order), plus the HIE004 / HIE005 / HIE006 warnings that make each
non-default treatment visible (``unify_exposures``).
The money these rows carry once a CCF is applied is pinned end to end, in both
regimes, by ``tests/acceptance/test_facility_undrawn_commitments.py``.

Rule text relied on (quoted verbatim):

- PS1/26 Glossary, "commitment": "means any off-balance sheet contractual
  arrangement that has been offered by the institution and accepted by the
  obligor ... This includes but is not limited to any such arrangement that may
  be: (1) unconditionally cancelled by the institution at any time without prior
  notice to the obligor; or (2) cancelled by the institution if the obligor
  fails to meet conditions set out in the relevant agreement".
- PS1/26 Art. 111 Table A1 row (7), 10%: "Undrawn commitments which may be
  cancelled unconditionally at any time without notice, or that effectively
  provide for automatic cancellation due to a deterioration in an obligor's
  creditworthiness."
- CRR Annex I 4(a) (low risk, 0%): "undrawn credit facilities comprising
  agreements to lend ... which may be cancelled unconditionally at any time
  without notice".
- CRR Art. 4(1)(56) / PS1/26 Glossary, "conversion factor": "... the currently
  undrawn amount of the commitment from that facility, the extent of the
  commitment being determined by the advised limit."

So ``committed=False`` (an accepted, unconditionally cancellable commitment) is
a Table A1 row (7) commitment, not "no exposure", and the undrawn amount is
``limit - utilisation`` measured in ONE currency: the facility's.
"""

from __future__ import annotations

import dataclasses
import random
from datetime import date
from decimal import Decimal
from typing import Any

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.contracts.errors import (
    ERROR_FACILITY_HEADROOM_FX_RATE_MISSING,
    ERROR_FACILITY_LIMIT_MISSING,
    ERROR_UNCOMMITTED_FACILITY_RISK_TYPE,
)
from rwa_calc.domain.enums import ErrorCategory, ErrorSeverity
from rwa_calc.engine.hierarchy import HierarchyResolver
from tests.fixtures.raw_bundle import seal_raw_table
from tests.fixtures.resolved_bundle import make_counterparty_lookup

_VALUE = date(2025, 1, 1)
_MATURITY = date(2031, 6, 30)
_CRR = CalculationConfig.crr(reporting_date=date(2026, 6, 30))


def _facility(ref: str, limit: float | None, **overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "facility_reference": ref,
        "product_type": "RCF",
        "book_code": "CORP",
        "counterparty_reference": "CP1",
        "value_date": _VALUE,
        "maturity_date": _MATURITY,
        "currency": "GBP",
        "limit": limit,
        "committed": True,
        "seniority": "senior",
        "risk_type": "OC",
    }
    row.update(overrides)
    return row


def _loan(ref: str, drawn: float, **overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "loan_reference": ref,
        "product_type": "RCF_DRAWING",
        "book_code": "CORP",
        "counterparty_reference": "CP1",
        "value_date": _VALUE,
        "maturity_date": _MATURITY,
        "currency": "GBP",
        "drawn_amount": drawn,
        "interest": 0.0,
        "seniority": "senior",
    }
    row.update(overrides)
    return row


def _map(parent: str, child: str, child_type: str) -> dict[str, str]:
    return {"parent_facility_reference": parent, "child_reference": child, "child_type": child_type}


def _frames(
    facilities: list[dict[str, Any]],
    loans: list[dict[str, Any]],
    mappings: list[dict[str, str]],
    fx: list[tuple[str, float]] | None,
) -> tuple[pl.LazyFrame, pl.LazyFrame, pl.LazyFrame, pl.LazyFrame | None]:
    """Seal the input tables exactly as the loader seals them."""
    fac = seal_raw_table(pl.DataFrame(facilities).lazy(), "facilities")
    loan_frame = (
        pl.DataFrame(loans).lazy()
        if loans
        else pl.LazyFrame(schema={"loan_reference": pl.String, "drawn_amount": pl.Float64})
    )
    lns = seal_raw_table(loan_frame, "loans")
    map_frame = (
        pl.DataFrame(mappings).lazy()
        if mappings
        else pl.LazyFrame(
            schema={
                "parent_facility_reference": pl.String,
                "child_reference": pl.String,
                "child_type": pl.String,
            }
        )
    )
    maps = seal_raw_table(map_frame, "facility_mappings")
    rates = (
        None
        if fx is None
        else seal_raw_table(
            pl.DataFrame(
                {
                    "currency_from": [c for c, _ in fx],
                    "currency_to": ["GBP"] * len(fx),
                    "rate": [r for _, r in fx],
                }
            ).lazy(),
            "fx_rates",
        )
    )
    return fac, lns, maps, rates


def _undrawn(
    facilities: list[dict[str, Any]],
    loans: list[dict[str, Any]],
    mappings: list[dict[str, str]],
    *,
    fx: list[tuple[str, float]] | None = None,
    config: CalculationConfig | None = _CRR,
) -> pl.DataFrame:
    """Run ``calculate_facility_undrawn`` (via the resolver delegator) and collect it."""
    resolver = HierarchyResolver()
    fac, lns, maps, rates = _frames(facilities, loans, mappings, fx)
    root_lookup = resolver._build_facility_root_lookup(maps)
    return (
        resolver._calculate_facility_undrawn(
            fac, lns, None, maps, root_lookup, config=config, fx_rates=rates
        )
        .collect()
        .sort("exposure_reference")
    )


def _warnings(
    facilities: list[dict[str, Any]],
    loans: list[dict[str, Any]],
    mappings: list[dict[str, str]],
    *,
    fx: list[tuple[str, float]] | None = None,
    config: CalculationConfig = _CRR,
) -> list[Any]:
    """The hierarchy-stage errors ``unify_exposures`` returns for these inputs."""
    resolver = HierarchyResolver()
    fac, lns, maps, rates = _frames(facilities, loans, mappings, fx)
    _exposures, errors = resolver._unify_exposures(
        lns, None, fac, maps, make_counterparty_lookup(), config, fx_rates=rates
    )
    return errors


def _row(frame: pl.DataFrame, reference: str) -> dict[str, Any]:
    rows = frame.filter(pl.col("exposure_reference") == reference)
    assert rows.height == 1, f"expected exactly one {reference} row, got {rows.height}"
    return rows.row(0, named=True)


# =============================================================================
# CM-01 - committed=False is an accepted UCC commitment (Table A1 row 7)
# =============================================================================


class TestUncommittedFacilityEmitsUccRow:
    """``committed=False`` emits its undrawn row in the UCC bucket ``LR``."""

    def test_uncommitted_lr_facility_emits_full_headroom_row(self) -> None:
        # Arrange - the documented UCC encoding the engine used to delete.
        facilities = [_facility("F1", 10_000_000.0, committed=False, risk_type="LR")]

        # Act
        undrawn = _undrawn(facilities, [], [])

        # Assert
        row = _row(undrawn, "F1_UNDRAWN")
        assert row["undrawn_amount"] == pytest.approx(10_000_000.0)
        assert row["nominal_amount"] == pytest.approx(10_000_000.0)
        assert row["risk_type"] == "LR"

    def test_uncommitted_facility_with_null_risk_type_is_priced_as_ucc(self) -> None:
        """No risk_type: the UCC bucket, not the CCF residual (OC 40% / 1(k) 100%)."""
        facilities = [_facility("F1", 4_000_000.0, committed=False, risk_type=None)]

        undrawn = _undrawn(facilities, [], [])

        row = _row(undrawn, "F1_UNDRAWN")
        assert row["undrawn_amount"] == pytest.approx(4_000_000.0)
        assert row["risk_type"] == "LR"

    def test_uncommitted_facility_with_contradictory_risk_type_is_forced_to_lr(self) -> None:
        facilities = [_facility("F1", 4_000_000.0, committed=False, risk_type="medium_risk")]

        undrawn = _undrawn(facilities, [], [])

        assert _row(undrawn, "F1_UNDRAWN")["risk_type"] == "LR"

    def test_committed_facility_keeps_its_own_risk_type(self) -> None:
        """The forcing is confined to committed=False - a committed MR line stays MR."""
        facilities = [_facility("F1", 4_000_000.0, committed=True, risk_type="MR")]

        undrawn = _undrawn(facilities, [], [])

        assert _row(undrawn, "F1_UNDRAWN")["risk_type"] == "MR"

    def test_uncommitted_facility_nets_its_drawings(self) -> None:
        facilities = [_facility("F1", 1_000_000.0, committed=False, risk_type="LR")]
        loans = [_loan("L1", 100_000.0)]

        undrawn = _undrawn(facilities, loans, [_map("F1", "L1", "loan")])

        assert _row(undrawn, "F1_UNDRAWN")["undrawn_amount"] == pytest.approx(900_000.0)


# =============================================================================
# SF-02 - a sub-facility's OWN committed flag governs its waterfall row
# =============================================================================


def _umbrella(parent_committed: bool, parent_limit: float | None) -> list[dict[str, Any]]:
    return [
        _facility("P", parent_limit, committed=parent_committed, risk_type="LR"),
        _facility("S1", 10_000_000.0, risk_type="OC"),
        _facility("S2", 10_000_000.0, risk_type="OC"),
    ]


_UMBRELLA_MAPPINGS = [
    _map("P", "S1", "facility"),
    _map("P", "S2", "facility"),
    _map("S1", "L1", "loan"),
    _map("S2", "L2", "loan"),
]
_UMBRELLA_LOANS = [_loan("L1", 2_000_000.0), _loan("L2", 2_000_000.0)]


class TestMofSubFacilityCommittedFlag:
    """Committed sub-lines under an uncommitted umbrella are no longer dropped."""

    def test_committed_subs_under_uncommitted_umbrella_emit_their_rows(self) -> None:
        # Arrange - P limit 30m, committed=False; S1 / S2 committed OC 10m, 2m drawn each.
        # Parent headroom 30 - 4 = 26: S1 8, S2 8, residual 10 at the UCC bucket.
        facilities = _umbrella(parent_committed=False, parent_limit=30_000_000.0)

        # Act
        undrawn = _undrawn(facilities, _UMBRELLA_LOANS, _UMBRELLA_MAPPINGS)

        # Assert
        assert sorted(undrawn["exposure_reference"].to_list()) == [
            "P_UNDRAWN_RESIDUAL",
            "P_UNDRAWN_S1",
            "P_UNDRAWN_S2",
        ]
        for sub in ("P_UNDRAWN_S1", "P_UNDRAWN_S2"):
            row = _row(undrawn, sub)
            assert row["undrawn_amount"] == pytest.approx(8_000_000.0)
            assert row["risk_type"] == "OC"
        residual = _row(undrawn, "P_UNDRAWN_RESIDUAL")
        assert residual["undrawn_amount"] == pytest.approx(10_000_000.0)
        assert residual["risk_type"] == "LR"

    def test_uncommitted_sub_under_uncommitted_umbrella_takes_ucc_allocation(self) -> None:
        """Both UCC: the sub's slice and the residual sit in the same LR bucket."""
        facilities = [
            _facility("P", 30_000_000.0, committed=False, risk_type="LR"),
            _facility("S1", 10_000_000.0, risk_type="OC"),
            _facility("S2", 10_000_000.0, committed=False, risk_type="LR"),
        ]

        undrawn = _undrawn(facilities, _UMBRELLA_LOANS, _UMBRELLA_MAPPINGS)

        assert _row(undrawn, "P_UNDRAWN_S1")["risk_type"] == "OC"
        s2 = _row(undrawn, "P_UNDRAWN_S2")
        assert s2["risk_type"] == "LR"
        assert s2["undrawn_amount"] == pytest.approx(8_000_000.0)
        assert _row(undrawn, "P_UNDRAWN_RESIDUAL")["undrawn_amount"] == pytest.approx(10_000_000.0)

    def test_uncommitted_sub_under_uncapped_umbrella_emits_its_own_ucc_row(self) -> None:
        """No umbrella cap: the cancellable sub-line is its own Table A1 row (7) commitment."""
        facilities = [
            _facility("P", None, risk_type="LR"),
            _facility("S1", 10_000_000.0, risk_type="OC"),
            _facility("S2", 10_000_000.0, committed=False, risk_type="LR"),
        ]

        undrawn = _undrawn(facilities, _UMBRELLA_LOANS, _UMBRELLA_MAPPINGS)

        s2 = _row(undrawn, "P_UNDRAWN_S2")
        assert s2["risk_type"] == "LR"
        assert s2["undrawn_amount"] == pytest.approx(8_000_000.0)

    def test_uncommitted_sub_under_committed_capped_umbrella_adds_nothing(self) -> None:
        """The umbrella's committed headroom stays at the umbrella's own risk type.

        A committed, limited umbrella has already committed its whole headroom; a
        cancellable sub-line inside it is not a second commitment, so it takes no
        allocation and the residual keeps the umbrella's bucket. (This is what
        keeps CRR RWA unchanged by CM-01: LR is 0% there, and letting the sub
        consume headroom would move it out of the umbrella's higher bucket.)
        """
        facilities = [
            _facility("P", 30_000_000.0, risk_type="MR"),
            _facility("S1", 10_000_000.0, risk_type="OC"),
            _facility("S2", 10_000_000.0, committed=False, risk_type="FR"),
        ]

        undrawn = _undrawn(facilities, _UMBRELLA_LOANS, _UMBRELLA_MAPPINGS)

        assert "P_UNDRAWN_S2" not in undrawn["exposure_reference"].to_list()
        residual = _row(undrawn, "P_UNDRAWN_RESIDUAL")
        assert residual["risk_type"] == "MR"
        assert residual["undrawn_amount"] == pytest.approx(18_000_000.0)

    def test_uncommitted_sub_declaring_a_non_ucc_risk_type_is_weighted_and_emitted_as_lr(
        self,
    ) -> None:
        """An uncommitted sub-line is a UCC commitment whatever ``risk_type`` it declares.

        P 14m committed=False with 4m drawn leaves 10m of umbrella headroom. S1 is a
        committed OC line (8m headroom); S2 is committed=False but declares FR. Priced
        as LR, S2 sorts AFTER S1 in the CCF-descending waterfall: S1 takes 8m, S2 the
        last 2m, and HIE004 names S2. Read at its declared FR, S2 would sort first and
        take 8m, leaving S1 only 2m.
        """
        facilities = [
            _facility("P", 14_000_000.0, committed=False, risk_type="LR"),
            _facility("S1", 10_000_000.0, risk_type="OC"),
            _facility("S2", 10_000_000.0, committed=False, risk_type="FR"),
        ]

        undrawn = _undrawn(facilities, _UMBRELLA_LOANS, _UMBRELLA_MAPPINGS)
        errors = _warnings(facilities, _UMBRELLA_LOANS, _UMBRELLA_MAPPINGS)

        s1 = _row(undrawn, "P_UNDRAWN_S1")
        s2 = _row(undrawn, "P_UNDRAWN_S2")
        assert (s1["risk_type"], s1["undrawn_amount"]) == ("OC", pytest.approx(8_000_000.0))
        assert (s2["risk_type"], s2["undrawn_amount"]) == ("LR", pytest.approx(2_000_000.0))
        assert "P_UNDRAWN_RESIDUAL" not in undrawn["exposure_reference"].to_list()
        hie004 = [e for e in errors if e.code == ERROR_UNCOMMITTED_FACILITY_RISK_TYPE]
        assert [(e.exposure_reference, e.actual_value) for e in hie004] == [("S2", "FR")]


# =============================================================================
# CM-02 / SF-01 - headroom nets utilisation in the FACILITY's currency
# =============================================================================


class TestFacilityHeadroomCurrency:
    """``limit - utilisation`` subtracts like units: the child is converted first."""

    def test_eur_drawing_on_gbp_line_is_converted_before_netting(self) -> None:
        # Arrange - GBP 10m line, EUR 5m drawn, EUR->GBP 0.85: 10 - 4.25 = 5.75m.
        facilities = [_facility("F1", 10_000_000.0)]
        loans = [_loan("L1", 5_000_000.0, currency="EUR")]

        # Act
        undrawn = _undrawn(facilities, loans, [_map("F1", "L1", "loan")], fx=[("EUR", 0.85)])

        # Assert
        row = _row(undrawn, "F1_UNDRAWN")
        assert row["currency"] == "GBP"
        assert row["undrawn_amount"] == pytest.approx(5_750_000.0)

    def test_low_unit_currency_drawing_no_longer_clips_the_commitment_to_zero(self) -> None:
        """JPY 1bn at 0.005 is GBP 5m: raw netting (10m - 1bn) deleted the whole row."""
        facilities = [_facility("F1", 10_000_000.0)]
        loans = [_loan("L1", 1_000_000_000.0, currency="JPY")]

        undrawn = _undrawn(facilities, loans, [_map("F1", "L1", "loan")], fx=[("JPY", 0.005)])

        assert _row(undrawn, "F1_UNDRAWN")["undrawn_amount"] == pytest.approx(5_000_000.0)

    def test_gbp_drawing_on_eur_line_is_netted_in_eur(self) -> None:
        """The reverse direction overstated: EUR 10m - GBP 5m is EUR 4,117,647.06, not 5m."""
        facilities = [_facility("F1", 10_000_000.0, currency="EUR")]
        loans = [_loan("L1", 5_000_000.0, currency="GBP")]

        undrawn = _undrawn(facilities, loans, [_map("F1", "L1", "loan")], fx=[("EUR", 0.85)])

        row = _row(undrawn, "F1_UNDRAWN")
        assert row["currency"] == "EUR"
        assert row["undrawn_amount"] == pytest.approx(10_000_000.0 - 5_000_000.0 / 0.85)

    def test_drawing_with_no_rate_is_not_netted(self) -> None:
        """An amount the run cannot measure does not reduce the headroom."""
        facilities = [_facility("F1", 10_000_000.0)]
        loans = [_loan("L1", 6_500_000.0, currency="USD"), _loan("L2", 1_000_000.0)]
        mappings = [_map("F1", "L1", "loan"), _map("F1", "L2", "loan")]

        undrawn = _undrawn(facilities, loans, mappings, fx=[("EUR", 0.85)])

        assert _row(undrawn, "F1_UNDRAWN")["undrawn_amount"] == pytest.approx(9_000_000.0)

    def test_no_fx_table_means_no_rate_for_a_foreign_drawing(self) -> None:
        facilities = [_facility("F1", 10_000_000.0)]
        loans = [_loan("L1", 6_500_000.0, currency="USD")]

        undrawn = _undrawn(facilities, loans, [_map("F1", "L1", "loan")], fx=None)

        assert _row(undrawn, "F1_UNDRAWN")["undrawn_amount"] == pytest.approx(10_000_000.0)

    def test_fx_conversion_disabled_nets_raw_amounts(self) -> None:
        """``apply_fx_conversion=False``: every amount in the run is one unit of account."""
        config = dataclasses.replace(_CRR, apply_fx_conversion=False)
        facilities = [_facility("F1", 10_000_000.0)]
        loans = [_loan("L1", 6_500_000.0, currency="USD")]

        undrawn = _undrawn(
            facilities, loans, [_map("F1", "L1", "loan")], fx=[("USD", 0.77)], config=config
        )

        assert _row(undrawn, "F1_UNDRAWN")["undrawn_amount"] == pytest.approx(3_500_000.0)

    def test_same_currency_netting_is_unchanged(self) -> None:
        facilities = [_facility("F1", 10_000_000.0, currency="EUR")]
        loans = [_loan("L1", 3_333_333.33, currency="EUR")]

        undrawn = _undrawn(facilities, loans, [_map("F1", "L1", "loan")], fx=[("EUR", 0.85)])

        # Exact equality: the same-currency path must be byte-for-byte the old one.
        assert _row(undrawn, "F1_UNDRAWN")["undrawn_amount"] == 10_000_000.0 - 3_333_333.33

    def test_mof_currency_sublimit_is_netted_and_capped_in_the_parent_currency(self) -> None:
        """SF-01's MOF case: GBP 20 umbrella, EUR 10 sublimit, EUR 4 drawn, EUR->GBP 0.85.

        Parent headroom 20 - 3.4 = 16.6 GBP; the sub's headroom EUR 6 is GBP 5.1;
        the residual is 16.6 - 5.1 = 11.5 GBP. Raw netting gave 16 / 6 / 10.
        """
        facilities = [
            _facility("P", 20.0, risk_type="MR"),
            _facility("S1", 10.0, currency="EUR", risk_type="OC"),
        ]
        loans = [_loan("L1", 4.0, currency="EUR")]
        mappings = [_map("P", "S1", "facility"), _map("S1", "L1", "loan")]

        undrawn = _undrawn(facilities, loans, mappings, fx=[("EUR", 0.85)])

        assert _row(undrawn, "P_UNDRAWN_S1")["undrawn_amount"] == pytest.approx(5.1)
        assert _row(undrawn, "P_UNDRAWN_RESIDUAL")["undrawn_amount"] == pytest.approx(11.5)

    def test_mof_sub_limit_with_no_rate_takes_no_slice(self) -> None:
        """A CHF sub-limit under a GBP umbrella with no CHF rate cannot be capped in GBP.

        Its headroom is unmeasurable in the umbrella's currency (HIE005), so it takes
        no slice of the waterfall and the umbrella's residual carries the whole 20 at
        the umbrella's own risk type. Netting it raw would have given S1 10 and the
        residual only 10.
        """
        facilities = [
            _facility("P", 20.0, risk_type="MR"),
            _facility("S1", 10.0, currency="CHF", risk_type="OC"),
        ]

        undrawn = _undrawn(facilities, [], [_map("P", "S1", "facility")], fx=[("EUR", 0.85)])

        assert undrawn["exposure_reference"].to_list() == ["P_UNDRAWN_RESIDUAL"]
        residual = _row(undrawn, "P_UNDRAWN_RESIDUAL")
        assert (residual["risk_type"], residual["undrawn_amount"]) == ("MR", pytest.approx(20.0))


# =============================================================================
# Float dust - a headroom that is zero in the inputs emits no row, in any order
# =============================================================================


def _exactly_drawn_book(
    count: int, seed: int
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, str]]]:
    """``count`` facilities, each drawn to exactly its limit by 3-5 cent-denominated loans.

    The limit is the DECIMAL sum of the drawings, so every facility's headroom is
    exactly zero. The binary sum of the same drawings lands an ulp either side of
    the limit for roughly one facility in twelve - and which side depends on the
    order the grouped sum meets the rows in.
    """
    rng = random.Random(seed)
    facilities: list[dict[str, Any]] = []
    loans: list[dict[str, Any]] = []
    mappings: list[dict[str, str]] = []
    for f in range(count):
        drawings = [rng.randint(100, 10**9) / 100 for _ in range(rng.choice((3, 4, 5)))]
        limit = float(sum(Decimal(str(d)) for d in drawings))
        facilities.append(_facility(f"F{f}", limit))
        for i, drawn in enumerate(drawings):
            loans.append(_loan(f"F{f}L{i}", drawn))
            mappings.append(_map(f"F{f}", f"F{f}L{i}", "loan"))
    return facilities, loans, mappings


class TestHeadroomFloatDust:
    """Every headroom gate reads summation residue as zero, whatever order it was summed in.

    Headroom is a difference of sums (``limit - sum(drawn)``; the MOF residual is
    ``headroom - sum(allocation)``). Where the inputs make it exactly zero, the
    binary result is +/- one ulp of the amounts involved - 9.3e-10 at GBP 7.8m -
    and a ``> 0`` gate turned a positive ulp into an exposure row. The sign of the
    ulp depends on summation order, which is what made ``spill_edges=True`` (parquet
    re-read in chunks) emit a different, run-to-run varying set of
    ``<facility>_UNDRAWN_RESIDUAL`` rows on the 200K benchmark. Every amount below
    is cent-denominated and chosen because it reproduces the residue.
    """

    def test_subs_absorbing_the_umbrella_headroom_leave_no_residual_row(self) -> None:
        # Arrange - P 7,816,127.22; S1 1,343,643.31 + S2 8,474,337.52 cover it.
        # S1 takes 1,343,643.31, S2 the remaining 6,472,483.91: residual exactly 0
        # (binary: 9.313225746154785e-10).
        facilities = [
            _facility("P", 7_816_127.22),
            _facility("S1", 1_343_643.31),
            _facility("S2", 8_474_337.52),
        ]
        mappings = [_map("P", "S1", "facility"), _map("P", "S2", "facility")]

        # Act
        undrawn = _undrawn(facilities, [], mappings)

        # Assert
        assert undrawn["exposure_reference"].to_list() == ["P_UNDRAWN_S1", "P_UNDRAWN_S2"]
        assert undrawn["undrawn_amount"].sum() == pytest.approx(7_816_127.22)

    def test_a_sub_after_the_umbrella_is_exhausted_takes_no_slice(self) -> None:
        """S1 (FR, sorted first) takes the whole headroom; S2 is left exactly nothing.

        Binary: S2's slice is ``H - ((h1 + h2) - h2)`` = 4.656612873077393e-10.
        """
        facilities = [
            _facility("P", 3_751_040.52),
            _facility("S1", 3_751_040.52, risk_type="FR"),
            _facility("S2", 9_823_853.46, risk_type="OC"),
        ]
        mappings = [_map("P", "S1", "facility"), _map("P", "S2", "facility")]

        undrawn = _undrawn(facilities, [], mappings)

        assert undrawn["exposure_reference"].to_list() == ["P_UNDRAWN_S1"]

    def test_a_facility_drawn_to_its_limit_emits_no_undrawn_row(self) -> None:
        """6,737,013.93 + 6,259,882.56 is 12,996,896.49; binary headroom 1.86e-09."""
        facilities = [_facility("F1", 12_996_896.49)]
        loans = [_loan("L1", 6_737_013.93), _loan("L2", 6_259_882.56)]
        mappings = [_map("F1", "L1", "loan"), _map("F1", "L2", "loan")]

        undrawn = _undrawn(facilities, loans, mappings)

        assert undrawn["exposure_reference"].to_list() == []

    def test_headroom_rows_do_not_depend_on_the_order_drawings_are_summed_in(self) -> None:
        """The spill-mode mechanism at unit scale: same book, rows met in reverse.

        Measured before the fix on 3,000 exactly-drawn facilities: 258 dust
        ``_UNDRAWN`` rows in input order, 271 in reverse, and the two sets differed.
        Every facility here is drawn to exactly its limit, so the only correct row
        set - in either order - is the empty one.
        """
        facilities, loans, mappings = _exactly_drawn_book(count=1_000, seed=11)

        forward = set(_undrawn(facilities, loans, mappings)["exposure_reference"])
        reverse = set(_undrawn(facilities, loans[::-1], mappings)["exposure_reference"])

        assert (forward, reverse) == (set(), set())

    def test_a_penny_of_real_headroom_on_a_large_line_is_kept(self) -> None:
        """The tolerance is dust-sized, not money-sized: GBP 0.01 on a GBP 50m line survives."""
        facilities = [_facility("F1", 50_000_000.01)]
        loans = [_loan("L1", 50_000_000.0)]

        undrawn = _undrawn(facilities, loans, [_map("F1", "L1", "loan")])

        assert _row(undrawn, "F1_UNDRAWN")["undrawn_amount"] == pytest.approx(0.01, abs=1e-6)

    def test_a_penny_of_real_umbrella_residual_is_kept(self) -> None:
        facilities = [
            _facility("P", 50_000_000.01),
            _facility("S1", 30_000_000.0),
            _facility("S2", 20_000_000.0),
        ]
        mappings = [_map("P", "S1", "facility"), _map("P", "S2", "facility")]

        undrawn = _undrawn(facilities, [], mappings)

        residual = _row(undrawn, "P_UNDRAWN_RESIDUAL")
        assert residual["undrawn_amount"] == pytest.approx(0.01, abs=1e-6)


# =============================================================================
# HIE004 / HIE005 / HIE006 - the warnings that make each treatment visible
# =============================================================================


def _codes(errors: list[Any], code: str) -> list[Any]:
    return [e for e in errors if e.code == code]


class TestFacilityUndrawnWarnings:
    """One warning per affected facility; none on clean input."""

    def test_clean_book_raises_none_of_the_three(self) -> None:
        facilities = [
            _facility("F1", 10_000_000.0),
            _facility("F2", 1_000_000.0, committed=False, risk_type="LR"),
        ]
        loans = [_loan("L1", 5_000_000.0, currency="EUR")]

        errors = _warnings(facilities, loans, [_map("F1", "L1", "loan")], fx=[("EUR", 0.85)])

        assert {e.code for e in errors} & {
            ERROR_UNCOMMITTED_FACILITY_RISK_TYPE,
            ERROR_FACILITY_HEADROOM_FX_RATE_MISSING,
            ERROR_FACILITY_LIMIT_MISSING,
        } == set()

    def test_hie004_names_an_uncommitted_facility_declaring_a_non_ucc_risk_type(self) -> None:
        facilities = [
            _facility("F_MR", 1_000_000.0, committed=False, risk_type="medium_risk"),
            _facility("F_LR", 1_000_000.0, committed=False, risk_type="low_risk"),
            _facility("F_NULL", 1_000_000.0, committed=False, risk_type=None),
        ]

        found = _codes(_warnings(facilities, [], []), ERROR_UNCOMMITTED_FACILITY_RISK_TYPE)

        assert len(found) == 1
        error = found[0]
        assert error.exposure_reference == "F_MR"
        assert error.actual_value == "medium_risk"
        assert error.severity == ErrorSeverity.WARNING
        assert error.category == ErrorCategory.HIERARCHY

    def test_hie005_names_the_facility_and_the_unconvertible_currency(self) -> None:
        facilities = [_facility("F1", 10_000_000.0)]
        loans = [_loan("L1", 6_500_000.0, currency="USD"), _loan("L2", 1.0, currency="USD")]
        mappings = [_map("F1", "L1", "loan"), _map("F1", "L2", "loan")]

        found = _codes(
            _warnings(facilities, loans, mappings, fx=[("EUR", 0.85)]),
            ERROR_FACILITY_HEADROOM_FX_RATE_MISSING,
        )

        assert len(found) == 1, "one warning per (facility, currency), not per drawing"
        assert found[0].exposure_reference == "F1"
        assert found[0].actual_value == "USD"
        assert found[0].severity == ErrorSeverity.WARNING

    def test_hie005_names_a_sub_limit_that_cannot_be_put_in_the_umbrella_currency(
        self,
    ) -> None:
        facilities = [
            _facility("P", 20.0, risk_type="MR"),
            _facility("S1", 10.0, currency="CHF", risk_type="OC"),
        ]

        found = _codes(
            _warnings(facilities, [], [_map("P", "S1", "facility")], fx=[("EUR", 0.85)]),
            ERROR_FACILITY_HEADROOM_FX_RATE_MISSING,
        )

        assert [(e.exposure_reference, e.actual_value) for e in found] == [("S1", "CHF")]

    def test_hie005_is_silent_when_conversion_is_disabled(self) -> None:
        config = dataclasses.replace(_CRR, apply_fx_conversion=False)
        facilities = [_facility("F1", 10_000_000.0)]
        loans = [_loan("L1", 6_500_000.0, currency="USD")]

        errors = _warnings(facilities, loans, [_map("F1", "L1", "loan")], config=config)

        assert _codes(errors, ERROR_FACILITY_HEADROOM_FX_RATE_MISSING) == []

    def test_hie006_names_a_facility_with_no_limit(self) -> None:
        facilities = [_facility("F_NOLIMIT", None), _facility("F_OK", 1_000_000.0)]

        found = _codes(_warnings(facilities, [], []), ERROR_FACILITY_LIMIT_MISSING)

        assert [e.exposure_reference for e in found] == ["F_NOLIMIT"]
        assert found[0].severity == ErrorSeverity.WARNING

    def test_warnings_follow_the_sample_cap_contract(self) -> None:
        """Five facilities named per code, then ONE summary with the true omitted count.

        A systemic input gap (a whole multi-currency book with no FX table) must
        stay readable: the stress book's 10k facilities would otherwise raise
        one warning each.
        """
        facilities = [_facility(f"F{i}", 1_000_000.0) for i in range(8)]
        loans = [_loan(f"L{i}", 1.0, currency="USD" if i % 2 else "CHF") for i in range(8)]
        mappings = [_map(f"F{i}", f"L{i}", "loan") for i in range(8)]

        found = _codes(
            _warnings(facilities, loans, mappings, fx=[("EUR", 0.85)]),
            ERROR_FACILITY_HEADROOM_FX_RATE_MISSING,
        )

        named = [e for e in found if e.exposure_reference is not None]
        summaries = [e for e in found if e.exposure_reference is None]
        assert [e.exposure_reference for e in named] == ["F0", "F1", "F2", "F3", "F4"]
        assert len(summaries) == 1
        assert summaries[0].actual_value == "3"
        assert "CHF, USD" in summaries[0].message

    def test_hie006_is_not_raised_for_an_umbrella_whose_null_limit_means_uncapped(self) -> None:
        facilities = _umbrella(parent_committed=True, parent_limit=None)

        found = _codes(
            _warnings(facilities, _UMBRELLA_LOANS, _UMBRELLA_MAPPINGS),
            ERROR_FACILITY_LIMIT_MISSING,
        )

        assert found == []
