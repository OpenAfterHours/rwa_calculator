"""
Unit tests for redistribute_non_beneficial() — reallocating a declined guarantor's share.

When an exposure has several guarantors and the calculator declines one (its risk
weight does not beat the obligor's), the declined item is disregarded and the
remaining guarantors are re-sized on their own, each covering at most its
protection GA (CRR Art. 235(1) / PS1/26 Art. 235(1)(a): Eg = min(GA, E), on the
CCF=100% basis). Basis taken over by a beneficial guarantor leaves the declined
legs, and every per-leg money carrier moves with it.

Every frame here is built the way ``engine/crm/guarantees.py::_apply_guarantee_splits``
builds one (``_split``): each guarantor's protection GA is pro-rated by
``min(1, E / sum(GA))``, its leg's ``guarantee_amount`` is that share of E, and the
leg's exposure value and covered amount are the share times the CCF. So a
guarantor has unused protection ONLY when the guarantors over-cover E — in which
case the remainder leg is empty. The previous version of this file used frames
with spare protection beside a non-empty remainder, which the split cannot
produce, and asserted the remainder absorbing basis.

References:
    CRR Art. 193(1); PS1/26 Art. 193(2A): the decline.
    CRR Art. 235(1), 236(3); PS1/26 Art. 235(1): covered part on the CCF=100% basis.
    GitHub issue #239; plan item P1.458 (review GT-09).
"""

from __future__ import annotations

from dataclasses import dataclass

import polars as pl
import pytest

from rwa_calc.engine.crm.guarantees import leg_share_carriers, redistribute_non_beneficial

_PARENT = "EXP001"


@dataclass(frozen=True)
class _G:
    """One guarantor: protection GA, its risk weight, and the calculator's verdict."""

    ref: str
    protection: float
    rw: float
    beneficial: bool


def _split(
    guarantors: list[_G],
    *,
    exposure: float = 1000.0,
    ccf: float = 1.0,
    parent: str = _PARENT,
    role: str | None = None,
    approach: str = "standardised",
) -> list[dict]:
    """Legs as the CRM split emits them for one parent (see the module docstring)."""
    total = sum(g.protection for g in guarantors)
    scale = min(1.0, exposure / total) if total > 0 else 0.0
    rows: list[dict] = []
    for g in guarantors:
        share = g.protection * scale
        ead = share * ccf
        rows.append(
            {
                "parent_exposure_reference": parent,
                "exposure_reference": f"{parent}__G_{g.ref}",
                "is_guarantee_beneficial": g.beneficial and ead > 0,
                "guarantor_rw": g.rw,
                "guarantee_amount": share,
                "original_guarantee_amount": g.protection,
                "guaranteed_portion": ead,
                "unguaranteed_portion": 0.0,
                "ead_after_collateral": ead,
                "ead_final": ead,
                "drawn_amount": share,
                "ead_for_crm": exposure,
                "re_split_role": role,
                "approach": approach,
            }
        )
    retained = exposure - sum(g.protection * scale for g in guarantors)
    rows.append(
        {
            "parent_exposure_reference": parent,
            "exposure_reference": f"{parent}__REM",
            "is_guarantee_beneficial": False,
            "guarantor_rw": None,
            "guarantee_amount": 0.0,
            "original_guarantee_amount": 0.0,
            "guaranteed_portion": 0.0,
            "unguaranteed_portion": retained * ccf,
            "ead_after_collateral": retained * ccf,
            "ead_final": retained * ccf,
            "drawn_amount": retained,
            "ead_for_crm": exposure,
            "re_split_role": role,
            "approach": approach,
        }
    )
    return rows


def _frame(rows: list[dict]) -> pl.LazyFrame:
    return pl.LazyFrame(
        rows, schema_overrides={"guarantor_rw": pl.Float64, "re_split_role": pl.String}
    )


def _column(result: pl.DataFrame, column: str) -> dict[str, float]:
    return dict(zip(result["exposure_reference"], result[column], strict=True))


def _approx(values: dict[str, float]) -> dict[str, object]:
    return {ref: pytest.approx(value, abs=1e-9) for ref, value in values.items()}


class TestReallocation:
    """The declined share moves to beneficial guarantors with protection left over."""

    def test_declined_share_moves_to_the_beneficial_leg(self) -> None:
        """G1 (GA 1000) was pro-rated to 666.67; declining G2 lets it cover all of E."""
        # Arrange
        lf = _frame(_split([_G("G1", 1000.0, 0.2, True), _G("G2", 500.0, 1.0, False)]))

        # Act
        result = redistribute_non_beneficial(lf).collect()

        # Assert
        assert _column(result, "ead_final") == _approx(
            {"EXP001__G_G1": 1000.0, "EXP001__G_G2": 0.0, "EXP001__REM": 0.0}
        )

    def test_capacity_limits_the_move_and_the_rest_stays_declined(self) -> None:
        """G1 has 200 spare: G2 keeps 400 of its 600, still declined, still covered."""
        # Arrange
        lf = _frame(_split([_G("G1", 600.0, 0.2, True), _G("G2", 900.0, 1.0, False)]))
        assert lf.collect()["guarantee_amount"].to_list()[:2] == pytest.approx([400.0, 600.0])

        # Act
        result = redistribute_non_beneficial(lf).collect()

        # Assert
        assert _column(result, "guaranteed_portion") == _approx(
            {"EXP001__G_G1": 600.0, "EXP001__G_G2": 400.0, "EXP001__REM": 0.0}
        )

    def test_lowest_risk_weight_guarantor_fills_first(self) -> None:
        """Freed 333.33: G1 (5%) takes its full 266.67 spare, G2 (20%) the other 66.67."""
        # Arrange
        lf = _frame(
            _split(
                [
                    _G("G1", 600.0, 0.05, True),
                    _G("G2", 600.0, 0.20, True),
                    _G("G3", 600.0, 1.00, False),
                ]
            )
        )

        # Act
        result = redistribute_non_beneficial(lf).collect()

        # Assert
        assert _column(result, "guarantee_amount") == _approx(
            {"EXP001__G_G1": 600.0, "EXP001__G_G2": 400.0, "EXP001__G_G3": 0.0, "EXP001__REM": 0.0}
        )

    def test_spare_protection_is_measured_on_the_ccf_100_basis(self) -> None:
        """Undrawn E = 1000 at CCF 50%, G1 30% + G2 40%: G1 is at its full GA already.

        Comparing G1's GA (300, CCF=100% basis) with its post-CCF covered amount (150)
        would invent 150 of capacity and cover 300 on a leg whose exposure value is 150.
        """
        # Arrange
        lf = _frame(_split([_G("G1", 300.0, 0.2, True), _G("G2", 400.0, 1.0, False)], ccf=0.5))

        # Act
        result = redistribute_non_beneficial(lf).collect()

        # Assert
        assert _column(result, "guaranteed_portion") == _approx(
            {"EXP001__G_G1": 150.0, "EXP001__G_G2": 200.0, "EXP001__REM": 0.0}
        )

    def test_carriers_move_with_the_leg_and_parent_carriers_do_not(self) -> None:
        """Split amounts and caller extras scale by the leg factor; GA and E stay put."""
        # Arrange
        rows = _split([_G("G1", 1000.0, 0.2, True), _G("G2", 500.0, 1.0, False)])
        for row in rows:
            row["rwa_irb_original"] = row["ead_final"] * 0.8
        lf = _frame(rows)

        # Act
        result = redistribute_non_beneficial(lf, extra_carriers=("rwa_irb_original",)).collect()

        # Assert
        g1 = result.row(0, named=True)
        assert (
            g1["drawn_amount"],
            g1["rwa_irb_original"],
            g1["original_guarantee_amount"],
            g1["ead_for_crm"],
        ) == (pytest.approx(1000.0), pytest.approx(800.0), 1000.0, 1000.0)

    def test_every_leg_share_carrier_on_the_frame_is_conserved(self) -> None:
        """Summed over the parent, a split amount is unchanged by an on-balance move."""
        # Arrange
        lf = _frame(_split([_G("G1", 1000.0, 0.2, True), _G("G2", 500.0, 1.0, False)]))
        present = [c for c in leg_share_carriers() if c in lf.collect_schema().names()]
        before = lf.select(present).sum().collect().row(0)

        # Act
        after = redistribute_non_beneficial(lf).select(present).sum().collect().row(0)

        # Assert
        assert after == pytest.approx(before)


class TestNothingMoves:
    """Cases where the CRM split's allocation stands."""

    def test_all_beneficial(self) -> None:
        # Arrange
        lf = _frame(_split([_G("G1", 600.0, 0.2, True), _G("G2", 900.0, 0.5, True)]))

        # Act
        result = redistribute_non_beneficial(lf).collect()

        # Assert
        assert _column(result, "ead_final") == _column(lf.collect(), "ead_final")

    def test_all_declined_keeps_every_covered_amount(self) -> None:
        """No beneficial leg: declined legs are not zeroed, the blend ignores them."""
        # Arrange
        lf = _frame(_split([_G("G1", 600.0, 1.0, False), _G("G2", 900.0, 1.5, False)]))

        # Act
        result = redistribute_non_beneficial(lf).collect()

        # Assert
        assert _column(result, "guaranteed_portion") == _column(lf.collect(), "guaranteed_portion")

    def test_under_covered_exposure_has_no_spare_protection(self) -> None:
        """30% + 40% of a drawn E: both legs are at their full GA, the remainder holds 300."""
        # Arrange
        lf = _frame(_split([_G("G1", 300.0, 0.2, True), _G("G2", 400.0, 1.0, False)]))

        # Act
        result = redistribute_non_beneficial(lf).collect()

        # Assert
        assert _column(result, "ead_final") == _approx(
            {"EXP001__G_G1": 300.0, "EXP001__G_G2": 400.0, "EXP001__REM": 300.0}
        )

    def test_declined_leg_with_no_exposure_value_frees_nothing(self) -> None:
        """A 0% CCF leg costs nothing; moving its basis to G1 could only add RWEA."""
        # Arrange
        rows = _split([_G("G1", 1000.0, 0.2, True), _G("G2", 500.0, 1.0, False)])
        rows[1].update(guaranteed_portion=0.0, ead_final=0.0, ead_after_collateral=0.0)
        lf = _frame(rows)

        # Act
        result = redistribute_non_beneficial(lf).collect()

        # Assert
        assert _column(result, "guarantee_amount") == _column(lf.collect(), "guarantee_amount")

    def test_legs_out_of_scope_do_not_move(self) -> None:
        """The output-floor SA pass passes the SA-branch predicate: IRB legs are left alone."""
        # Arrange
        lf = _frame(
            _split(
                [_G("G1", 1000.0, 0.2, True), _G("G2", 500.0, 1.0, False)],
                approach="foundation_irb",
            )
        )

        # Act
        result = redistribute_non_beneficial(
            lf, scope=pl.col("approach") == "standardised"
        ).collect()

        # Assert
        assert _column(result, "ead_final") == _column(lf.collect(), "ead_final")

    def test_basis_does_not_cross_real_estate_split_roles(self) -> None:
        """G1's spare on the secured leg cannot take over G2's residual leg."""
        # Arrange
        secured = _split(
            [_G("G1", 1000.0, 0.2, True), _G("G2", 500.0, 1.0, True)], role="secured_rre"
        )
        residual = _split(
            [_G("G1", 1000.0, 0.2, False), _G("G2", 500.0, 1.0, False)], role="residual"
        )
        for row in secured:
            row["exposure_reference"] += "_sec"
        for row in residual:
            row["exposure_reference"] += "_res"
        lf = _frame(secured + residual)

        # Act
        result = redistribute_non_beneficial(lf).collect()

        # Assert
        assert _column(result, "ead_final") == _column(lf.collect(), "ead_final")

    def test_single_unsplit_row_is_not_a_leg(self) -> None:
        # Arrange
        lf = _frame(
            _split([_G("G1", 1000.0, 0.2, True), _G("G2", 500.0, 1.0, False)])[:1]
        ).with_columns(pl.lit(_PARENT).alias("exposure_reference"))

        # Act
        result = redistribute_non_beneficial(lf).collect()

        # Assert
        assert result["ead_final"].to_list() == lf.collect()["ead_final"].to_list()

    def test_missing_columns_returns_unchanged(self) -> None:
        # Arrange
        lf = pl.LazyFrame({"exposure_reference": ["EXP001"], "ead_after_collateral": [1000.0]})

        # Act
        result = redistribute_non_beneficial(lf).collect()

        # Assert
        assert result.columns == ["exposure_reference", "ead_after_collateral"]
