"""
A split exposure that ALSO carries financial collateral — the one shape on which
``collateral_adjusted_value`` is non-zero on a leg the RE splitter emitted.

Pipeline position:
    RE_SPLIT_WITH_FINANCIAL -> build_bundle -> PipelineOrchestrator
        -> AggregatedResultBundle (the sealed ledger these assertions read)

Why this file exists. The splitter allocates its per-exposure money carriers
across the legs it emits, and the collapse path must sum them back up. For most
carriers the estate already had a fixture that would notice a dropped share. For
``collateral_adjusted_value`` it did not, and the reason is structural rather
than accidental: on an RE-only split the carrier is ``0.00`` on every leg —
immovable property is recognised through the exposure class and the
Art. 125/124F secured cap, not through the Art. 223 volatility-adjusted
collateral value — while every fixture that DID populate the carrier had no
property and therefore never split. The two conditions were disjoint across the
whole estate, so a leg-share the collapse dropped would have left the parent row
holding one leg's fraction with nothing to object. ``collateral_adjusted_value``
is compared by the reconciliation engine, which makes that a live reconciliation
break, not a cosmetic one.

``test_the_re_only_split_portfolio_cannot_see_this`` is the first test below and
is the justification for the rest: it measures the carrier on ``RE_SPLIT`` and
asserts it is identically zero there. If that ever stops being true this file's
premise has changed and the reason should be re-read rather than the test
deleted.

Deliberately NOT asserted here: the generic collapse additivity identity over
every carrier, and the source-conservation identities. Those live in
``tests/contracts/test_collapse_additivity.py`` and
``tests/properties/test_collapse_conservation.py`` / ``test_source_conservation.py``.
What this file adds is the PORTFOLIO those identities need in order to be
non-vacuous for this carrier, plus the per-leg attribution they do not check.

References:
- CRR Art. 125 / Art. 126, PS1/26 Art. 124F / 124H: the loan-split route
- CRR Art. 197(1): eligible financial collateral — the second, independent route
- CRR Art. 223 / Art. 224: comprehensive-method volatility adjustments (cash
  takes none; a debt security does), which is what makes the two pledges
  distinguishable in the carrier
- PS1/26 Art. 124F(2): the prior-charge deduction, so one exposure's leg shares
  differ by regime
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl
import pytest

from tests.properties import portfolios as P
from tests.properties.corpus import RE_SPLIT, RE_SPLIT_WITH_FINANCIAL

if TYPE_CHECKING:
    from tests.properties.portfolios import ExposureSpec

_CARRIER: str = "collateral_adjusted_value"

_REGIMES: tuple[str, ...] = ("CRR", "B31")

#: Index into ``RE_SPLIT_WITH_FINANCIAL``. ``build_bundle`` assigns loan
#: references positionally (``LN{i:03d}``), so the parent reference is derived
#: from the index rather than written out — a reordered portfolio then moves the
#: expectation with it instead of silently pointing at a different exposure.
_IDX_CASH: int = 0
_IDX_BOND: int = 1
_IDX_PRIOR_CHARGE: int = 2
_IDX_UNSPLIT_CONTROL: int = 3


def _parent_ref(index: int) -> str:
    return f"LN{index:03d}"


def _parent_of(results: pl.DataFrame) -> pl.DataFrame:
    """Add the lineage key: the split parent, or the row itself when unsplit."""
    return results.with_columns(
        pl.coalesce(pl.col("split_parent_id"), pl.col("exposure_reference")).alias("parent")
    )


def _legs_of(results: pl.DataFrame, parent: str) -> pl.DataFrame:
    return _parent_of(results).filter(pl.col("parent") == parent)


def _spec(index: int) -> ExposureSpec:
    return RE_SPLIT_WITH_FINANCIAL[index]


class TestThePremise:
    """The measurement that makes this portfolio necessary."""

    @pytest.mark.parametrize("regime", _REGIMES)
    def test_the_re_only_split_portfolio_cannot_see_this(self, regime: str) -> None:
        """``RE_SPLIT`` splits, and carries ``collateral_adjusted_value == 0`` on
        every leg. A test of the split-then-collapse path for this carrier run
        against that portfolio would pass on a broken engine."""
        results = P.results_df(RE_SPLIT, regime)

        assert int(results["split_parent_id"].is_not_null().sum()) > 0, (
            "RE_SPLIT stopped splitting — the premise below rests on it splitting"
        )
        assert float(results[_CARRIER].fill_null(0.0).sum()) == pytest.approx(0.0)

    @pytest.mark.parametrize("regime", _REGIMES)
    def test_this_portfolio_both_splits_and_carries_the_value(self, regime: str) -> None:
        """The conjunction the estate lacked: split lineage AND a non-zero
        Art. 223 adjusted collateral value in the same run."""
        results = P.results_df(RE_SPLIT_WITH_FINANCIAL, regime)

        assert int(results["split_parent_id"].is_not_null().sum()) > 0
        assert {value for value in results["re_split_role"].to_list() if value is not None} == {
            "secured",
            "residual",
        }
        assert float(results[_CARRIER].fill_null(0.0).sum()) > 0.0


class TestTheCarrierReachesBothLegs:
    """The point of the fixture: both halves of a split carry their share."""

    @pytest.mark.parametrize("regime", _REGIMES)
    def test_both_legs_of_every_split_parent_carry_a_positive_share(self, regime: str) -> None:
        """Per leg, not per portfolio. A carrier inherited whole by one leg and
        dropped from the other sums to the same portfolio total as a correctly
        halved one, so only a per-leg assertion can tell them apart."""
        results = P.results_df(RE_SPLIT_WITH_FINANCIAL, regime)

        split_parents = sorted(
            {value for value in results["split_parent_id"].to_list() if value is not None}
        )
        assert len(split_parents) == 3, f"{regime}: expected three split parents"

        for parent in split_parents:
            legs = _legs_of(results, parent)
            assert legs.height == 2, f"{regime}/{parent}: expected a secured + residual pair"
            for row in legs.iter_rows(named=True):
                assert float(row[_CARRIER] or 0.0) > 0.0, (
                    f"{regime}/{parent}: leg {row['exposure_reference']} carries no "
                    f"{_CARRIER} — the split dropped its share"
                )

    @pytest.mark.parametrize("regime", _REGIMES)
    def test_each_parent_conserves_the_carrier_across_its_legs(self, regime: str) -> None:
        """Per-parent, so one parent's over-allocation cannot net against
        another's shortfall. Cash takes no Art. 224 volatility adjustment, so the
        conserved total is exactly the pledged market value and the tie needs no
        haircut arithmetic to state."""
        results = P.results_df(RE_SPLIT_WITH_FINANCIAL, regime)

        for index in (_IDX_CASH, _IDX_PRIOR_CHARGE, _IDX_UNSPLIT_CONTROL):
            spec = _spec(index)
            assert spec.financial_collateral_type == "cash"
            legs = _legs_of(results, _parent_ref(index))
            total = float(legs[_CARRIER].fill_null(0.0).sum())
            assert total == pytest.approx(spec.financial_collateral_value), (
                f"{regime}/{_parent_ref(index)}"
            )

    @pytest.mark.parametrize("regime", _REGIMES)
    def test_a_haircut_bearing_pledge_conserves_a_reduced_total(self, regime: str) -> None:
        """The bond leg. Art. 223/224 apply a volatility adjustment to a debt
        security, so the conserved total must be strictly BELOW the market value
        — and strictly above zero. A leg that carried the raw market value
        instead would satisfy neither bound."""
        results = P.results_df(RE_SPLIT_WITH_FINANCIAL, regime)

        spec = _spec(_IDX_BOND)
        assert spec.financial_collateral_type != "cash"
        legs = _legs_of(results, _parent_ref(_IDX_BOND))
        total = float(legs[_CARRIER].fill_null(0.0).sum())
        assert 0.0 < total < spec.financial_collateral_value

    @pytest.mark.parametrize("regime", _REGIMES)
    def test_the_share_follows_the_legs_ead(self, regime: str) -> None:
        """The splitter's single allocation basis is the leg's share of the
        parent EAD, so the carrier's split must match the EAD's. Asserted as a
        ratio rather than as an amount so it holds in both regimes even though
        the split point itself moves."""
        results = P.results_df(RE_SPLIT_WITH_FINANCIAL, regime)

        for index in (_IDX_CASH, _IDX_BOND, _IDX_PRIOR_CHARGE):
            legs = _legs_of(results, _parent_ref(index))
            parent_ead = float(legs["ead_final"].fill_null(0.0).sum())
            parent_carrier = float(legs[_CARRIER].fill_null(0.0).sum())
            assert parent_ead > 0.0, (
                f"{regime}/{_parent_ref(index)}: parent EAD is {parent_ead}, so the "
                "share below would divide by zero and the assertion could not fail"
            )
            assert parent_carrier > 0.0, (
                f"{regime}/{_parent_ref(index)}: parent {_CARRIER} is "
                f"{parent_carrier}, so this parent pledges nothing and the "
                "proportionality check would be vacuous"
            )

            for row in legs.iter_rows(named=True):
                ead_share = float(row["ead_final"] or 0.0) / parent_ead
                carrier_share = float(row[_CARRIER] or 0.0) / parent_carrier
                assert carrier_share == pytest.approx(ead_share), (
                    f"{regime}/{_parent_ref(index)}: leg {row['exposure_reference']} "
                    f"carries {carrier_share:.6f} of the collateral against "
                    f"{ead_share:.6f} of the EAD"
                )

    @pytest.mark.parametrize("regime", _REGIMES)
    def test_the_unsplit_control_row_is_untouched(self, regime: str) -> None:
        """The survivor leg (`.claude/LESSONS.md` B5). It pledges financial
        collateral and no property, so it never reaches the splitter — its
        carrier value must be the whole pledge on a single row. Without it, a
        change to the split allocation and a change to the carrier itself look
        identical."""
        results = P.results_df(RE_SPLIT_WITH_FINANCIAL, regime)

        legs = _legs_of(results, _parent_ref(_IDX_UNSPLIT_CONTROL))
        assert legs.height == 1
        row = legs.row(0, named=True)
        assert row["re_split_role"] is None
        assert row["split_parent_id"] is None
        assert float(row[_CARRIER]) == pytest.approx(
            _spec(_IDX_UNSPLIT_CONTROL).financial_collateral_value
        )


class TestRegimeDivergenceMovesTheShares:
    """The prior-charge exposure exists so the leg shares are NOT a constant.

    PS1/26 Art. 124F(2) deducts the prior charge from the secured cap and CRR
    Art. 125 does not, so this one exposure splits at two different points. A
    test that happened to pass on a hardcoded 50/50 share would fail here.
    """

    def test_the_secured_leg_carrier_share_differs_between_regimes(self) -> None:
        shares: dict[str, float] = {}
        for regime in _REGIMES:
            results = P.results_df(RE_SPLIT_WITH_FINANCIAL, regime)
            legs = _legs_of(results, _parent_ref(_IDX_PRIOR_CHARGE))
            secured = legs.filter(pl.col("re_split_role") == "secured").row(0, named=True)
            total = float(legs[_CARRIER].fill_null(0.0).sum())
            shares[regime] = float(secured[_CARRIER]) / total

        assert shares["CRR"] != pytest.approx(shares["B31"]), (
            "the encumbered exposure splits at the same point under both regimes, "
            "so the prior-charge deduction is not reaching the allocation"
        )
