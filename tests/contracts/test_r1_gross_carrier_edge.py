"""
Contract tests: the four floored gross-exposure carriers
(``reporting_gross_drawn`` / ``_interest`` / ``_nominal`` / ``_undrawn``) are
whitelisted on the sealed aggregator-exit edge alongside the other
``reporting_*`` projection columns, and — like ``reporting_ead`` — are produced
by the aggregator, so they must NOT appear on the calculator branch edges.

Also covers the two sealed per-side gross carriers (``reporting_gross_on_bs``
/ ``_off_bs`` — R-gross-side-carriers) that repoint the on/off-BS template
cells independently of ``reporting_on_balance_sheet``, closing the
facility_undrawn gap: the legacy exposure_type ladder recognises "loan" (on)
and "facility"/"contingent" (off) but never "facility_undrawn" — a dead
"facility" value stands in for it — so a facility_undrawn leg's headroom was
silently dropped from both gross-exposure sides while its EAD stayed in the
EAD/RWEA cells.

References:
- CRR Art. 111 (SA gross exposure value); Art. 166 (IRB exposure value)
- src/rwa_calc/engine/aggregator/aggregator.py::_add_reporting_projection
- .claude/state/gross-side-carriers-spec.md
"""

from __future__ import annotations

import polars as pl
import pytest

from rwa_calc.contracts.edges import AGGREGATOR_EXIT_EDGE, CALC_BRANCH_EDGES

_GROSS_CARRIERS = (
    "reporting_gross_drawn",
    "reporting_gross_interest",
    "reporting_gross_nominal",
    "reporting_gross_undrawn",
)

_SIDE_CARRIERS = (
    "reporting_gross_on_bs",
    "reporting_gross_off_bs",
)


@pytest.mark.parametrize("carrier", _GROSS_CARRIERS)
def test_aggregator_exit_declares_gross_carrier(carrier: str) -> None:
    """Each floored gross carrier is a Float64 column on the aggregator exit."""
    assert carrier in AGGREGATOR_EXIT_EDGE.columns
    assert AGGREGATOR_EXIT_EDGE.columns[carrier].dtype == pl.Float64


@pytest.mark.parametrize("carrier", _GROSS_CARRIERS)
@pytest.mark.parametrize("branch", ["sa_branch", "irb_branch", "slotting_branch"])
def test_gross_carrier_absent_from_branch_edges(carrier: str, branch: str) -> None:
    """The carriers are aggregator-produced (like reporting_ead) — not branch columns."""
    assert carrier not in CALC_BRANCH_EDGES[branch].columns


@pytest.mark.parametrize("carrier", _SIDE_CARRIERS)
def test_aggregator_exit_declares_side_carrier(carrier: str) -> None:
    """Each sealed per-side gross carrier is a Float64 column on the
    aggregator exit, cited to CRR Art. 111."""
    assert carrier in AGGREGATOR_EXIT_EDGE.columns
    assert AGGREGATOR_EXIT_EDGE.columns[carrier].dtype == pl.Float64
    assert AGGREGATOR_EXIT_EDGE.columns[carrier].citation == "CRR Art. 111"


@pytest.mark.parametrize("carrier", _SIDE_CARRIERS)
@pytest.mark.parametrize("branch", ["sa_branch", "irb_branch", "slotting_branch"])
def test_side_carrier_absent_from_branch_edges(carrier: str, branch: str) -> None:
    """The side carriers are aggregator-produced (like reporting_ead) — not branch columns."""
    assert carrier not in CALC_BRANCH_EDGES[branch].columns


class TestSideCarrierRuleSemantics:
    """The sealed per-side carriers' row-level rule (spec §Design), exercised
    directly against ``_add_reporting_projection`` — not the LedgerShim
    mirror, which only stands in for pre-existing unit fixtures.

    loan -> on-side drawn+interest, off-side true 0.0; contingent -> off-side
    nominal; facility_undrawn -> off-side undrawn (once, not aliased with
    nominal); a CCR exposure_type -> null on BOTH sides; a negative on-balance
    netting deposit floors to 0.0 rather than going negative (CRR Art.
    195/219 the same clip-at-0 convention as the four R1 carriers).
    """

    # Explicit dtypes so a None override (e.g. a genuinely absent
    # nominal_amount) keeps its column's real type instead of inferring Null
    # (which ``.clip()`` in the projection rejects).
    _ROW_DTYPES: dict[str, pl.DataType] = {
        "exposure_reference": pl.String(),
        "exposure_type": pl.String(),
        "drawn_amount": pl.Float64(),
        "interest": pl.Float64(),
        "nominal_amount": pl.Float64(),
        "undrawn_amount": pl.Float64(),
        "ead_final": pl.Float64(),
        "risk_weight": pl.Float64(),
        "exposure_class_applied": pl.String(),
        "exposure_class_post_crm": pl.String(),
        "exposure_class": pl.String(),
        "exposure_subclass": pl.String(),
        "approach_applied": pl.String(),
        "approach_post_crm": pl.String(),
        "is_guaranteed": pl.Boolean(),
    }

    def _projected(self, exposure_type: str, **overrides: object) -> dict[str, object]:
        """Run one row through the real aggregator projection step and
        return its ``reporting_gross_on_bs`` / ``_off_bs`` pair."""
        from rwa_calc.engine.aggregator.aggregator import _add_reporting_projection

        row: dict[str, object] = {
            "exposure_reference": ["E1"],
            "exposure_type": [exposure_type],
            "drawn_amount": [0.0],
            "interest": [0.0],
            "nominal_amount": [0.0],
            "undrawn_amount": [0.0],
            "ead_final": [1000.0],
            "risk_weight": [1.0],
            "exposure_class_applied": ["corporate"],
            "exposure_class_post_crm": ["corporate"],
            "exposure_class": ["corporate"],
            "exposure_subclass": [None],
            "approach_applied": ["standardised"],
            "approach_post_crm": ["standardised"],
            "is_guaranteed": [False],
        }
        row.update({k: [v] for k, v in overrides.items()})
        lf = pl.LazyFrame(row, schema=self._ROW_DTYPES)
        projected = _add_reporting_projection(lf).collect()
        return {
            "on": projected["reporting_gross_on_bs"][0],
            "off": projected["reporting_gross_off_bs"][0],
        }

    def test_loan_on_side_drawn_plus_interest_off_side_zero(self) -> None:
        result = self._projected("loan", drawn_amount=900.0, interest=100.0)
        assert result["on"] == pytest.approx(1000.0)
        assert result["off"] == pytest.approx(0.0)

    def test_contingent_off_side_is_nominal(self) -> None:
        result = self._projected("contingent", nominal_amount=2000.0)
        assert result["off"] == pytest.approx(2000.0)

    def test_facility_undrawn_off_side_counts_undrawn_once(self) -> None:
        """nominal_amount and undrawn_amount alias the same headroom on a
        facility_undrawn row — the off-side carrier must read it ONCE."""
        result = self._projected("facility_undrawn", nominal_amount=4000.0, undrawn_amount=4000.0)
        assert result["off"] == pytest.approx(4000.0)

    def test_ccr_exposure_type_is_null_both_sides(self) -> None:
        result = self._projected("ccr_netting_set", drawn_amount=2000.0)
        assert result["on"] is None
        assert result["off"] is None

    def test_negative_drawn_deposit_clips_to_zero(self) -> None:
        """A negative on-balance netting deposit floors to 0.0, never negative."""
        result = self._projected("loan", drawn_amount=-200_000.0, interest=0.0)
        assert result["on"] == pytest.approx(0.0)

    def test_facility_alias_off_side_recognised(self) -> None:
        """ "facility" is a legacy off-BS alias (Amendment 2): R11-era unit
        fixtures use it (test_c08_01.py:1125, test_c08_02.py:144), and the
        sealed ``reporting_on_balance_sheet`` / ``filter_off_bs`` / the
        ``c07_bs``/``c08_bs`` ladders all already map it to off-BS. A type the
        discriminators put on a side must have that side's carrier populated
        or the null-carrier asymmetry this fix removes is recreated (observed:
        C 08.01 col 0100 memo going negative, 0 - 500)."""
        result = self._projected("facility", nominal_amount=None, undrawn_amount=2000.0)
        assert result["off"] == pytest.approx(2000.0)
        assert result["on"] == pytest.approx(0.0)

        # nominal_amount and undrawn_amount alias the same headroom (as with
        # facility_undrawn) — max_horizontal counts the aliased pair once.
        aliased = self._projected("facility", nominal_amount=2000.0, undrawn_amount=2000.0)
        assert aliased["off"] == pytest.approx(2000.0)
