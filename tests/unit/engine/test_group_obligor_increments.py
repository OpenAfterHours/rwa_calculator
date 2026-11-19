"""
Group-wide obligor increments for solo / sub-consolidated runs (RC-07 / RG-02 / RE-12).

``whole_group_increments`` compares the run's own hierarchy-resolved exposures
with the same resolution of the whole reporting group, per obligor-group key
(lending group, else counterparty), and publishes what the rest of the group adds
— to the retail-threshold aggregate and to the CRR Art. 501 E* — as
``max(whole - own, 0)``. ``compute_e_star_group_drawn`` then adds the E* half once
per key.

Rules: CRR Art. 123(c) "the total amount owed to the institution and parent
undertakings and its subsidiaries"; CRR Art. 501(1) E* "the total amount owed to
the institution, its subsidiaries, its parent undertakings and other subsidiaries
of those parent undertakings ... excluding claims or contingent claims secured on
residential property collateral"; PS1/26 Art. 123A(1)(b)(ii) "owed to the
institution, its parent undertakings, its subsidiaries and subsidiaries of its
parent undertakings ..., excluding all residential real estate exposures".
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.engine.hierarchy.group_obligor import (
    attach_out_of_scope_threshold,
    whole_group_increments,
)
from rwa_calc.engine.supporting_factors import compute_e_star_group_drawn


def _frame(rows: list[tuple[str, str | None, str | None, float, float, float]]) -> pl.LazyFrame:
    """(exposure, counterparty, lending group, drawn, interest, residential cover)."""
    return pl.LazyFrame(
        {
            "exposure_reference": [r[0] for r in rows],
            "counterparty_reference": [r[1] for r in rows],
            "lending_group_reference": [r[2] for r in rows],
            "drawn_amount": [r[3] for r in rows],
            "interest": [r[4] for r in rows],
            "residential_collateral_value": [r[5] for r in rows],
            "exposure_for_retail_threshold": [r[3] - r[5] for r in rows],
        },
        schema_overrides={
            "counterparty_reference": pl.String,
            "lending_group_reference": pl.String,
        },
    )


def _increments(own: pl.LazyFrame, whole: pl.LazyFrame) -> dict[str, tuple[float, float]]:
    df = whole_group_increments(own, whole).collect()
    return {
        r["obligor_group_key"]: (r["group_threshold_increment"], r["group_e_star_increment"])
        for r in df.to_dicts()
    }


def test_increment_is_what_the_rest_of_the_group_adds() -> None:
    """Own 600,000; whole group 1,200,000 + 5,000 interest elsewhere -> +600,000 / +605,000."""
    own = _frame([("L_P", "IND1", None, 600_000.0, 0.0, 0.0)])
    whole = _frame(
        [
            ("L_P", "IND1", None, 600_000.0, 0.0, 0.0),
            ("L_S", "IND1", None, 600_000.0, 5_000.0, 0.0),
        ]
    )

    assert _increments(own, whole) == {"IND1": (600_000.0, 605_000.0)}


def test_pledge_spanning_the_scope_is_allocated_as_the_whole_group_allocates_it() -> None:
    """A 300,000 residential pledge over both books is not netted twice.

    The solo pass gives the whole pledge to its one loan (600,000 - 300,000 =
    300,000); the group pass spreads it 150,000 / 150,000 (450,000 + 450,000 =
    900,000). The increment is 900,000 - 300,000 = 600,000, so the solo figure
    becomes the group's 900,000 — over the GBP 880,000 limit. Summing only the
    other entity's rows (450,000) would give 750,000 and pass the obligor as
    retail on pledge cover the solo pass already used.
    """
    own = _frame([("L_P", "IND1", None, 600_000.0, 0.0, 300_000.0)])
    whole = _frame(
        [
            ("L_P", "IND1", None, 600_000.0, 0.0, 150_000.0),
            ("L_S", "IND1", None, 600_000.0, 0.0, 150_000.0),
        ]
    )

    threshold_increment, _e_star = _increments(own, whole)["IND1"]
    assert 300_000.0 + threshold_increment == pytest.approx(900_000.0)


def test_lending_group_members_aggregate_on_the_group_key() -> None:
    """Two members of lending group G: the key is G, the other member's debt counts."""
    own = _frame([("L_A", "CP_A", "G", 400_000.0, 0.0, 0.0)])
    whole = _frame(
        [
            ("L_A", "CP_A", "G", 400_000.0, 0.0, 0.0),
            ("L_B", "CP_B", "G", 700_000.0, 0.0, 0.0),
        ]
    )

    assert _increments(own, whole) == {"G": (700_000.0, 700_000.0)}


def test_keys_only_the_run_holds_get_no_increment_and_none_is_negative() -> None:
    """An intragroup row kept on a solo run is absent from the group pass: no row.

    And a key the group pass sees with LESS than the run (never expected) clips
    to zero, so the increment can only add.
    """
    own = _frame(
        [
            ("L_IG", "BANK_B_CP", None, 1_000_000.0, 0.0, 0.0),
            ("L_X", "CP_X", None, 500_000.0, 0.0, 0.0),
        ]
    )
    whole = _frame([("L_X", "CP_X", None, 400_000.0, 0.0, 0.0)])

    assert _increments(own, whole) == {"CP_X": (0.0, 0.0)}


def test_attach_broadcasts_the_threshold_increment_to_every_row_of_the_key() -> None:
    own = _frame(
        [
            ("L_P1", "IND1", None, 100_000.0, 0.0, 0.0),
            ("L_P2", "IND1", None, 200_000.0, 0.0, 0.0),
            ("L_Q", "IND2", None, 50_000.0, 0.0, 0.0),
        ]
    )
    increments = pl.LazyFrame(
        {
            "obligor_group_key": ["IND1"],
            "group_threshold_increment": [700_000.0],
            "group_e_star_increment": [700_000.0],
        }
    )

    df = attach_out_of_scope_threshold(own, increments).collect()

    assert df["exposure_reference"].to_list() == ["L_P1", "L_P2", "L_Q"]
    assert df["out_of_scope_group_adjusted_exposure"].to_list() == [700_000.0, 700_000.0, None]


def test_e_star_adds_the_group_increment_once_per_key() -> None:
    """Two own rows of 1,000,000 + a 2,000,000 group increment: E* 4,000,000 on both."""
    exposures = _frame(
        [
            ("L1", "SME1", None, 1_000_000.0, 0.0, 0.0),
            ("L2", "SME1", None, 1_000_000.0, 0.0, 0.0),
            ("L3", "SME2", None, 500_000.0, 0.0, 0.0),
        ]
    )
    increments = pl.LazyFrame(
        {
            "obligor_group_key": ["SME1"],
            "group_threshold_increment": [2_000_000.0],
            "group_e_star_increment": [2_000_000.0],
        }
    )
    config = CalculationConfig.crr(reporting_date=date(2026, 6, 30))

    df = compute_e_star_group_drawn(exposures, config, group_increments=increments).collect()

    assert df["exposure_reference"].to_list() == ["L1", "L2", "L3"]
    assert df["e_star_group_drawn"].to_list() == [4_000_000.0, 4_000_000.0, 500_000.0]


def test_e_star_without_increments_is_the_run_sum() -> None:
    """No artifact (unscoped / whole-group run): the windowed sum alone."""
    exposures = _frame(
        [
            ("L1", "SME1", None, 1_000_000.0, 10_000.0, 0.0),
            ("L2", "SME1", None, 1_000_000.0, 0.0, 400_000.0),
        ]
    )
    config = CalculationConfig.crr(reporting_date=date(2026, 6, 30))

    df = compute_e_star_group_drawn(exposures, config).collect()

    assert df["e_star_group_drawn"].to_list() == [1_610_000.0, 1_610_000.0]
